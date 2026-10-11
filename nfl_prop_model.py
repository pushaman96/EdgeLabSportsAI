"""NFL yardage research, with a frozen 2024 fit and an untouched 2025 test.
No historical sportsbook prop prices are inferred from box scores.
"""
import csv
import io
import math
import re
import statistics
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import requests
import streamlit as st

MARKETS = {
 'player_pass_yds': ('Passing yards', 'passing_yards', 'attempts', ('QB',), 20),
 'player_rush_yds': ('Rushing yards', 'rushing_yards', 'carries', ('RB', 'HB', 'FB'), 8),
 'player_reception_yds': ('Receiving yards', 'receiving_yards', 'targets', ('WR', 'TE'), 3),
}
MODEL_VERSION = 'NFL yardage v1 / 2024 fit / 2025 test'
SCHEDULE_URL = 'https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv'
ALIASES = {'LAR': 'LA', 'WSH': 'WAS', 'JAC': 'JAX', 'LV': 'LV'}

def name_key(value):
    return re.sub(r'[^a-z0-9]', '', str(value).lower())

def num(value):
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (ValueError, TypeError):
        return None

def mean(values):
    return statistics.mean(values) if values else None

def csv_url(url):
    response = requests.get(url, timeout=40)
    response.raise_for_status()
    return list(csv.DictReader(io.StringIO(response.text.lstrip('\ufeff'))))

@st.cache_data(ttl=21600)
def load_season_stats(kind, season):
    rows = csv_url(f'https://github.com/nflverse/nflverse-data/releases/download/stats_{kind}/stats_{kind}_week_{season}.csv')
    required = {'season', 'week', 'season_type', 'team', 'opponent_team', 'game_id', 'passing_yards', 'rushing_yards', 'receiving_yards'}
    if kind == 'player':
        required |= {'player_id', 'player_display_name', 'position', 'attempts', 'carries', 'targets'}
    if not rows or not required.issubset(rows[0]):
        raise ValueError('NFL weekly stats are missing required fields.')
    return normalize_stats(rows, kind)

def normalize_stats(rows, kind):
    result = []
    seen = set()
    for row in rows:
        if row.get('season_type') != 'REG':
            continue
        if kind == 'player' and row.get('position') not in ('QB', 'RB', 'HB', 'FB', 'WR', 'TE'):
            continue
        converted = {k: row.get(k) for k in ['player_id', 'player_display_name', 'position', 'game_id']}
        converted.update(season=int(row['season']), week=int(row['week']), team=ALIASES.get(row['team'], row['team']), opponent_team=ALIASES.get(row['opponent_team'], row['opponent_team']))
        for key in ['passing_yards', 'rushing_yards', 'receiving_yards', 'attempts', 'carries', 'targets']:
            converted[key] = num(row.get(key))
        identity = (converted['game_id'], converted.get('player_id') if kind == 'player' else converted['team'])
        if identity in seen:
            raise ValueError('Duplicate NFL stat rows.')
        seen.add(identity)
        result.append(converted)
    return sorted(result, key=lambda r: (r['season'], r['week'], r['game_id']))

def indexes(players, teams):
    pi, ti, defense = defaultdict(list), defaultdict(list), defaultdict(list)
    for row in players:
        pi[(row['season'], row['player_id'])].append(row)
    for row in teams:
        ti[(row['season'], row['team'])].append(row)
        defense[(row['season'], row['opponent_team'])].append(row)
    return pi, ti, defense

def features(player, season, week, team, opponent, market, idx):
    _, stat, workload, positions, minimum = MARKETS[market]
    pi, ti, defense = idx
    history = [r for r in pi.get((season, player), []) if r['week'] < week and r['team'] == team][-8:]
    team_history = [r for r in ti.get((season, team), []) if r['week'] < week][-4:]
    if len(history) < 4 or len(team_history) < 4:
        return None, 'Fewer than four current-season games.'
    recent = history[-4:]
    if {r['game_id'] for r in recent} != {r['game_id'] for r in team_history}:
        return None, 'Missed games, a team change, or incomplete recent history.'
    if recent[-1]['position'] not in positions:
        return None, 'This position is not supported for this prop yet.'
    if any(r[stat] is None or r[workload] is None for r in history):
        return None, 'Missing yardage or workload data.'
    volume = mean([r[workload] for r in recent])
    if volume < minimum or min(r[workload] for r in recent[-2:]) < .6 * volume:
        return None, 'Low or recently unstable workload.'
    opponent_rows = [r for r in defense.get((season, opponent), []) if r['week'] < week][-4:]
    if len(opponent_rows) < 4 or any(r[stat] is None for r in opponent_rows):
        return None, 'Opponent has fewer than four usable games.'
    league = [r[stat] for values in ti.values() for r in values if r['season'] == season and max(1, week-4) <= r['week'] < week and r[stat] is not None]
    league_average = mean(league)
    if not league_average or league_average <= 0:
        return None, 'League comparison unavailable.'
    total_workload = sum(r[workload] for r in history)
    if total_workload <= 0:
        return None, 'No usable workload.'
    baseline = mean([r[stat] for r in recent])
    volume_forecast = .6 * mean([r[workload] for r in recent[-2:]]) + .4 * volume
    efficiency_forecast = volume_forecast * sum(r[stat] for r in history) / total_workload
    ratio = max(.75, min(1.25, mean([r[stat] for r in opponent_rows]) / league_average))
    return {'baseline': baseline, 'volume_forecast': volume_forecast, 'efficiency_forecast': efficiency_forecast, 'ratio': ratio, 'games': len(history), 'latest_week': recent[-1]['week'], 'player': recent[-1]['player_display_name'], 'position': recent[-1]['position']}, None

def projection(feature, blend, defense_weight):
    return max(0, ((1-blend)*feature['baseline'] + blend*feature['efficiency_forecast']) * (1+defense_weight*(feature['ratio']-1)))

def error_scale(projected):
    return max(15, .35*projected)

def over_probability(projected, line, residuals):
    # Yardage is integer-valued. Half-yard lines are supported, avoiding push ambiguity.
    cutoff = (line-projected)/error_scale(projected)
    raw = (sum(error > cutoff for error in residuals)+1)/(len(residuals)+2)
    return max(.05, min(.95, .5 + .8*(raw-.5)))

def samples_for_season(season, players, idx):
    samples = defaultdict(list)
    for row in players:
        if row['season'] != season:
            continue
        for market, (_, stat, _, positions, _) in MARKETS.items():
            if row['position'] not in positions or row[stat] is None:
                continue
            feature, _ = features(row['player_id'], season, row['week'], row['team'], row['opponent_team'], market, idx)
            if feature:
                samples[market].append((feature, row[stat]))
    return samples

def fit_and_test(players, teams):
    idx = indexes(players, teams)
    train = samples_for_season(2024, players, idx)
    test = samples_for_season(2025, players, idx)
    models, reports = {}, []
    for market, (label, *_rest) in MARKETS.items():
        if len(train[market]) < 100 or len(test[market]) < 100:
            continue
        candidates = [(blend, weight) for blend in (0, .5, 1) for weight in (0, .25, .5)]
        blend, weight = min(candidates, key=lambda pair: mean([abs(projection(f,*pair)-actual) for f,actual in train[market]]))
        residuals = sorted((actual-projection(f,blend,weight))/error_scale(projection(f,blend,weight)) for f,actual in train[market])
        tested = test[market]
        mae = mean([abs(projection(f,blend,weight)-actual) for f,actual in tested])
        baseline_mae = mean([abs(f['baseline']-actual) for f,actual in tested])
        # Fixed pregame benchmark thresholds, NOT reconstructed sportsbook lines.
        briers, correct = [], []
        for feature, actual in tested:
            line = math.floor(feature['baseline'])+.5
            p = over_probability(projection(feature,blend,weight), line, residuals)
            y = float(actual > line)
            briers.append((p-y)**2)
            correct.append((p >= .5) == bool(y))
        models[market] = {'blend': blend, 'defense_weight': weight, 'residuals': residuals, 'forecast_passed': mae < baseline_mae, 'mae': mae, 'baseline_mae': baseline_mae, 'test_count': len(tested)}
        reports.append({'Category': label, '2025 test forecasts': len(tested), 'Model error (yards, lower is better)': round(mae,2), 'Recent-average error (yards)': round(baseline_mae,2), 'Error improvement (yards)': round(baseline_mae-mae,2), 'Benchmark Brier': round(mean(briers),4), '50/50 benchmark Brier': .25, 'Benchmark accuracy %': round(mean(correct)*100,1), 'Forecast beats baseline': mae < baseline_mae})
    return models, reports

@st.cache_data(ttl=21600)
def load_prop_research(season):
    with ThreadPoolExecutor(max_workers=6) as pool:
        tasks = {(kind,y): pool.submit(load_season_stats,kind,y) for kind in ('player','team') for y in sorted({2024,2025,season})}
        values = {key: task.result() for key,task in tasks.items()}
    players = [r for (kind,_),rows in values.items() if kind == 'player' for r in rows]
    teams = [r for (kind,_),rows in values.items() if kind == 'team' for r in rows]
    schedule = csv_url(SCHEDULE_URL)
    models, reports = fit_and_test(players,teams)
    if len(models) != len(MARKETS):
        raise ValueError('Insufficient NFL historical model data.')
    return {'players':players,'teams':teams,'schedule':schedule,'models':models,'reports':reports,'retrieved':datetime.now(timezone.utc).isoformat(),'season':season}

@st.cache_data(ttl=300)
def injury_context():
    response = requests.get('https://site.api.espn.com/apis/site/v2/sports/football/nfl/injuries',timeout=20)
    response.raise_for_status()
    data = response.json()
    if not isinstance(data.get('injuries'),list):
        raise ValueError('Injury coverage unavailable.')
    teams, statuses = set(), {}
    for group in data['injuries']:
        team = group.get('displayName')
        teams.add(team)
        for item in group.get('injuries',[]):
            key = (team,name_key(item.get('athlete',{}).get('displayName')))
            # Multiple reports for one name: any non-active report takes precedence.
            status = item.get('status') or 'Unknown'
            if key not in statuses or status.lower() != 'active':
                statuses[key] = status
    return {'teams':teams,'statuses':statuses,'retrieved':datetime.now(timezone.utc).isoformat(),'season':data.get('season',{}).get('year'),'source_updated':data.get('timestamp')}

@st.cache_data(ttl=300)
def current_roster(team_id):
    response = requests.get(f'https://site.api.espn.com/apis/site/v2/sports/football/nfl/teams/{team_id}/roster',timeout=20)
    response.raise_for_status()
    rows = []
    for group in response.json().get('athletes',[]):
        for athlete in group.get('items',[]):
            status = athlete.get('status',{})
            rows.append({'name':athlete.get('displayName'),'status':status.get('name') if isinstance(status,dict) else str(status)})
    if not rows:
        raise ValueError('Current roster unavailable.')
    return rows

def event_context(event, scoreboard):
    for source in scoreboard.get('events',[]):
        competition = source.get('competitions',[{}])[0]
        home = next((r.get('team',{}) for r in competition.get('competitors',[]) if r.get('homeAway') == 'home'),{})
        away = next((r.get('team',{}) for r in competition.get('competitors',[]) if r.get('homeAway') == 'away'),{})
        if (home.get('displayName'),away.get('displayName')) != (event['home_team'],event['away_team']):
            continue
        source_start = datetime.fromisoformat(source['date'].replace('Z','+00:00'))
        odds_start = datetime.fromisoformat(event['commence_time'].replace('Z','+00:00'))
        if abs((source_start-odds_start).total_seconds()) > 3600:
            return None
        season = source.get('season',scoreboard.get('season',{}))
        return {'season':int(season['year']), 'regular':int(season['type']) == 2,'home':home,'away':away,'date':source_start.date()}
    return None

def prop_reviews(event, scoreboard, research, injuries, rosters, now=None):
    now = now or datetime.now(timezone.utc)
    context = event_context(event,scoreboard)
    rows = []
    idx = indexes(research['players'],research['teams'])
    starts = datetime.fromisoformat(event['commence_time'].replace('Z','+00:00'))
    matching = [g for g in research['schedule'] if context and int(g['season']) == context['season'] and g['game_type'] == 'REG' and {g['home_team'],g['away_team']} == {ALIASES.get(context[s].get('abbreviation'),context[s].get('abbreviation')) for s in ('home','away')} and g['gameday'] == context['date'].isoformat()]
    schedule = matching[0] if len(matching) == 1 else None
    for book in event.get('bookmakers',[]):
        for market in book.get('markets',[]):
            for outcome in market.get('outcomes',[]):
                if market['key'] not in MARKETS:
                    continue
                row = {'Decision':'Pass','Game':event['away_team']+' at '+event['home_team'],'Player':outcome.get('description','Unknown'),'Category':MARKETS[market['key']][0],'Selection':outcome.get('name'),'Line':outcome.get('point'),'Sportsbook':book['title'],'Odds':outcome.get('price'),'Projection (yards)':None,'Historical error range low':None,'Historical error range high':None,'Estimated win %':None,'Break-even %':None,'Model edge (pp)':None,'Reason':'','Quote updated UTC':market.get('last_update') or book.get('last_update'),'Model':MODEL_VERSION}
                rows.append(row)
                if starts <= now or not context or not context['regular'] or not schedule:
                    row['Reason'] = 'Game started or regular-season schedule match unavailable.';continue
                try:
                    age = (now-datetime.fromisoformat(row['Quote updated UTC'].replace('Z','+00:00'))).total_seconds()
                except (ValueError,TypeError,AttributeError):
                    age = 99999
                if not 0 <= age <= 900:
                    row['Reason'] = 'Quote older than 15 minutes or timestamp unavailable.';continue
                line = num(row['Line']);odds = num(row['Odds'])
                if line is None or line < 0 or not math.isclose(line%1,.5) or odds is None or abs(odds)<100 or row['Selection'] not in ('Over','Under'):
                    row['Reason'] = 'Only valid prices and half-yard over/under lines are supported.';continue
                key = name_key(row['Player'])
                roster_matches = [(side,p) for side in ('home','away') for p in rosters.get(context[side].get('displayName'),[]) if name_key(p['name']) == key]
                if len(roster_matches) != 1:
                    row['Reason'] = 'Player cannot be matched uniquely to a current game roster.';continue
                side,player = roster_matches[0]
                team_name = context[side]['displayName']
                if not injuries or team_name not in injuries['teams']:
                    row['Reason'] = 'Injury report coverage unavailable for this team.';continue
                try:
                    injury_age = (now-datetime.fromisoformat(injuries['source_updated'].replace('Z','+00:00'))).total_seconds()
                    retrieval_age = (now-datetime.fromisoformat(injuries['retrieved'])).total_seconds()
                except (ValueError,TypeError,AttributeError,KeyError):
                    injury_age = retrieval_age = 99999
                if int(injuries.get('season') or 0) != context['season'] or not -600 <= injury_age <= 21600 or not 0 <= retrieval_age <= 900:
                    row['Reason'] = 'Injury report is stale or from a different season.';continue
                status = injuries['statuses'].get((team_name,key),'Not listed')
                if status.lower() not in ('active','not listed') or str(player.get('status','')).lower() != 'active':
                    row['Reason'] = 'Availability uncertain: '+status+' / roster '+str(player.get('status'));continue
                team = ALIASES.get(context[side]['abbreviation'],context[side]['abbreviation'])
                opponent_side = 'away' if side == 'home' else 'home'
                opponent = ALIASES.get(context[opponent_side]['abbreviation'],context[opponent_side]['abbreviation'])
                ids = {r['player_id'] for r in research['players'] if r['season'] == context['season'] and r['team'] == team and name_key(r['player_display_name']) == key}
                if len(ids) != 1:
                    row['Reason'] = 'No unique current-season player-stat match.';continue
                feature,reason = features(next(iter(ids)),context['season'],int(schedule['week']),team,opponent,market['key'],idx)
                if not feature:
                    row['Reason'] = reason;continue
                coverage_ok = True
                for code, values in [(team,idx[1].get((context['season'],team),[])), (opponent,idx[2].get((context['season'],opponent),[]))]:
                    completed = [g for g in research['schedule'] if int(g['season']) == context['season'] and g['game_type'] == 'REG' and code in (g['home_team'],g['away_team']) and int(g['week']) < int(schedule['week']) and num(g.get('home_score')) is not None and num(g.get('away_score')) is not None]
                    expected = {g['game_id'] for g in sorted(completed,key=lambda g:int(g['week']))[-4:]}
                    observed = {r['game_id'] for r in values if r['week'] < int(schedule['week'])}
                    if len(expected) < 4 or not expected.issubset(observed):coverage_ok = False
                if not coverage_ok:
                    row['Reason'] = 'Weekly stats do not cover the most recent completed team/opponent games.';continue
                last_games = [g for g in research['schedule'] if int(g['season']) == context['season'] and int(g['week']) == feature['latest_week'] and team in (g['home_team'],g['away_team']) and g['game_type']=='REG']
                if not last_games or not 0 <= (context['date']-datetime.fromisoformat(last_games[0]['gameday']).date()).days <= 21:
                    row['Reason'] = 'Player history too old for this game.';continue
                model = research['models'][market['key']]
                projected = projection(feature,model['blend'],model['defense_weight'])
                residuals=model['residuals']
                lower=projected+residuals[int(.1*(len(residuals)-1))]*error_scale(projected)
                upper=projected+residuals[math.ceil(.9*(len(residuals)-1))]*error_scale(projected)
                row['Historical error range low']=round(max(0,lower),1)
                row['Historical error range high']=round(max(0,upper),1)
                p = over_probability(projected,line,model['residuals'])
                if row['Selection'] == 'Under':p = 1-p
                break_even = 100/(odds+100) if odds>0 else abs(odds)/(abs(odds)+100)
                row.update({'Projection (yards)':round(projected,1),'Estimated win %':round(p*100,1),'Break-even %':round(break_even*100,1),'Model edge (pp)':round((p-break_even)*100,1)})
                if not model['forecast_passed']:
                    row['Reason'] = 'Forecast did not beat the recent-average baseline on the 2025 test.';continue
                if p-break_even < .05:
                    row['Reason'] = 'Estimated edge below five percentage points.';continue
                row['Decision'] = 'Watch — experimental'
                row['Reason'] = f"{feature['games']} recent games; expected {feature['volume_forecast']:.1f} opportunities; opponent allowed {feature['ratio']*100:.0f}% of league yardage average. Availability: {status}. Confirm lineup/weather."
    return sorted(rows,key=lambda r:(r['Decision']=='Pass',-(r['Model edge (pp)'] or -999)))

def clear_prop_shortlist(rows):
    grouped=defaultdict(list)
    for row in rows:
        grouped[(row['Game'],name_key(row.get('Player','')),row.get('Category',''))].append(row)
    def score(row):
        probability=num(row.get('Estimated win %'))
        odds=num(row.get('Odds'))
        if probability is None or odds is None or abs(odds)<100:return -999
        decimal=1+odds/100 if odds>0 else 1+100/abs(odds)
        return probability/100*decimal-1
    result=[]
    for group in grouped.values():
        candidates=[r for r in group if r['Decision']!='Pass']
        directions={r.get('Selection') for r in candidates}
        if len(directions)==1 and directions.issubset({'Over','Under'}):
            row=dict(max(candidates,key=score))
            row['Paper pick']=f"{row['Player']} {row['Selection'].upper()} {row['Line']} {row['Category'].lower()}"
            if len(candidates)>1:row['Reason'] += ' One loaded quote retained by estimated return; other sportsbook entries consolidated.'
        else:
            row=dict(max(group,key=lambda r:num(r.get('Model edge (pp)')) or -999))
            row['Decision']='Pass'
            if candidates:row['Reason']='Qualifying Over and Under quotes conflict or no supported direction exists. No single paper pick.'
            row.update({'Paper pick':'PASS — no pick','Selection':'—','Line':'—','Sportsbook':'—','Odds':'—','Estimated win %':None,'Break-even %':None,'Model edge (pp)':None})
        # Put the explicit direction first in the displayed/exported table.
        result.append({'Paper pick':row.pop('Paper pick'),**row})
    return sorted(result,key=lambda r:(r['Decision']=='Pass',-(num(r.get('Model edge (pp)')) or -999)))

def render_prop_research(event, scoreboard, books, quote_retrieved, auto_analyze=False):
    events = event if isinstance(event,list) else [event]
    starts = {e['away_team']+' at '+e['home_team']:e['commence_time'] for e in events}
    st.subheader('NFL prop shortlist — one direction or Pass')
    st.caption('Passing, rushing and receiving yardage only. Receptions and QB rushing are not modeled yet. Experimental probabilities use 2024 forecast errors; 2025 is the held-out test. This test does not establish profit at sportsbook prices.')
    cache_key = (tuple(e['id'] for e in events), quote_retrieved, tuple(sorted(books)))
    analyze = st.button('Analyze all loaded player props' if len(events)>1 else 'Analyze loaded player props',key='nfl_analyze_props')
    if auto_analyze or analyze:
        try:
            contexts = [event_context(e,scoreboard) for e in events]
            usable = [c for c in contexts if c and c['regular']]
            if not usable:
                st.info('Pass: no matching upcoming NFL regular-season games.');return
            if len({c['season'] for c in usable}) != 1:
                st.info('Pass: loaded games must belong to the same NFL season.');return
            with st.spinner('Testing historical forecasts and checking current player availability...'):
                research = load_prop_research(usable[0]['season'])
                injury_context.clear()
                injuries = injury_context()
                team_ids = {c[side]['displayName']:c[side]['id'] for c in usable for side in ('home','away')}
                rosters = {}
                issues = []
                with ThreadPoolExecutor(max_workers=4) as pool:
                    tasks = {team:pool.submit(current_roster,tid) for team,tid in team_ids.items()}
                    for team,task in tasks.items():
                        try:rosters[team] = task.result()
                        except (requests.exceptions.RequestException,ValueError,KeyError,TypeError,AttributeError,OSError):
                            issues.append(team+': roster unavailable; affected props stay on Pass.')
                rows = []
                for loaded in events:
                    filtered = dict(loaded,bookmakers=[b for b in loaded.get('bookmakers',[]) if b['title'] in books])
                    rows.extend(prop_reviews(filtered,scoreboard,research,injuries,rosters))
                rows.sort(key=lambda r:(r['Decision']=='Pass',-(r['Model edge (pp)'] or -999)))
                st.session_state['nfl_prop_analysis'] = {'key':cache_key,'rows':rows,'reports':research['reports'],'retrieved':research['retrieved'],'analyzed':datetime.now(timezone.utc).isoformat(),'issues':issues}
        except (requests.exceptions.RequestException, ValueError, KeyError, TypeError, AttributeError, OSError):
            st.warning('Pass: player history, roster, schedule or injury data could not be verified. Try again later.');return
    saved = st.session_state.get('nfl_prop_analysis')
    if not saved or saved['key'] != cache_key:
        st.info('Click Analyze loaded player props. Analysis uses free statistics and does not request more sportsbook credits.');return
    # Recheck quote age on every display, rather than leaving an old shortlist actionable.
    now = datetime.now(timezone.utc)
    display = []
    for original in saved['rows']:
        row = dict(original)
        try:
            quote_age = (now-datetime.fromisoformat(row['Quote updated UTC'].replace('Z','+00:00'))).total_seconds()
            analysis_age = (now-datetime.fromisoformat(saved['analyzed'])).total_seconds()
            start = datetime.fromisoformat(starts[row['Game']].replace('Z','+00:00'))
            if quote_age > 900 or quote_age < 0 or analysis_age > 900 or start <= now:
                row.update(Decision='Pass',Reason='Quote/availability analysis expired or game started. Refresh and analyze again.')
        except (ValueError,TypeError,AttributeError):
            row.update(Decision='Pass',Reason='Quote timestamp unavailable.')
        display.append(row)
    display=clear_prop_shortlist(display)
    for issue in saved.get('issues',[]):st.warning(issue)
    st.caption(f'Combined results for {len(events)} loaded NFL game(s).')
    watch = [r for r in display if r['Decision'] != 'Pass']
    st.write(f'**{len(watch)} unique experimental paper picks; {len(display)-len(watch)} player/category passes.**')
    picks_only=st.checkbox('Show only qualifying paper picks',key='nfl_only_clear_picks')
    table=watch if picks_only else display
    if table:st.dataframe(table,hide_index=True,use_container_width=True)
    if watch:
        st.caption('One experimental paper direction per player/category; the retained quote has the highest estimated return among qualifying loaded quotes. Historical error ranges use the middle 80% of scaled 2024 forecast errors, not guaranteed limits. Confirm player participation and conditions. Profitability at actual sportsbook prices is unverified.')
    else:
        st.info('PASS: no supported player props meet the current research filters. No bet is suggested.')
    with st.expander('Check the yardage model test results'):
        st.dataframe(saved['reports'],hide_index=True,use_container_width=True)
        st.caption('2024 chooses forecast parameters and supplies errors; 2025 tests them without refitting. Forecasts use only earlier weeks, current-season workload and opponent yardage allowed. Baseline is the preceding four-game yardage average. Benchmark thresholds are that pregame average rounded down plus 0.5 yards, not actual sportsbook lines. Missing player game rows are not invented as zero-yard outcomes. Injuries, weather and lineup changes were not backtested. Rushing/receiving models that fail the forecast baseline stay on Pass.')
        st.markdown('[Statistics source: nflverse](https://nflreadr.nflverse.com/reference/load_player_stats.html)')
    if display:
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer,fieldnames=['Recorded UTC','Game starts UTC']+list(dict.fromkeys(key for row in display for key in row)))
        writer.writeheader()
        for row in display:
            writer.writerow({'Recorded UTC':saved['analyzed'],'Game starts UTC':starts[row['Game']],**row})
        st.download_button('Download this prop analysis',buffer.getvalue(),file_name='nfl_prop_analysis.csv',mime='text/csv',key='nfl_prop_export')
    st.caption(f"Analysis time: {saved['analyzed']}. Statistics retrieved: {saved['retrieved']}. This is a research shortlist; no automatic bets are placed.")
