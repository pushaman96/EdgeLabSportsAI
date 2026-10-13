"""Measured historical usage. Not yet an injury or causal-dependence model."""
from collections import defaultdict
from datetime import datetime,timezone
import streamlit as st
import requests
from nfl_prop_model import load_prop_research,csv_url,num,name_key,ALIASES

@st.cache_data(ttl=21600)
def load_snap_usage(season):
    return csv_url(f'https://github.com/nflverse/nflverse-data/releases/download/snap_counts/snap_counts_{season}.csv')

def nfl_role_rows(players,teams,snaps,season,before_week):
    team_games={(r['team'],r['game_id']):r for r in teams if r['season']==season and r['week']<before_week}
    snap_index=defaultdict(list)
    for r in snaps:
        if int(r['season'])!=season or r.get('game_type')!='REG' or int(r['week'])>=before_week:continue
        key=(ALIASES.get(r['team'],r['team']),r['game_id'],name_key(r['player']))
        snap_index[key].append(r)
    grouped=defaultdict(list)
    for r in players:
        if r['season']==season and r['week']<before_week:grouped[(r['team'],r['player_id'])].append(r)
    out=[]
    for (team,pid),history in grouped.items():
        recent=sorted(history,key=lambda r:r['week'])[-4:]
        row={'Player':recent[-1]['player_display_name'],'Team':team,'Position':recent[-1]['position'],
             'Observed games':len(recent),'Latest week':recent[-1]['week']}
        for field,label in [('targets','Target'),('carries','Carry'),('attempts','Pass-attempt')]:
            pairs=[(r,team_games.get((team,r['game_id']))) for r in recent]
            pairs=[(r,t) for r,t in pairs if t and r[field] is not None and t[field] is not None]
            denominator=sum(t[field] for _,t in pairs)
            row[label+' share %']=round(100*sum(r[field] for r,_ in pairs)/denominator,1) if denominator>0 else None
            values=[r[field] for r in recent if r[field] is not None]
            row[label+' opportunities/game']=round(sum(values)/len(values),2) if values else None
        joined=[]
        for r in recent:
            found=snap_index.get((team,r['game_id'],name_key(r['player_display_name'])),[])
            if len(found)==1:joined.append((r,found[0]))
        fractions=[num(s['offense_pct']) for _,s in joined if num(s.get('offense_pct')) is not None]
        row['Offensive snap %']=round(100*sum(fractions)/len(fractions),1) if fractions else None
        row['Snap games matched']=len(joined)
        usable=[(r,s) for r,s in joined if num(s.get('offense_snaps')) is not None and r['targets'] is not None]
        snap_total=sum(num(s['offense_snaps']) for _,s in usable)
        row['Targets per offensive snap']=round(sum(r['targets'] for r,_ in usable)/snap_total,3) if snap_total else None
        out.append(row)
    return out

def render_nfl_usage():
    with st.expander('NFL player usage and role evidence — all teams'):
        st.caption('Measures earlier-game target/carry shares and offensive snap participation. Shares use team totals from the same games in which player stats are observed; missing games are not zero-filled. Snap joins require a unique name/team/game match. These inputs are not yet enabled as new prediction factors.')
        if st.button('Load NFL player usage',key='nfl_role_load'):
            try:
                season=datetime.now(timezone.utc).year
                research=load_prop_research(season);snaps=load_snap_usage(season)
                st.session_state['nfl_role_measurements']={'rows':nfl_role_rows(research['players'],research['teams'],snaps,season,23),'retrieved':research['retrieved']}
            except (requests.exceptions.RequestException,ValueError,KeyError,TypeError,OSError):st.warning('Player usage could not be loaded. Forecasts remain available.');return
        saved=st.session_state.get('nfl_role_measurements')
        if not saved:return
        teams=sorted({r['Team'] for r in saved['rows']})
        selected=st.selectbox('Usage team',['All teams']+teams,key='nfl_role_team')
        shown=[r for r in saved['rows'] if selected=='All teams' or r['Team']==selected]
        search=st.text_input('Usage player search',key='nfl_role_player').strip().lower()
        if search:shown=[r for r in shown if search in r['Player'].lower()]
        st.dataframe(shown,hide_index=True,use_container_width=True)
        st.caption('Snap counts: nflverse/PFR. Weekly opportunities: nflverse. Routes, red-zone opportunities, confirmed starters and teammate-absence effects are not measured by this table. High usage does not establish that team wins depend on the player; lineup and game-situation confounding must be tested. Stats can lag newly completed games. Retrieved '+saved['retrieved'])

def nba_role_rows(players):
    out=[]
    for p in players:
        minutes=num(p.get('MIN'))
        row={'Player':p.get('PLAYER_NAME'),'Games':p.get('GP'),'Minutes/game':minutes,
             'Shots/game':p.get('FGA'),'3-point attempts/game':p.get('FG3A'),'Free-throw attempts/game':p.get('FTA')}
        for key,label in [('PTS','Points'),('FGA','Shots'),('REB','Rebounds'),('AST','Assists')]:
            value=num(p.get(key));row[label+' per 36 minutes']=round(36*value/minutes,2) if minutes and minutes>0 and value is not None else None
        out.append(row)
    return out
