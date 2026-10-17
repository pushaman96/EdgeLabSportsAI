"""Team emblems from ESPN metadata already loaded by the app. No API requests."""
from urllib.parse import urlparse

def logo_url(team):
    candidates=[team.get('logo')]+[r.get('href') for r in team.get('logos',[]) if isinstance(r,dict)]
    for url in candidates:
        if isinstance(url,str) and urlparse(url).scheme=='https' and (urlparse(url).hostname or '').endswith('.espncdn.com'):return url
    return None

def team_index(competitions,sport):
    result={}
    for competition in competitions:
        for competitor in competition.get('competitors',[]):
            team=competitor.get('team',{});entry={'name':team.get('displayName'),'abbreviation':team.get('abbreviation'),'logo':logo_url(team)}
            for value in (team.get('id'),team.get('displayName'),team.get('abbreviation')):
                if value:result[sport+':'+str(value)]=entry
            if sport=='NFL':
                for source,target in {'LAR':'LA','WSH':'WAS'}.items():
                    if team.get('abbreviation')==source:result[sport+':'+target]=entry
    return result

def remember_teams(scoreboard,sport):
    import streamlit as st
    entries=team_index([c for e in scoreboard.get('events',[]) for c in e.get('competitions',[])],sport)
    st.session_state.setdefault('team_emblems',{}).update(entries)

def pick_team(record,data=None,index=None):
    sport=record.get('sport','NFL');index=dict(index or {})
    if data:index.update(team_index(data.get('header',{}).get('competitions',[]),sport))
    if record.get('category')=='Moneyline':name=record.get('player')
    else:name=(record.get('forecast_context') or {}).get('Current roster team')
    entry=index.get(sport+':'+str(name)) if name else None
    if entry:return entry
    # If no frozen team was saved, use an unambiguous athlete match from this game's feed.
    matches=[]
    for block in (data or {}).get('boxscore',{}).get('players',[]):
        if any(a.get('athlete',{}).get('displayName')==record.get('player') for group in block.get('statistics',[]) for a in group.get('athletes',[])):
            team=block.get('team',{});key=sport+':'+str(team.get('id') or team.get('displayName'))
            if key in index:matches.append(index[key])
    unique={m['name']:m for m in matches}
    return next(iter(unique.values())) if len(unique)==1 else None

def render_team_score(column,team,score):
    name=team.get('displayName','Team');url=logo_url(team)
    if not url:column.metric(name,score);return
    emblem,text=column.columns([1,7]);emblem.image(url,width=28);text.metric(name,score)
