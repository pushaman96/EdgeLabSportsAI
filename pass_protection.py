from team_emblems import render_team_table
"""Observed NFL sack matchup context. Not an offensive-line grade or bet model."""
from collections import defaultdict
from datetime import date
import math

def number(v):
    try:
        n=float(v);return n if math.isfinite(n) and n>=0 else None
    except (TypeError,ValueError):return None

def profiles(rows,schedule,asof):
    games={g['game_id']:g for g in schedule if g.get('gameday') and g['gameday']<str(asof) and number(g.get('home_score')) is not None and number(g.get('away_score')) is not None}
    usable=[];seen=set()
    for r in rows:
        key=(r.get('game_id'),r.get('team'))
        if r.get('season_type')!='REG' or r.get('game_id') not in games or key in seen:continue
        if any(number(r.get(k)) is None for k in ('attempts','sacks_suffered')):continue
        seen.add(key);usable.append(r)
    bygame={(r['game_id'],r['team']):r for r in usable}
    groups=defaultdict(list)
    for r in usable:groups[r['team']].append(r)
    result={}
    for team,history in groups.items():
        att=sum(number(r['attempts']) for r in history);allowed=sum(number(r['sacks_suffered']) for r in history)
        defense=[]
        for r in history:
            opponent=bygame.get((r['game_id'],r['opponent_team']))
            if opponent: defense.append(opponent)
        faced=sum(number(r['attempts'])+number(r['sacks_suffered']) for r in defense)
        made=sum(number(r['sacks_suffered']) for r in defense)
        hits=[number(bygame[(r['game_id'],r['opponent_team'])].get('def_qb_hits')) for r in history if (r['game_id'],r['opponent_team']) in bygame]
        result[team]={'Team':team,'Games':len(history),'Passing attempts':att,'Sacks allowed':allowed,'Sacks allowed / game':allowed/len(history),'Sack allowed rate %':100*allowed/(att+allowed) if att+allowed else None,'Average dropbacks':(att+allowed)/len(history),'Defensive games matched':len(defense),'Defensive sacks':made if defense else None,'Defensive sack rate %':100*made/faced if faced else None,'QB hits allowed':sum(hits) if hits and all(h is not None for h in hits) else None,'Latest game':max(games[r['game_id']]['gameday'] for r in history)}
    return result

def matchup(defense,offense):
    if defense['Defensive games matched']<4 or offense['Games']<4:return None
    d=defense['Defensive sack rate %'];o=offense['Sack allowed rate %']
    if d is None or o is None:return None
    return .5*(d+o)/100*offense['Average dropbacks']

def display_profiles(data):
    """Round presentation only; retain precise rates for matchup calculations."""
    rows=[]
    for profile in data.values():
        row=dict(profile)
        for key,value in row.items():
            if isinstance(value,(int,float)) and not isinstance(value,bool):
                if key.endswith('%'):
                    row[key]=f'{value:.0f}%'
                elif isinstance(value,float):
                    row[key]=round(value,1)
        rows.append(row)
    return rows

def render_pass_protection(season,asof,auto_load=False,prefix='team_stats'):
    import streamlit as st
    from nfl_prop_model import csv_url, SCHEDULE_URL
    st.subheader('Projected team sacks')
    st.caption('Estimated sacks for each defense, combining its sack production with the opposing offense’s pass-protection record. Experimental estimates, not guaranteed totals or betting recommendations.')
    if st.button('Load defense & offensive-line context — 0 odds credits',key=prefix+'_load_sack_context'):st.session_state[prefix+'_sack_context_loaded']=True
    if not auto_load and not st.session_state.get(prefix+'_sack_context_loaded'):return
    @st.cache_data(ttl=21600,show_spinner=False)
    def load(year):
        return csv_url(f'https://github.com/nflverse/nflverse-data/releases/download/stats_team/stats_team_week_{year}.csv'),csv_url(SCHEDULE_URL)
    try:
        raw,schedule=load(season);data=profiles(raw,schedule,asof)
        if not data:st.info('No completed regular-season sack data is available before the selected date.');return
        slate=[]
        aliases={'STL':'LA','LAR':'LA','SD':'LAC','OAK':'LV'}
        for game in schedule:
            if game.get('gameday')!=str(asof) or str(game.get('season'))!=str(season):continue
            for defender,opponent in ((game.get('home_team'),game.get('away_team')),(game.get('away_team'),game.get('home_team'))):
                defender=aliases.get(defender,defender);opponent=aliases.get(opponent,opponent)
                if defender not in data or opponent not in data:continue
                estimate=matchup(data[defender],data[opponent])
                defensive_games=data[defender]['Defensive games matched']
                defensive_average=data[defender]['Defensive sacks']/defensive_games if defensive_games else None
                allowed=data[opponent]['Sacks allowed / game']
                slate.append({'Defense':defender,'Opposing offense':opponent,'Projected sacks this game':round(estimate,1) if estimate is not None else None,'Why':f"Defense averages {defensive_average:.1f} sacks/game; opponent allows {allowed:.1f}." if defensive_average is not None else 'Not enough matched game history.'})
        if slate:
            st.write('**Projected sacks for each selected game**')
            selected=st.selectbox('Team sack projection',list(range(len(slate))),format_func=lambda i:slate[i]['Defense']+' defense vs '+slate[i]['Opposing offense'],key=prefix+'_projected_sack_team')
            projection=slate[selected]
            value=projection['Projected sacks this game']
            st.metric(projection['Defense']+' projected team sacks',f'{value:.1f}' if value is not None else 'Not enough history')
            if value is not None:
                st.write(f"{projection['Defense']} is projected to record about {value:.1f} sacks against {projection['Opposing offense']} in this game.")
            st.caption('Matchup-specific experimental expectation, not a guaranteed total or a prediction for every game. A decimal describes an average expectation.')

            render_team_table(slate,hide_index=True,use_container_width=True, sport='NFL')
            from automatic_reports import autosave_report
            import json
            autosave_report('Team sack research',json.dumps({'season':season,'asof':str(asof),'rows':slate},sort_keys=True),file_name=f'nfl_team_sack_research_{season}.json',mime='application/json')
        st.caption('More sacks allowed can raise the estimate, especially against a productive pass rush. Quarterback play, quick throws and game flow also matter; sacks allowed are a team protection measure, not an individual blocker grade. Blank estimates mean fewer than four usable games.')
        with st.expander('Explore protection statistics and the calculation'):
            render_team_table(display_profiles(data),hide_index=True,use_container_width=True, sport='NFL')
            names=sorted(data)
            defense=st.selectbox('Defense to examine',names,key=prefix+'_sack_defense')
            offense=st.selectbox('Opposing offense to examine',[n for n in names if n!=defense],key=prefix+'_sack_offense')
            estimate=matchup(data[defense],data[offense])
            if estimate is None:st.info('At least four matched defensive games and four offensive games are needed for the research comparison.')
            else:st.metric(defense+' projected team sacks vs '+offense,f'{estimate:.1f}')
            st.caption('Reference = average of defensive sack rate and opponent sack-allowed rate × opponent average dropbacks. This simple comparison has not passed a sportsbook-line backtest, provides no Over/Under recommendation or win probability, and does not change current picks. A weak protection record can raise sack risk, but quick throws, scrambling, line injuries and game script can change it. Pressures, time to throw and individual blocker grades are not supplied here. Data excludes games on or after the sidebar date.')
    except Exception:st.warning('Sack and protection data could not be loaded. Missing data is not interpreted as zero; retry later.')


