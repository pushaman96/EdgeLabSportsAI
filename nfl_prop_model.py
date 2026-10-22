from probability_order import highest_probability
from team_emblems import render_team_table
from pick_readiness import render_source_status
from automatic_reports import autosave_report, load_report
"""NFL prop research: 2024 fit, 2025 historical development, future paper testing.
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
from zoneinfo import ZoneInfo
import requests
import streamlit as st
from pick_history import publish_rows

MARKETS = {
 'player_pass_yds': ('Passing yards', 'passing_yards', 'attempts', ('QB',), 20),
 'player_rush_yds': ('Rushing yards', 'rushing_yards', 'carries', ('RB', 'HB', 'FB'), 8),
 'player_reception_yds': ('Receiving yards', 'receiving_yards', 'targets', ('WR', 'TE'), 3),
}
COUNT_MARKETS = {
 'player_receptions': ('Receptions','receptions','targets',('WR','TE','RB','HB','FB'),3),
 'player_pass_attempts': ('Passing attempts','attempts','attempts',('QB',),20),
 'player_rush_attempts': ('Rushing attempts','carries','carries',('RB','HB','FB'),8),
}
MARKETS.update(COUNT_MARKETS)
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
def load_season_stats(kind, season, schema_version=4):
    rows = csv_url(f'https://github.com/nflverse/nflverse-data/releases/download/stats_{kind}/stats_{kind}_week_{season}.csv')
    required = {'season', 'week', 'season_type', 'team', 'opponent_team', 'game_id', 'passing_yards', 'rushing_yards', 'receiving_yards'}
    if kind == 'player':
        required |= {'player_id', 'player_display_name', 'position', 'attempts', 'carries', 'targets', 'receptions'}
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
        for key in ['passing_yards', 'rushing_yards', 'receiving_yards', 'attempts', 'carries', 'targets', 'receptions', 'passing_interceptions', 'completions', 'passing_tds', 'rushing_tds', 'receiving_tds']:
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

def features(player, season, week, team, opponent, market, idx, history_games=4):
    if history_games not in (3,4):raise ValueError("Unsupported history window.")
    _, stat, workload, positions, minimum = MARKETS[market]
    pi, ti, defense = idx
    history = [r for r in pi.get((season, player), []) if r['week'] < week and r['team'] == team][-8:]
    team_history = [r for r in ti.get((season, team), []) if r['week'] < week][-history_games:]
    if len(history) < history_games or len(team_history) < history_games:
        return None, f'Fewer than {history_games} current-season games.'
    recent = history[-history_games:]
    if recent[-1]['position'] not in positions:
        return None, 'This position is not supported for this prop yet.'
    expected={r['game_id'] for r in team_history}
    observed={r['game_id'] for r in history}
    missing=sorted(expected-observed)
    if missing:
        return None, ('Recent player-stat coverage gap: '+', '.join(missing)+
            '. A missing row does not establish an injury or DNP. No zero is assumed; the model requires the latest '+str(history_games)+' team games.')
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

def over_probability(projected, line, residuals, strength=.8):
    # Yardage is integer-valued. Half-yard lines are supported, avoiding push ambiguity.
    cutoff = (line-projected)/error_scale(projected)
    raw = (sum(error > cutoff for error in residuals)+1)/(len(residuals)+2)
    return max(.05, min(.95, .5 + strength*(raw-.5)))

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
        reports.append({'Category': label, '2025 test forecasts': len(tested), 'Model error (category units, lower is better)': round(mae,2), 'Recent-average error (category units)': round(baseline_mae,2), 'Error improvement (category units)': round(baseline_mae-mae,2), 'Benchmark Brier': round(mean(briers),4), '50/50 benchmark Brier': .25, 'Benchmark accuracy %': round(mean(correct)*100,1), 'Forecast beats baseline': mae < baseline_mae})
    return models, reports

@st.cache_data(ttl=21600)
def load_prop_research(season,research_schema=3):
    with ThreadPoolExecutor(max_workers=6) as pool:
        tasks = {(kind,y): pool.submit(load_season_stats,kind,y) for kind in ('player','team') for y in sorted({2023,2024,2025,season-1,season})}
        values = {key: task.result() for key,task in tasks.items()}
    players = [r for (kind,_),rows in values.items() if kind == 'player' for r in rows]
    teams = [r for (kind,_),rows in values.items() if kind == 'team' for r in rows]
    schedule = csv_url(SCHEDULE_URL)
    models, reports = fit_and_test(players,teams)
    if len(models) != len(MARKETS):
        raise ValueError('Insufficient NFL historical model data.')
    from nfl_passing_forecasts import validate as validate_passing_counts
    passing_reports=validate_passing_counts(players,teams)
    from nfl_season_prior import validate as validate_season_prior
    season_prior_reports=validate_season_prior(players,teams)
    from workload_candidates import validate_nfl
    workload_reports=validate_nfl(players,teams)
    from nfl_scoring_models import td_validate,total_validate
    td_report=td_validate(players);total_report=total_validate(schedule)
    return {'td_report':td_report,'total_report':total_report,'workload_reports':workload_reports,'season_prior_reports':season_prior_reports,'passing_count_reports':passing_reports,'schema_version':research_schema,'players':players,'teams':teams,'schedule':schedule,'models':models,'reports':reports,'retrieved':datetime.now(timezone.utc).isoformat(),'season':season}

@st.cache_data(ttl=300)
def injury_context():
    response = requests.get('https://site.api.espn.com/apis/site/v2/sports/football/nfl/injuries',timeout=20)
    response.raise_for_status()
    data = response.json()
    if not isinstance(data.get('injuries'),list):
        raise ValueError('Injury coverage unavailable.')
    teams, statuses, rows = set(), {}, []
    for group in data['injuries']:
        team = group.get('displayName')
        teams.add(team)
        for item in group.get('injuries',[]):
            key = (team,name_key(item.get('athlete',{}).get('displayName')))
            # Multiple reports for one name: any non-active report takes precedence.
            status = item.get('status') or 'Unknown'
            if key not in statuses or status.lower() != 'active':
                statuses[key] = status
            rows.append({'Team':team,'Player':item.get('athlete',{}).get('displayName'),'Status':status,'Short comment':item.get('shortComment')or'','Report updated UTC':item.get('date')})
    return {'teams':teams,'statuses':statuses,'rows':rows,'retrieved':datetime.now(timezone.utc).isoformat(),'season':data.get('season',{}).get('year'),'source_updated':data.get('timestamp')}

@st.cache_data(ttl=300)
def current_roster(team_id):
    response = requests.get(f'https://site.api.espn.com/apis/site/v2/sports/football/nfl/teams/{team_id}/roster',timeout=20)
    response.raise_for_status()
    rows = []
    for group in response.json().get('athletes',[]):
        for athlete in group.get('items',[]):
            status = athlete.get('status',{})
            rows.append({'name':athlete.get('displayName'),'status':status.get('name') if isinstance(status,dict) else str(status),'position':athlete.get('position',{}).get('abbreviation'),'espn_id':str(athlete.get('id',''))})
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
        return {'season':int(season['year']), 'regular':int(season['type']) == 2,'home':home,'away':away,'date':source_start.astimezone(ZoneInfo('America/Los_Angeles')).date(),'espn_event':source}
    return None

def prop_reviews(event, scoreboard, research, injuries, rosters, now=None):
    now = now or datetime.now(timezone.utc)
    context = event_context(event,scoreboard)
    rows = []
    idx = indexes(research['players'],research['teams'])
    starts = datetime.fromisoformat(event['commence_time'].replace('Z','+00:00'))
    matching = [g for g in research['schedule'] if context and int(g['season']) == context['season'] and g['game_type'] == 'REG' and {g['home_team'],g['away_team']} == {ALIASES.get(context[s].get('abbreviation'),context[s].get('abbreviation')) for s in ('home','away')} and g['gameday'] == context['date'].isoformat()]
    schedule = matching[0] if len(matching) == 1 else None
    arrival_cache={}
    passing_cache={}
    evidence_inputs={}
    from interception_model import estimate as interception_estimate, validation as interception_validation
    interception_report = interception_validation(research['players'],research['teams'])
    from nfl_passing_forecasts import MARKETS as PASSING_MARKETS,estimate as passing_estimate,evaluated_row,targets as target_forecast
    supported = dict(MARKETS, player_pass_interceptions=('Passing interceptions',), **PASSING_MARKETS)
    def cached_passing(pid,season,week,team,opponent,field):
        key=(pid,season,week,team,opponent,field)
        if key not in passing_cache:passing_cache[key]=passing_estimate(pid,season,week,team,opponent,idx,field)
        return passing_cache[key]

    for book in event.get('bookmakers',[]):
        for market in book.get('markets',[]):
            for outcome in market.get('outcomes',[]):
                if market['key'] not in supported:
                    continue
                row = {'Decision':'Pass','Game':event['away_team']+' at '+event['home_team'],'Player':outcome.get('description','Unknown'),'Category':supported[market['key']][0],'Selection':outcome.get('name'),'Line':outcome.get('point'),'Sportsbook':book['title'],'Odds':outcome.get('price'),'Projection (yards)':None,'Historical error range low':None,'Historical error range high':None,'Estimated win %':None,'Break-even %':None,'Model edge (pp)':None,'Reason':'','Quote updated UTC':market.get('last_update') or book.get('last_update'),'Model':MODEL_VERSION}
                if market['key'] in COUNT_MARKETS:row['Model']='NFL count forecast v1 / 2024 fit / 2025 development'
                rows.append(row)
                if starts <= now:
                    row['Reason'] = 'Game already started; pregame analysis closed.';continue
                if not context:
                    row['Reason'] = 'ESPN matchup or kickoff time could not be matched.';continue
                from pick_history import verified_pregame_start
                try:verified_pregame_start(context['espn_event'],event['commence_time'],now)
                except (ValueError,KeyError,TypeError):row['Reason']='ESPN or sportsbook indicates the pregame window is closed.';continue
                if not context['regular']:
                    row['Reason'] = 'This game is not a regular-season matchup.';continue
                if not schedule:
                    row['Reason'] = 'No unique regular-season schedule match for '+context['date'].isoformat()+'.';continue
                try:
                    age = (now-datetime.fromisoformat(row['Quote updated UTC'].replace('Z','+00:00'))).total_seconds()
                except (ValueError,TypeError,AttributeError):
                    age = 99999
                if not 0 <= age <= 900:
                    row['Reason'] = 'Quote older than 15 minutes or timestamp unavailable.';continue
                line = num(row['Line']);odds = num(row['Odds'])
                if market['key']=='player_reception_yds' and line is not None and line<15:
                    row['Reason']='Receiving line below your 15-yard minimum; excluded from picks.';continue
                if line is None or line < 0 or not math.isclose(line%1,.5) or odds is None or abs(odds)<100 or row['Selection'] not in ('Over','Under'):
                    row['Reason'] = 'Only valid prices and half-unit over/under lines are supported.';continue
                key = name_key(row['Player'])
                roster_matches = [(side,p) for side in ('home','away') for p in rosters.get(context[side].get('displayName'),[]) if name_key(p['name']) == key and (not p.get('position') or p['position'] in ('QB','RB','HB','FB','WR','TE'))]
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
                from trade_awareness import player_context,transition_reason
                trade,trade_error=player_context(row['Player'],team,context['season'],int(schedule['week']),research['players'])
                if not trade:
                    row['Reason']=trade_error;continue
                row.update({k:v for k,v in trade.items() if k!='player_id'})
                prior=[r for r in research['players'] if r.get('player_id')==trade['player_id'] and (r['season'],r['week'])<(context['season'],int(schedule['week']))]
                history_ids={r.get('game_id') for r in prior}
                history_dates=[g['gameday'] for g in research['schedule'] if g.get('game_id') in history_ids and g.get('gameday')]
                row.update({'Statistics retrieved UTC':research.get('retrieved'),'Injury source updated UTC':injuries.get('source_updated'),'Injury retrieved UTC':injuries.get('retrieved'),'Roster checked UTC':now.isoformat(),'Player history through':max(history_dates) if history_dates else None})
                evidence_inputs[row['Player'],row['Category']]={'history':prior,'team':team,'opponent':opponent,'team_name':team_name,'team_id':context[side].get('id'),'athlete_id':player.get('espn_id')}

                ids={trade['player_id']}
                if team not in arrival_cache:
                    from trade_awareness import new_teammates
                    arrival_cache[team]=new_teammates(rosters.get(team_name,[]),team,context['season'],int(schedule['week']),research['players'])
                arrivals=[n for n in arrival_cache[team] if name_key(n)!=key]
                if arrivals:row['New teammates — role uncertainty']=', '.join(arrivals)
                # Season priors have their own chronological category/stage gate.
                from nfl_season_prior import estimate as prior_estimate,evaluated_row as prior_row
                candidate=prior_estimate(trade['player_id'],context['season'],int(schedule['week']),team,opponent,market['key'],idx)
                if market['key']=='player_pass_interceptions' and line!=.5:candidate=None
                if candidate:
                    prior_report=research.get('season_prior_reports',{}).get((market['key'],candidate['cohort']),{'passed':False,'residuals':[]})
                    from nfl_opportunity import candidate as matchup_candidate,VERSION as MATCHUP_VERSION
                    context_candidate=matchup_candidate(trade['player_id'],context['season'],int(schedule['week']),team,opponent,market['key'],idx)
                    context_report=prior_report.get('opportunity_report',{})
                    if context_candidate:
                        row['Matchup homework']=context_candidate['homework']
                        row['Opportunity candidate']={'version':MATCHUP_VERSION,'projection':context_candidate['projected'],'opportunities':context_candidate['opportunities'],'benchmark':{k:v for k,v in context_report.items()if k!='residuals'}}
                        if context_report.get('residuals')and prior_report.get('residuals'):
                            from forecast_benchmark import probability as candidate_probability
                            from nfl_season_prior import over_probability as incumbent_probability
                            bp=incumbent_probability(candidate['projected'],line,prior_report,candidate['uncertainty'])
                            cp=candidate_probability(context_candidate['projected'],line,context_report['residuals'],context_report.get('temperature',1))
                            if bp is not None and cp is not None:
                                row['Research model comparison']=[{'version':MATCHUP_VERSION,'incumbent_projection':candidate['projected'],'candidate_projection':context_candidate['projected'],
                                    'incumbent_probability':1-bp if row['Selection']=='Under'else bp,'candidate_probability':1-cp if row['Selection']=='Under'else cp,
                                    'line':line,'selection':row['Selection'],'historical_checks_passed':context_report.get('passed',False)}]
                    use_context=bool(context_candidate and context_report.get('passed'))
                    if use_context:
                        candidate=dict(context_candidate,uncertainty=1.)
                        prior_report=dict(context_report,forecast_mae=context_report['candidate_mae'],baseline_mae=context_report['simple_baseline_mae'])
                    row['Last-season blend candidate projection']=round(candidate['projected'],2)
                    if candidate['current_games']<4 or prior_report.get('passed'):
                        for code,values in ((team,idx[1].get((context['season'],team),[])),(opponent,idx[2].get((context['season'],opponent),[]))):
                            completed=[g for g in research['schedule'] if int(g['season'])==context['season'] and g['game_type']=='REG' and code in (g['home_team'],g['away_team']) and int(g['week'])<int(schedule['week']) and num(g.get('home_score')) is not None and num(g.get('away_score')) is not None]
                            expected={g['game_id'] for g in sorted(completed,key=lambda g:int(g['week']))[-4:]}
                            observed={r['game_id'] for r in values if r['week']<int(schedule['week'])}
                            if not expected.issubset(observed):candidate=dict(candidate,coverage_gap=True)
                        row.update(prior_row(row,candidate,prior_report))
                        if use_context:
                            row.update({'Model':MATCHUP_VERSION,'Base model':MATCHUP_VERSION,'Opportunity model applied':True,'Matchup model applied':True})
                            row['Reason']='Team volume × player workload share and bounded opponent-volume candidate passed later historical workload/stat and synthetic-line probability checks. '+row['Reason']
                        from workload_candidates import nfl_sample,attach
                        sample=nfl_sample(dict(player_id=trade['player_id'],season=context['season'],week=int(schedule['week']),team=team,opponent_team=opponent),market['key'],idx)
                        absent=[p['name'] for p in rosters.get(team_name,[]) if str(injuries['statuses'].get((team_name,name_key(p['name'])),p.get('status',''))).lower() in ('out','injured reserve','ir','suspended','inactive')]
                        attach(row,sample,research.get('workload_reports',{}).get((market['key'],candidate['cohort'])),absent)
                        from contextual_forecasts import nfl_situation
                        situations=nfl_situation(team,opponent,context['date'],research['schedule'],research['teams'])
                        if situations:row['Game context scenarios']={'Forecast':situations,'Use':'Historical margin scenarios only; no extra adjustment to this candidate or evidence of causation'}
                        continue
                trade_error=transition_reason(trade)
                if trade_error:
                    row['Reason']=trade_error;continue
                interception = market['key']=='player_pass_interceptions'
                passing_count = market['key'] in PASSING_MARKETS
                if interception and line != .5:
                    row['Reason']='Interception model supports only Over/Under 0.5; other thresholds not validated.';continue
                if interception or passing_count:
                    from boosted_yardage import base_feature
                    feature,reason=base_feature({'player_id':next(iter(ids)),'season':context['season'],'week':int(schedule['week']),'team':team,'opponent_team':opponent},'player_pass_attempts',idx)
                elif research['models'].get(market['key'],{}).get('boosted'):
                    from boosted_yardage import base_feature
                    feature,reason=base_feature({'player_id':next(iter(ids)),'season':context['season'],'week':int(schedule['week']),'team':team,'opponent_team':opponent},market['key'],idx)
                else:
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
                if passing_count:
                    field=PASSING_MARKETS[market['key']][1]
                    forecast,reason=cached_passing(next(iter(ids)),context['season'],int(schedule['week']),team,opponent,field)
                    if not forecast:row['Reason']=reason;continue
                    report=research.get('passing_count_reports',{}).get(field,{'passed':False})
                    row.update(evaluated_row(row,forecast,report,now))
                    continue
                if interception:
                    forecast,reason=interception_estimate(next(iter(ids)),context['season'],int(schedule['week']),team,opponent,idx)
                    if not forecast:row['Reason']=reason;continue
                    p=forecast['probability'] if row['Selection']=='Over' else 1-forecast['probability']
                    breakeven=100/(odds+100) if odds>0 else abs(odds)/(abs(odds)+100)
                    row.pop('Projection (yards)',None)
                    row.update({'Model':'NFL interceptions frequency/rate v1 — experimental','Projection (count)':round(forecast['expected'],2),'Expected opportunities':round(forecast['attempts'],2),'Opportunity type':'Passing attempts','Estimated win %':round(100*p,1),'Break-even %':round(100*breakeven,1),'Model edge (pp)':round(100*(p-breakeven),1),'Prior games with interception %':round(100*forecast['frequency'],1),'Validation games':interception_report['games'],'Validation Brier':interception_report['brier'],'Baseline Brier':interception_report['baseline_brier']})
                    if not interception_report['passed']:row['Reason']='Interception probability model has not beaten both prior-game frequency and 50/50 baselines in 2025 development; research estimate only.';continue
                    if p-breakeven<.05:row['Reason']='Estimated edge below five percentage points.';continue
                    row['Decision']='Watch — experimental'
                    row['Reason']=f"{forecast['games']} prior starter games; interception-game frequency {100*forecast['frequency']:.0f}%; passing attempts, QB interception rate and opponent interception rate included. Average interceptions is not probability of an interception."
                    continue
                if market['key'] in ('player_pass_yds','player_pass_attempts'):
                    counts={}
                    for _,(label,field) in PASSING_MARKETS.items():
                        count,missing=cached_passing(next(iter(ids)),context['season'],int(schedule['week']),team,opponent,field)
                        if count:
                            counts[label]={'Forecast':round(count['expected'],2),'Expected attempts':round(count['attempts'],2),'Conversion rate %':round(100*count['rate'],2),'Range low':count['low'],'Range high':count['high'],'Recommendation gate passed':research.get('passing_count_reports',{}).get(field,{}).get('passed',False)}
                    if counts:
                        row['Passing conversion breakdown']=counts
                        row['Supporting completions forecast']=counts.get('Passing completions',{}).get('Forecast')
                        row['Supporting passing TD forecast']=counts.get('Passing touchdowns',{}).get('Forecast')
                model = research['models'][market['key']]
                projected = projection(feature,model['blend'],model['defense_weight'])
                if research.get('experiment'):
                    from nfl_workload_lab import live_opportunity_projection
                    sample={'player_id':next(iter(ids)),'season':context['season'],'week':int(schedule['week']),
                            'team':team,'opponent_team':opponent,'position':feature['position'],
                            MARKETS[market['key']][1]:0,MARKETS[market['key']][2]:0}
                    try:
                        if model.get('receiver_role'):
                            from receiver_role import role_inputs,predict
                            role_sample=role_inputs(sample,market['key'],idx,research['receiver_role_snaps'])
                            if not role_sample:raise ValueError('Participation inputs unavailable')
                            projected,volume,team_attempts,catch=predict(role_sample,model['role_parameters'],model['chain_parameters'],market['key'])
                            row['Expected team passing attempts']=round(team_attempts,2)
                            row['Catch probability %']=round(100*catch,1)
                            row['Recent snap share %']=round(100*role_sample['recent_snap'],1) if role_sample['recent_snap'] is not None else None
                            row['Usual snap share %']=round(100*role_sample['usual_snap'],1) if role_sample['usual_snap'] is not None else None
                            row['Snap effect weight']=model['role_parameters'][0]
                            row['Snap coverage']='Available' if role_sample['snap_covered'] else 'Unavailable — neutral effect'
                            row['Route coverage']='Unavailable; snap share is not route participation'
                        elif model.get('reception_chain'):
                            from reception_chain import chain_inputs,predict,VERSION
                            chain_sample=chain_inputs(sample,idx)
                            if not chain_sample:raise ValueError('Missing chain inputs')
                            projected,volume,team_attempts,catch=predict(chain_sample,model['chain_parameters'])
                            row['Expected team passing attempts']=round(team_attempts,2)
                            row['Catch probability %']=round(100*catch,1)
                        elif model.get('boosted'):
                            from boosted_yardage import live_boost
                            projected,volume=live_boost(sample,market['key'],idx,model,research['boosted_snaps'])
                        else:projected,volume=live_opportunity_projection(sample,market['key'],idx,model['parameters'])
                    except ValueError:
                        row['Reason']='Experimental opportunity inputs unavailable.';continue
                    feature=dict(feature,volume_forecast=volume)
                    row['Model']='NFL count workload v1 / 2024 fit / 2025 development' if market['key'] in COUNT_MARKETS else 'NFL opportunity experiment v2 / 2024 fit / 2025 development'
                    if model.get('boosted'):
                        row['Model']='NFL boosted opportunities v1 / 2023-24 fit / late-2024 calibration'
                        row['Boosted tree weight %']=100*model['opportunity_fit']['weight']
                    if model.get('receiver_role'):
                        from receiver_role import VERSION
                        row['Model']=VERSION
                    if model.get('reception_chain'):
                        from reception_chain import VERSION
                        row['Model']=VERSION
                    if research.get('chronological_calibration'):row['Model']='NFL chronological calibration v1 / early-2024 fit / late-2024 calibration'
                    row['Probability adjustment strength']=model.get('probability_strength',.8)
                    row['Opportunity type']={'player_pass_yds':'Passing attempts','player_rush_yds':'Carries','player_reception_yds':'Targets','player_receptions':'Targets','player_pass_attempts':'Passing attempts','player_rush_attempts':'Carries'}[market['key']]
                    row['Workload method']=model['parameters'][0]
                    row['Efficiency method']=model['parameters'][1]
                    row['Opportunity forecast blend %']=100*model['parameters'][2]
                if market['key'] in ('player_pass_yds','player_pass_attempts'):
                    from game_script import workload_risk
                    risk=workload_risk(next(iter(ids)),context['season'],int(schedule['week']),team,line if market['key']=='player_pass_attempts' else None,idx,research['schedule'])
                    if risk:
                        row['Historical high-volume attempts (80th percentile)']=risk['Historical high-volume attempts (80th percentile)']
                        row['Game-script stress scenarios']=str(risk['Scenarios'])
                        row['Game-script risk']='Passing volume can rise when trailing; historical outcome scenarios are context only, not scenario probabilities.'
                        row['Prior attempts above quoted line %']=risk['Prior attempts above quoted line %']
                from contextual_forecasts import nfl_availability, nfl_situation
                before_context=projected
                availability=nfl_availability(row['Player'],row['Category'],team,team_name,context['season'],int(schedule['week']),research['players'],rosters.get(team_name,[]),injuries)
                situation=nfl_situation(team,opponent,context['date'],research['schedule'],research['teams'])
                situation_factor=1.
                scenario_factor=1.
                if situation:
                    scenario_factor=situation['rushing_factor'] if market['key'] in ('player_rush_yds','player_rush_attempts') else situation['passing_factor']
                    row['Situation forecast']=situation
                row['Situation adjustment %']=0.
                row['NFL context scenario']={'Projected stat':projected*availability['workload_factor']*availability['efficiency_factor']*scenario_factor,'Expected opportunities':feature['volume_forecast']*availability['workload_factor']*scenario_factor,'Availability workload factor':availability['workload_factor'],'Availability efficiency factor':availability['efficiency_factor'],'Situation factor':scenario_factor,'Status':'Unvalidated scenario only; not applied to base forecast or probability','Reason':availability['reason']}
                row['Injury adjustment %']=0.
                row['Injury adjustment reason']='Fresh availability checked. Numerical absence effects remain a separate unvalidated scenario.'
                row['Unadjusted projection']=before_context
                row['Context validation status']='Base forecast matches the historically tested pipeline; extra absence/score-state multipliers remain separate research scenarios'
                row['Model']+=' / context-audit-v2'
                from online_learning import adjust_forecast, adjust_probability
                base_p = over_probability(projected,line,model['residuals'],model.get('probability_strength',.8))
                if row['Selection'] == 'Under':base_p = 1-base_p
                row['Base estimated win %'] = 100*base_p
                row['Base model'] = row['Model']
                projected, learned_volume = adjust_forecast(row, projected, feature['volume_forecast'], now)
                feature = dict(feature, volume_forecast=learned_volume)
                residuals=model['residuals']
                lower=projected+residuals[int(.1*(len(residuals)-1))]*error_scale(projected)
                upper=projected+residuals[math.ceil(.9*(len(residuals)-1))]*error_scale(projected)
                row['Historical error range low']=round(max(0,lower),1)
                row['Historical error range high']=round(max(0,upper),1)
                p = over_probability(projected,line,model['residuals'],model.get('probability_strength',.8))
                if row['Selection'] == 'Under':p = 1-p
                if row.get('Candidate projection') is not None:
                    candidate_p=over_probability(row['Candidate projection'],line,model['residuals'],model.get('probability_strength',.8))
                    row['Candidate input win %']=100*(1-candidate_p if row['Selection']=='Under' else candidate_p)
                online_p=adjust_probability(row,p,now)
                p=online_p
                row['Raw estimated win %']=100*p
                row['Feedback status']=row.get('Online learning status','Collecting prospective per-game evidence')
                break_even = 100/(odds+100) if odds>0 else abs(odds)/(abs(odds)+100)
                row['Validation details']={'passed':bool(model.get('forecast_passed')),'calibration_examples':len(model.get('residuals',[])),'test_count':model.get('test_count'),'scope':'Existing chronological NFL model baseline test; calibration examples and later test cases are separate'}
                row.update({'Projection (yards)':round(projected,1),'Expected opportunities':round(feature['volume_forecast'],2),'Estimated win %':round(p*100,1),'Break-even %':round(break_even*100,1),'Model edge (pp)':round((p-break_even)*100,1)})
                if market['key'] in COUNT_MARKETS:
                    row['Projection (count)']=row.pop('Projection (yards)')
                    row['Forecast units']=row['Category']
                if market['key'] in ('player_receptions','player_reception_yds'):
                    target=target_forecast(next(iter(ids)),context['season'],int(schedule['week']),team,opponent,idx)
                    if target:
                        row['Target breakdown']=target
                        row['Player targets forecast']=round(target['targets'],2)
                        row['Target share forecast %']=round(100*target['target_share'],2)
                        row['Supporting team attempts']=round(target['team_attempts'],2)
                        row['Supporting catch probability %']=round(100*target['catch_rate'],2)
                        row['Supporting receptions forecast']=round(target['receptions'],2)
                        row['Supporting receiving yards forecast']=round(target['receiving_yards'],2) if target['receiving_yards'] is not None else None
                if 'receiver_role_snaps' in research and market['key'] in ('player_receptions','player_reception_yds'):
                    from receiver_role import role_inputs
                    context_role=role_inputs(sample,market['key'],idx,research['receiver_role_snaps'])
                    if context_role:
                        row['Recent snap share %']=round(100*context_role['recent_snap'],1) if context_role['recent_snap'] is not None else None
                        row['Usual snap share %']=round(100*context_role['usual_snap'],1) if context_role['usual_snap'] is not None else None
                        row['Recent target share %']=round(100*context_role['chain']['recent_share'],1)
                        row['Usual target share %']=round(100*context_role['chain']['share'],1)
                        row['Snap coverage']='Available' if context_role['snap_covered'] else 'Unavailable — neutral effect'
                        row['Snap effect weight']=model['role_parameters'][0] if model.get('receiver_role') else 0
                        row['Route coverage']='Unavailable; snap share is not route participation'
                if not model['forecast_passed']:
                    row['Reason'] = 'Forecast did not beat the recent-average baseline on the 2025 test.';continue
                if p-break_even < .05:
                    row['Reason'] = 'Estimated edge below five percentage points.';continue
                row['Decision'] = 'Watch — experimental'
                row['Reason'] = f"{feature['games']} recent games; expected {feature['volume_forecast']:.1f} opportunities; opponent historical {row['Category'].lower()} allowed: {feature['ratio']*100:.0f}% of league average (context, not a standalone direction signal). Availability: {status}. Additional absence and score-state effects are separate research scenarios, not automatic forecast boosts. Confirm lineup/weather."
    for row in rows:
        meta=evidence_inputs.get((row['Player'],row['Category']))
        if meta:
            from nfl_forecast_evidence import attach as attach_nfl_evidence
            attach_nfl_evidence(row,meta['history'],research,context['season'],int(schedule['week']),meta['team'],meta['opponent'],meta['team_name'],meta['team_id'],meta['athlete_id'],injuries,now,context['date'])
        if row.get('Estimated win %')is not None:
            from pick_learning import adjust_row
            p=adjust_row(row,float(row['Estimated win %'])/100,now,sport='NFL')
            row['Probability calibration status']=row['Feedback status']
            price=float(row['Odds']);be=100/(price+100)if price>0 else abs(price)/(abs(price)+100)
            row['Estimated win %']=round(100*p,1);row['Model edge (pp)']=round(100*(p-be),1)
            if row.get('Online learning status'):row['Feedback status']=row['Online learning status']+'; '+row['Probability calibration status']
            edge_reason='Estimated edge below five percentage points.'
            if row['Decision']!='Pass'and p-be<.05:row['Decision']='Pass';row['Reason']=edge_reason
            elif row['Decision']=='Pass'and edge_reason in row.get('Reason','')and p-be>=.05:
                row['Decision']='Watch — experimental';row['Reason']=row['Reason'].replace(edge_reason,'Validated calibration meets the five-percentage-point edge threshold.')
        if row.get('New teammates — role uncertainty'):
            row['Reason']+=' New teammates with limited team history: '+row['New teammates — role uncertainty']+'. Target/carry redistribution is not quantified; previous shares may change.'
        if row.get('Snap coverage'):
            row['Reason']+=f" Expected targets {row.get('Expected opportunities')}; snap coverage {row['Snap coverage']}; selected snap effect weight {row['Snap effect weight']}. Routes unavailable."
        row['Evidence explanation']=evidence_explanation(row)
    if any(m.get('key')in ('player_anytime_td','totals')for b in event.get('bookmakers',[])for m in b.get('markets',[])):
        from nfl_scoring_models import reviews as scoring_reviews
        rows.extend(scoring_reviews(event,scoreboard,research,injuries,rosters,now))
    return sorted(rows,key=lambda r:(r['Decision']=='Pass',-(r['Model edge (pp)'] or -999)))

def evidence_explanation(row):
    reason=row.get('Reason','')
    projected=num(row.get('Projection (count)'))
    if projected is None:projected=num(row.get('Projection (yards)'))
    if projected is None:
        return 'Not evaluated: '+reason+' This does not predict an Over or Under.'
    probability=num(row.get('Estimated win %'));breakeven=num(row.get('Break-even %'))
    text=f"Forecast: {projected:g} {row.get('Category','').lower()}. Compared quote: {row.get('Selection')} {row.get('Line')} at {row.get('Odds')} ({row.get('Sportsbook')}). "
    if row.get('Last-season games') is not None:text+=f"Last-season history: {row['Last-season games']} games; current-season appearances: {row['Current-season appearances']}; current-season weight: {row['Current-season weight %']:.1f}%. {row.get('Role uncertainty','')} "
    if row.get('Roster/history status'):text+=f"Current roster team: {row['Current roster team']}; current-team games: {row['Current-team games']}; {row['Roster/history status']}. "
    from saved_pick_explanation import from_row
    explained=from_row({k:v for k,v in row.items() if k!='Evidence explanation'})
    if row.get('Conversion rate %') is not None or row.get('Target breakdown'):
        text+=explained['calculation']+' '+explained['uncertainty']+' '
    volume=num(row.get('Expected opportunities'))
    if volume is not None:text+=f"Expected workload: {volume:g} {row.get('Opportunity type','opportunities').lower()}. "
    if probability is not None and breakeven is not None:
        text+=f"Estimated win chance {probability:.1f}% versus {breakeven:.1f}% needed to break even; estimated gap {probability-breakeven:.1f} percentage points. "
        if reason.startswith('Estimated edge below five percentage points.'):
            text+='Pass because the gap is below the required 5 points; a forecast below or above the line alone is insufficient. '
    if row.get('Snap coverage'):text+=f"Snap coverage: {row['Snap coverage']}; recent share {row.get('Recent snap share %')}%, usual share {row.get('Usual snap share %')}%, selected effect weight {row.get('Snap effect weight')}. Routes run are unavailable. "
    if row.get('Expected team passing attempts') is not None:text+=f"Team passing forecast: {row['Expected team passing attempts']} attempts; player catch probability: {row['Catch probability %']}%. "
    if row.get('Game-script risk'):text+=row['Game-script risk']+' Historical high-volume workload: '+str(row['Historical high-volume attempts (80th percentile)'])+' attempts. '
    if row.get('Feedback status'):text+=row['Feedback status']+'. '
    text+='Experimental estimates, not independently verified confidence or profitability. '
    if row.get('Model','').startswith('NFL boosted'):text+='Snap participation and role trends inform expected opportunities. '
    text+='Extra absence and predicted-margin effects remain separate unvalidated scenarios; they do not boost the tested base forecast. Depth listings do not confirm game-day starters, and snap share is not routes run.'
    return text

def estimated_risk(probability):
    p=num(probability)
    if p is None:return 'Not estimated'
    if p>=70:return 'Lower estimated loss risk — unverified'
    if p>=60:return 'Moderate estimated loss risk — unverified'
    if p>=50:return 'Elevated estimated loss risk — unverified'
    return 'High estimated loss risk — unverified'


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
            for field in ('Selection','Line','Sportsbook','Odds','Estimated win %','Break-even %','Model edge (pp)'):
                row['Evaluated quote — '+field]=row.get(field)
            row['Evaluation status']='Evaluated — price edge insufficient' if row.get('Reason')=='Estimated edge below five percentage points.' else 'No qualifying pick — see reason'
            if candidates:row['Reason']='Qualifying Over and Under quotes conflict or no supported direction exists. No single paper pick.'
            row.update({'Paper pick':'PASS — no pick','Selection':'—','Line':'—','Sportsbook':'—','Odds':'—','Estimated win %':None,'Break-even %':None,'Model edge (pp)':None})
        # A central forecast lean is context, never an instruction to bet.
        passed=row['Decision']=='Pass'
        line=num(row.get('Evaluated quote — Line') if passed else row.get('Line'))
        projected=num(row.get('Projection (count)'))
        if projected is None:projected=num(row.get('Projection (yards)'))
        probability=num(row.get('Evaluated quote — Estimated win %') if passed else row.get('Estimated win %'))
        selection=row.get('Evaluated quote — Selection') if passed else row.get('Selection')
        evaluated=projected is not None and line is not None and probability is not None and selection in ('Over','Under')
        conflict='conflict' in row.get('Reason','').lower()
        lean=('Over' if projected>line else 'Under' if projected<line else 'At line') if evaluated and not conflict else 'No reliable lean shown'
        row['Forecast lean']=lean
        row['Forecast projection']=projected
        row['Compared line']=line
        row['Compared sportsbook']=row.get('Evaluated quote — Sportsbook') if passed else row.get('Sportsbook')
        row['Compared odds']=row.get('Evaluated quote — Odds') if passed else row.get('Odds')
        row['Compared direction']=selection if evaluated else None
        row['Compared direction win %']=probability if evaluated else None
        row['Compared break-even %']=row.get('Evaluated quote — Break-even %') if passed else row.get('Break-even %')
        row['Compared edge (pp)']=row.get('Evaluated quote — Model edge (pp)') if passed else row.get('Model edge (pp)')
        if passed:
            row['Research summary']=f'Forecast leans {lean} — PASS; see reason' if lean in ('Over','Under') else 'PASS — no reliable direction; see reason'
        else:row['Research summary']='Qualifying experimental paper pick'
        # Put the explicit direction first in the displayed/exported table.
        result.append({'Paper pick':row.pop('Paper pick'),**row})
    return sorted(result,key=lambda r:(r['Decision']=='Pass',-(num(r.get('Model edge (pp)')) or -999)))

def cushion_sources(rows):
    eligible=[r for r in rows if r.get('Category') in ('Passing yards','Receiving yards')]
    selected={(r['Game'],name_key(r['Player']),r['Category']):r for r in clear_prop_shortlist(eligible)}
    grouped={}
    for original in eligible:
        key=(original['Game'],name_key(original['Player']),original['Category'])
        chosen=selected[key]
        # A selected direction owns its cushion; never replace it with the rejected opposite side.
        if chosen['Decision']!='Pass':
            grouped[key+('selected',)]=dict(chosen)
            continue
        if chosen.get('Reason','').startswith('Qualifying Over and Under quotes conflict'):continue
        if original.get('Selection') not in ('Over','Under'):continue
        if original.get('Decision')=='Pass' and original.get('Reason')!='Estimated edge below five percentage points.':continue
        if num(original.get('Projection (yards)')) is None or num(original.get('Line')) is None:continue
        row=dict(original)
        row['Paper pick']=f"PASS — evaluated quote: {row['Player']} {row['Selection']} {row['Line']} {row['Category']}"
        direction_key=key+(row['Selection'],)
        score=num(row.get('Model edge (pp)'))
        prior=num(grouped.get(direction_key,{}).get('Model edge (pp)'))
        if direction_key not in grouped or (score if score is not None else -999)>(prior if prior is not None else -999):grouped[direction_key]=row
    return list(grouped.values())

def analyzed_cushions(watch, events, books, models, now=None, season_priors=None):
    now=now or datetime.now(timezone.utc)
    results=[]
    for original in watch:
        receiving=original.get('Category')=='Receiving yards'
        model=models.get('player_reception_yds' if receiving else 'player_pass_yds',{})
        prior_model=(season_priors or {}).get(('player_reception_yds' if receiving else 'player_pass_yds',original.get('Season stage')), {}) if original.get('Model','').startswith('NFL season-prior workload') else {}
        if original.get('Opportunity model applied')and prior_model.get('opportunity_report',{}).get('passed'):
            prior_model=prior_model['opportunity_report']
        if original.get('Model','').startswith('NFL season-prior workload'):model=dict(prior_model,forecast_passed=prior_model.get('passed',False))
        desired=25 if receiving else 30
        minimum,maximum=(20,25) if receiving else (25,40)
        target=cushion_target(original)
        if target is None:continue
        row={'Player':original['Player'],'Game':original['Game'],'Original pick':original['Paper pick'],
             'Original decision':original['Decision'],'Original reason':original.get('Reason'),'Original explanation':original.get('Evidence explanation',''),'Direction':original['Selection'],'Category':original['Category'],'Cushion target':target,'Target cushion yards':desired,'Cushion decision':'Pass','Selection status':'Not recommended — Pass','Available selection':'—','Actual cushion yards':None,
             'Sportsbook':'—','Actual odds':None,'Recalculated win %':None,'Break-even %':None,
             'Model edge (pp)':None,'Reason':f'No fresh alternate quote with a {minimum}–{maximum}-yard cushion. Load the matching original and alternate yardage categories.'}
        candidates=[]
        for event in events:
            if event.get('away_team','')+' at '+event.get('home_team','')!=original['Game']:continue
            try:
                if datetime.fromisoformat(event['commence_time'].replace('Z','+00:00'))<=now:continue
            except (KeyError,ValueError,TypeError):continue
            for book in event.get('bookmakers',[]):
                if book.get('title') not in books:continue
                for market in book.get('markets',[]):
                    if market.get('key')!=('player_reception_yds_alternate' if receiving else 'player_pass_yds_alternate'):continue
                    try:
                        age=(now-datetime.fromisoformat((market.get('last_update') or book.get('last_update')).replace('Z','+00:00'))).total_seconds()
                        if not 0<=age<=900:continue
                    except (ValueError,TypeError,AttributeError):continue
                    for outcome in market.get('outcomes',[]):
                        if name_key(outcome.get('description',''))!=name_key(original['Player']) or outcome.get('name')!=original['Selection']:continue
                        line=num(outcome.get('point'));odds=num(outcome.get('price'))
                        if line is None or odds is None or abs(odds)<100 or line<0 or line%1!=.5:continue
                        if receiving and line<15:continue
                        cushion=line-float(original['Line']) if original['Selection']=='Under' else float(original['Line'])-line
                        if not minimum<=cushion<=maximum:continue
                        candidates.append((abs(cushion-desired),book['title'],line,odds,cushion,market.get('last_update') or book.get('last_update')))
        if candidates and model.get('residuals') and num(original.get('Projection (yards)')) is not None:
            evaluated=[]
            for distance,book,line,odds,cushion,updated in candidates:
                if prior_model:
                    from nfl_season_prior import over_probability as prior_probability
                    p=prior_probability(float(original['Projection (yards)']),line,prior_model,float(original.get('Uncertainty multiplier',1)))
                else:
                    p=over_probability(float(original['Projection (yards)']),line,model['residuals'],model.get('probability_strength',.8))
                if original['Selection']=='Under':p=1-p
                breakeven=100/(odds+100) if odds>0 else abs(odds)/(abs(odds)+100)
                ev=p*(odds/100 if odds>0 else 100/abs(odds))-(1-p)
                evaluated.append((distance,-ev,book,line,odds,cushion,p,breakeven,ev,updated))
            _,_,book,line,odds,cushion,p,breakeven,ev,updated=min(evaluated)
            qualifies=p-breakeven>=.05 and ev>0 and model.get('forecast_passed',False)
            row.update({'Cushion decision':'Watch — experimental' if qualifies else 'Pass','Selection status':'Qualifying paper candidate' if qualifies else 'Not recommended — Pass',
                'Available selection':f"{original['Selection']} {line:g} {original['Category'].lower()}",'Actual cushion yards':cushion,
                'Sportsbook':book,'Actual odds':odds,'Recalculated win %':round(p*100,1),
                'Available line':line,'Quote updated UTC':updated,
                'Break-even %':round(breakeven*100,1),'Model edge (pp)':round((p-breakeven)*100,1),
                'Reason':f"At {line:g}, the {original['Selection']} has estimated win chance {p*100:.1f}% versus {breakeven*100:.1f}% needed at odds {odds:+g}. It meets the 5-point edge requirement. Original decision: {original['Decision']}. Experimental, not verified profitability." if qualifies else f"At {line:g}, estimated win chance is {p*100:.1f}% versus {breakeven*100:.1f}% needed at odds {odds:+g}. The cushion fails the model baseline or 5-point price-edge requirement. More cushion does not necessarily mean better value."})
        elif candidates:
            row['Reason']='Reanalyze to load the probability model for this comparison.'
        results.append(row)
    return results


def cushion_target(row):
    if row.get('Category') not in ('Passing yards','Receiving yards'):return None
    if row.get('Decision')=='Pass' and row.get('Reason')!='Estimated edge below five percentage points.':return None
    line=num(row.get('Line'))
    if line is None:return None
    receiving=row['Category']=='Receiving yards'
    if receiving and line<15:return None
    amount=25 if receiving else 30
    target=line+amount if row.get('Selection')=='Under' else line-amount
    return target if target>=(15 if receiving else 0) else None


def cushion_result(direction,line,actual):
    if actual == line:return 'Push'
    return 'Win' if (actual < line if direction=='Under' else actual > line) else 'Loss'


def render_cushion_tracker(watch,starts):
    with st.expander('30-yard passing cushion experiment and results'):
        st.caption('Target only: Under adds 30 yards; Over subtracts 30. This is not a verified alternate quote or recommendation. Original probability and odds do not apply to the new line. Enter the actual available threshold and American-equivalent odds. For No to 300+, enter Under 299.5; Yes to 275+ means Over 274.5. Confirm the platform settlement rules.')
        records=st.session_state.setdefault('passing_cushion_records',[])
        uploaded=st.file_uploader('Restore cushion tracking CSV',type=['csv'],key='cushion_restore_file')
        if uploaded is not None and st.button('Restore cushion records',key='cushion_restore'):
            try:
                loaded=list(csv.DictReader(io.StringIO(uploaded.getvalue().decode('utf-8-sig'))))
                if len(loaded)>500:raise ValueError()
                clean=[]
                for r in loaded:
                    if r['Direction'] not in ('Under','Over'):raise ValueError()
                    for key in ('Original line','Actual cushion line','Original odds','Actual cushion odds'):
                        value=num(r[key])
                        if value is None or (key.endswith('odds') and abs(value)<100) or (key.endswith('line') and value<0):raise ValueError()
                        r[key]=value
                    if datetime.fromisoformat(r['Recorded UTC'])>=datetime.fromisoformat(r['Game starts UTC'].replace('Z','+00:00')):raise ValueError()
                    if r.get('Final yards','')!='':
                        r['Final yards']=num(r['Final yards'])
                        if r['Final yards'] is None or r['Final yards']<0:raise ValueError()
                    clean.append(r)
                records[:]=clean
                st.success('Tracking records restored. Imported records are user-editable evidence.')
            except (ValueError,KeyError,TypeError,UnicodeError):st.warning('Could not restore this tracking CSV.')
        picks=[r for r in watch if r['Category']=='Passing yards' and cushion_target(r) is not None]
        if picks:
            index=st.selectbox('Original pick to track',range(len(picks)),format_func=lambda i:picks[i]['Paper pick'],key='cushion_pick')
            row=picks[index];target=cushion_target(row)
            st.write(f"30-yard target: **{row['Selection']} {target:g} passing yards**")
            actual=st.number_input('Actual available alternate line',min_value=0.0,value=float(target),step=.5,key='cushion_actual_line_'+str(index))
            price=st.number_input('Actual alternate American odds',value=-110.0,step=1.0,key='cushion_actual_price_'+str(index))
            if st.button('Record original and actual cushion selection',key='cushion_record'):
                now=datetime.now(timezone.utc)
                if now>=datetime.fromisoformat(starts[row['Game']].replace('Z','+00:00')):st.warning('Record selections before kickoff.')
                elif abs(price)<100:st.warning('Enter valid American odds.')
                elif (row['Selection']=='Under' and actual<=row['Line']) or (row['Selection']=='Over' and actual>=row['Line']):st.warning('The alternate line must give the original direction more room.')
                elif any(r['Game']==row['Game'] and r['Player']==row['Player'] for r in records):st.info('This player/game is already recorded.')
                else:
                    records.append({'Recorded UTC':now.isoformat(),'Game starts UTC':starts[row['Game']],'Game':row['Game'],'Player':row['Player'],'Direction':row['Selection'],'Original line':row['Line'],'Original odds':row['Odds'],'30-yard target':target,'Actual cushion line':actual,'Actual cushion odds':price,'Final yards':''})
                    st.success('Both selections recorded. Download the CSV to keep it after this session.')
        if records:
            index=st.selectbox('Record to grade',range(len(records)),format_func=lambda i:records[i]['Player']+' — '+records[i]['Game'],key='cushion_grade_pick')
            final=st.number_input('Final passing yards from completed game',min_value=0,step=1,key='cushion_final_yards')
            if st.button('Save final yards and compare',key='cushion_grade'):
                records[index]['Final yards']=final
            results=[]
            for r in records:
                item=dict(r)
                for label,linekey,pricekey in [('Original','Original line','Original odds'),('Cushioned','Actual cushion line','Actual cushion odds')]:
                    result=cushion_result(r['Direction'],float(r[linekey]),float(r['Final yards'])) if r['Final yards']!='' else 'Pending'
                    item[label+' result']=result
                    odds=float(r[pricekey]);item[label+' return per $1']=round((odds/100 if odds>0 else 100/abs(odds)) if result=='Win' else -1 if result=='Loss' else 0,3) if result!='Pending' else None
                results.append(item)
            render_team_table(results,hide_index=True,use_container_width=True, sport='NFL')
            buffer=io.StringIO();writer=csv.DictWriter(buffer,fieldnames=list(records[0]));writer.writeheader();writer.writerows(records)
            autosave_report('Download cushion tracking CSV',buffer.getvalue(),file_name='kamikaze_picks_passing_cushion.csv',mime='text/csv',key='cushion_download')
            st.caption('Results are manually entered. Returns compare $1 straight selections, excluding fees; combo/parlay payouts are not inferred. Report snapshots save automatically when permanent storage is configured. Check any save warnings.')


def render_prop_research(event, scoreboard, books, quote_retrieved, auto_analyze=False):
    events = event if isinstance(event,list) else [event]
    starts = {e['away_team']+' at '+e['home_team']:e['commence_time'] for e in events}
    st.subheader('NFL prop shortlist — one direction or Pass')
    st.caption('Models: passing/rushing/receiving yards, receptions, passing attempts, completions, passing touchdowns and RB rushing attempts. Completions and passing touchdowns use attempts × conversion distributions; picks require stat and probability benchmark passes. Interceptions at 0.5 remain gated separately. New count markets remain experimental and must beat their baseline. Anytime offensive touchdowns and NFL game totals use separate chronological scoring models. Specific rushing/receiving TD counts, QB rushing yards and defensive props are not modeled. Probabilities and sportsbook returns are unverified.')
    mode=st.selectbox('Forecast model',['Original model','Experimental opportunity model — paper testing','Chronological calibration model — paper testing','Boosted opportunity model — paper testing','Team targets and receptions — paper testing','Receiving participation — paper testing'],index=1,key='nfl_workload_forecast_mode')
    experimental=mode!='Original model'
    chronological=mode.startswith('Chronological')
    boosted=mode.startswith('Boosted')
    chain=mode.startswith('Team targets')
    participation=mode.startswith('Receiving participation')
    with st.expander('Forecast coverage, model details and limitations'):
        if participation:st.info('Participation paper candidate: target share and snap-share changes feed receiving yards and receptions. Uses a candidate only when it beats the incumbent and baseline in development. Missing snaps have a neutral effect; routes, injury effects and weather are not quantified.')
        if chain:st.info('Linked receptions candidate: team passing attempts → player target share → catch probability. Uses the candidate only after beating the current receptions model and recent-average baseline; otherwise retains the current model. Historical comparisons are not verified profitability.')
        if experimental:st.info('Paper experiment: improved workload and stabilized efficiency. The 2025 comparison informed development; it is not independent validation. Probabilities and profitability are unverified. Save this model’s picks separately before kickoff.')
        if chronological:st.info('Separate-calibration experiment: parameters use 2024 weeks 1–12; uncertainty and probability adjustment use weeks 13 onward. Later-year results remain development evidence. This is a separate model, not a proven accuracy upgrade.')
        if boosted:st.info('Boosted paper candidate: passing attempts and receiving targets use team/opponent workload, player share, snap participation and role trends. Passing/receiving yardage and passing-attempt props use a candidate only when it beats the baseline and current v2 on comparable historical games; other cases retain the existing opportunity model. Historical gaps may use three consecutive recent games when supported. Current roster, injury, quote and schedule checks remain required.')
        if experimental and not boosted:st.caption('Workload connected: expected passing attempts, carries or targets feed the yardage forecast, using the historical model selected for that category. Expected opportunities and the workload/efficiency methods appear in analyzed results. Snap counts, teammate absences and weather are not numerical forecast inputs yet. SportsDataIO trial data is excluded.')
    cache_key = (tuple(e['id'] for e in events), quote_retrieved, tuple(sorted(books)),mode)
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
                if experimental:
                    from nfl_workload_lab import load_experimental_research
                    if participation:
                        from receiver_role import load_role_research
                        research=load_role_research(usable[0]['season'])
                        render_team_table(research['role_reports'],hide_index=True,use_container_width=True, sport='NFL')
                        for issue in research['role_feed_issues']:st.warning(issue)
                    elif chain:
                        from reception_chain import load_chain_research
                        research=load_chain_research(usable[0]['season'])
                        render_team_table(research['chain_reports'],hide_index=True,use_container_width=True, sport='NFL')
                    elif boosted:
                        from boosted_yardage import load_boosted_pick_research
                        research=load_boosted_pick_research(usable[0]['season'])
                    else:research=load_experimental_research(usable[0]['season'],chronological)
                injury_context.clear()
                injuries = injury_context()
                team_ids = {c[side]['displayName']:c[side]['id'] for c in usable for side in ('home','away')}
                research=dict(research)
                from nfl_forecast_evidence import load_depths
                research['parity_depths']=load_depths(team_ids.values())
                from player_usage import load_snap_usage
                from role_forecast_lab import snap_lookup
                snap_rows=[];snap_issues=[]
                for year in (usable[0]['season']-1,usable[0]['season']):
                    try:snap_rows.extend(load_snap_usage(year))
                    except Exception:snap_issues.append(str(year)+' NFL snap feed unavailable; missing participation stays unknown.')
                research['parity_snaps']=snap_lookup(snap_rows)
                rosters = {}
                issues = list(research['parity_depths']['issues'])+snap_issues
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
                from game_day_diagnostics import apply as apply_game_day_diagnostic
                rows=apply_game_day_diagnostic(rows,'NFL')
                rows.sort(key=lambda r:(r['Decision']=='Pass',-(r['Model edge (pp)'] or -999)))
                st.session_state['nfl_prop_analysis'] = {'key':cache_key,'rows':rows,'models':research['models'],'season_prior_reports':research.get('season_prior_reports',{}),'reports':research['reports'],'retrieved':research['retrieved'],'analyzed':datetime.now(timezone.utc).isoformat(),'issues':issues,'injury_retrieved':injuries.get('retrieved'),'injury_source_updated':injuries.get('source_updated'),'roster_checked':datetime.now(timezone.utc).isoformat()}
        except (requests.exceptions.RequestException, ValueError, KeyError, TypeError, AttributeError, OSError, ImportError):
            st.warning('Pass: player history, roster, schedule or injury data could not be verified. Try again later.');return
    saved = st.session_state.get('nfl_prop_analysis')
    if not saved or saved['key'] != cache_key:
        st.info('Click Analyze loaded player props. Analysis uses free statistics and does not request more sportsbook credits.');return
    render_source_status(saved)
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
    from forecast_tracking import archive as archive_forecasts
    archive_forecasts(saved['rows'], events, scoreboard, 'NFL')
    cushion_inputs=cushion_sources(display)
    display=clear_prop_shortlist(display)
    for row in display:
        row['30-yard cushion target'] = cushion_target(row) if row['Category']=='Passing yards' else None
        row['25-yard receiving cushion target'] = cushion_target(row) if row['Category']=='Receiving yards' else None
        probability=num(row.get('Estimated win %'))
        row['Risk label']=estimated_risk(probability) if row['Decision']!='Pass' else 'Pass — no selection'
        row['Estimated loss %']=round(100-probability,1) if probability is not None else None
        row['Selection type']='Value selection — less likely to win than lose' if row['Decision']!='Pass' and probability is not None and probability<50 else 'Higher-probability experimental selection' if row['Decision']!='Pass' and probability is not None and probability>=60 else 'Experimental value selection' if row['Decision']!='Pass' else 'No selection'
    display=[dict([('Paper pick', row['Paper pick']), ('Decision', row['Decision']),
                   ('Risk label',row['Risk label']),('Selection type',row['Selection type']),
                   ('Estimated win %',row.get('Estimated win %')),('Estimated loss %',row['Estimated loss %']),
                   ('Reason', row['Reason'])] + [(key,value) for key,value in row.items()
                   if key not in ('Paper pick','Decision','Reason','Risk label','Selection type','Estimated win %','Estimated loss %')]) for row in display]
    for issue in saved.get('issues',[]):st.warning(issue)
    st.caption(f'Combined results for {len(events)} loaded NFL game(s).')
    present={r.get('Category') for r in saved['rows']}
    missing=[label for label,*_ in MARKETS.values() if label not in present]
    if missing:st.info('No analyzed quotes for: '+', '.join(missing)+'. Select these in the prop REQUEST categories and load again if offered by your books. Market-board filters only filter already loaded prices.')
    breakdown=[];seen_breakdown=set()
    for row in saved['rows']:
        identity=(row['Game'],row['Player'],row['Category'])
        if identity in seen_breakdown or not (row.get('Target breakdown') or row.get('Passing conversion breakdown') or row.get('Conversion rate %') is not None):continue
        seen_breakdown.add(identity)
        breakdown.append({key:row.get(key) for key in ('Game','Player','Category','Projection (count)','Expected opportunities','Conversion rate %','Historical error range low','Historical error range high','Player targets forecast','Target share forecast %','Supporting team attempts','Supporting catch probability %','Supporting receptions forecast','Supporting receiving yards forecast','Supporting completions forecast','Supporting passing TD forecast')})
    if breakdown:
        with st.expander('Passing and receiving forecast calculations',expanded=False):
            st.dataframe(breakdown,hide_index=True,use_container_width=True)
            st.caption('Completion/TD counts combine expected attempts and conversion uncertainty. Target breakdowns explain receiving workload; supporting reception/yardage forecasts do not replace the selected model or create a target bet. Add Passing completions or Passing touchdowns to requested prop categories to compare actual quotes; extra requested markets can spend credits.')
    priors={}
    for row in saved['rows']:
        if row.get('Last-season games') is not None:priors.setdefault((row['Game'],row['Player'],row['Category']),row)
    if priors:
        with st.expander('NFL projections — last-season starting point and new-season blend'):
            fields=('Game','Player','Category','Projection (yards)','Projection (count)','Expected opportunities','Last-season games','Current-season appearances','Current-season weight %','Role uncertainty','Reason')
            render_team_table([{k:r.get(k) for k in fields} for r in priors.values()],hide_index=True,use_container_width=True,sport='NFL')
            st.caption('New-season weight is n/(n+4): 0 games = 0%, 1 = 20%, 4 = 50%, 8 = 67%. Fresh availability and verified coverage are still required. Stat forecasts can appear before they qualify as picks; new-team roles and teammate injury impacts remain uncertain.')
    workload_rows={}
    for row in saved['rows']:
        if row.get('Workload candidate opportunities') is not None:workload_rows.setdefault((row['Game'],row['Player'],row['Category']),row)
    if workload_rows:
        with st.expander('Workload and lineup scenarios — research comparisons'):
            st.caption('Candidate workload changes are tracked separately and do not change the recommended direction or saved probability. Low/high scenarios are observed-workload sensitivity examples, not picks or probabilities.')
            fields=('Game','Player','Category','Expected opportunities','Workload candidate opportunities','Workload candidate projection','Workload candidate status','Supporting team workload','Supporting player workload share %','Confirmed unavailable teammates','Lineup scenario limitation')
            render_team_table([{k:r.get(k) for k in fields}for r in workload_rows.values()],hide_index=True,use_container_width=True,sport='NFL')
            labels=list(workload_rows)
            chosen=st.selectbox('Inspect workload sensitivity',labels,format_func=lambda k:' · '.join(k),key='nfl_workload_sensitivity')
            st.dataframe(workload_rows[chosen]['Workload sensitivity scenarios'],hide_index=True,use_container_width=True)
            st.write(workload_rows[chosen].get('Workload candidate benchmark',{}))
            if workload_rows[chosen].get('Game context scenarios'):st.write(workload_rows[chosen]['Game context scenarios'])
    from saved_pick_explanation import render_current_explanations
    from nfl_forecast_evidence import render_evidence
    render_evidence(saved['rows'])
    render_current_explanations(saved['rows'],'nfl_current')
    display=highest_probability(display,'Estimated win %',decision_key='Decision')
    watch = [r for r in display if r['Decision'] != 'Pass']
    st.caption('Qualifying picks are sorted by estimated win probability, highest first. Pass rows follow when included; missing probabilities are last.')
    st.write(f'**{len(watch)} unique experimental paper picks; {len(display)-len(watch)} player/category passes.**')
    picks_only=st.checkbox('Show only qualifying paper picks',value=True,key='nfl_only_clear_picks_v2')
    table=watch if picks_only else display
    if table:render_team_table(table,hide_index=True,use_container_width=True, sport='NFL')
    rejected=[{key:r.get(key) for key in ('Player','Category','Current roster team','Latest historical team','Current-team games','Roster/history status','Research summary','Forecast lean','Forecast projection','Compared direction','Compared line','Compared sportsbook','Compared odds','Compared direction win %','Compared break-even %','Compared edge (pp)','Reason')} for r in display if r['Decision']=='Pass']
    if rejected:
        with st.expander('Why other player props did not qualify'):
            st.caption('A Pass is not an Under prediction. Missing history and unsupported positions mean the model could not evaluate the prop; insufficient price edge means the evaluated quote did not qualify. Market-board category filters only change the price display, not which prediction models exist.')
            render_team_table(rejected,hide_index=True,use_container_width=True, sport='NFL')
            st.caption('Forecast lean compares the central projection with the displayed line. The win probability belongs to the compared Over/Under direction and can differ from that central lean because of the forecast distribution. PASS rows are research only and are not saved as recommended picks. Missing data produces no reliable lean.')
    st.caption('Risk labels use unverified model probabilities: 70%+ win = lower estimated loss risk; 60–69.9% = moderate; 50–59.9% = elevated; below 50% = high. These are relative labels, not safe bets or proven confidence levels. Value selections can qualify because of payout even when more likely to lose.')
    cushions=analyzed_cushions(cushion_inputs,events,books,saved.get('models',{}),season_priors=saved.get('season_prior_reports',{}))
    grouped_cushions=defaultdict(list)
    for c in cushions:grouped_cushions[(c['Game'],c['Player'],c['Category'])].append(c)
    cushions=[]
    for group in grouped_cushions.values():
        qualified=[c for c in group if c['Cushion decision']!='Pass']
        if len({c['Direction'] for c in qualified})>1:
            row=dict(qualified[0],**{'Cushion decision':'Pass','Reason':'Qualifying cushion directions conflict; no single selection.'})
        else:row=max(qualified or group,key=lambda c:num(c.get('Model edge (pp)')) if num(c.get('Model edge (pp)')) is not None else -999)
        cushions.append(row)
    if cushions:
        for r in cushions:
            r['Risk label']=estimated_risk(r.get('Recalculated win %')) if r['Cushion decision']!='Pass' else 'Pass — no selection'
        st.subheader('Analyzed passing and receiving cushions')
        st.caption('Cushions follow the selected original direction. Rejected originals are compared only when no original qualifies; Pass rows are not recommendations. Passing targets 30 yards (available range 25–40); receiving targets 25 yards (range 20–25), never below a 15-yard line. Also evaluates price-rejected originals with usable forecasts. Missing-history and unsupported props stay excluded. Actual alternate quotes, recalculated probabilities and price filters are required. Small original receiving lines may have no valid cushion. Separate paper experiment; Kalshi quotes are not connected.')
        render_team_table(cushions,hide_index=True,use_container_width=True, sport='NFL')
        output=io.StringIO();writer=csv.DictWriter(output,fieldnames=['Recorded UTC']+list(dict.fromkeys(key for r in cushions for key in r)));writer.writeheader()
        for r in cushions:writer.writerow({'Recorded UTC':saved['analyzed'],**r})
        autosave_report('Download analyzed cushion comparison',output.getvalue(),file_name='kamikaze_picks_analyzed_cushions.csv',mime='text/csv',key='analyzed_cushion_export')
    render_cushion_tracker(watch, starts)
    publish_rows(watch+[r for r in cushion_inputs if r['Decision']=='Pass'], events, cushions)
    if watch:
        st.caption('One experimental paper direction per player/category; the retained quote has the highest estimated return among qualifying loaded quotes. Historical error ranges use the middle 80% of scaled 2024 forecast errors, not guaranteed limits. Confirm player participation and conditions. Profitability at actual sportsbook prices is unverified.')
    else:
        if display:
            st.info('No qualifying modeled paper picks. See Reason beside each Pass; missing data and failed model tests do not establish an Under or Over.')
        else:
            st.info('No supported modeled props were available to analyze for the selected sportsbook. Other loaded markets can be viewed in the prices table and used in the paper parlay builder; they do not have tested pick models yet.')
    with st.expander('Check the prop model test results'):
        render_team_table(saved['reports'],hide_index=True,use_container_width=True, sport='NFL')
        st.caption('2024 chooses forecast parameters and supplies errors. The opportunity experiment uses 2025 as development evidence; future saved picks provide the prospective test. The original report uses benchmark thresholds, not historical sportsbook prices. Missing/DNP rows are not assigned zero. Availability gates remain active, but injury impacts, weather and lineup changes were not backtested. Failed baseline or price checks remain Pass.')
        st.markdown('[Statistics source: nflverse](https://nflreadr.nflverse.com/reference/load_player_stats.html)')
    if display:
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer,fieldnames=['Recorded UTC','Game starts UTC']+list(dict.fromkeys(key for row in display for key in row)))
        writer.writeheader()
        for row in display:
            writer.writerow({'Recorded UTC':saved['analyzed'],'Game starts UTC':starts[row['Game']],**row})
        autosave_report('Download this prop analysis',buffer.getvalue(),file_name='nfl_prop_analysis.csv',mime='text/csv',key='nfl_prop_export')
    st.caption(f"Analysis time: {saved['analyzed']}. Statistics retrieved: {saved['retrieved']}. This is a research shortlist; no automatic bets are placed.")

