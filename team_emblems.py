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
            team=competitor.get('team',{});entry={'id':str(team.get('id','')),'name':team.get('displayName'),'abbreviation':team.get('abbreviation'),'logo':logo_url(team),'color':team.get('color')}
            for value in (team.get('id'),team.get('displayName'),team.get('abbreviation')):
                if value:result[sport+':'+str(value)]=entry
            if sport=='NFL':
                for source,target in {'LAR':'LA','WSH':'WAS'}.items():
                    if team.get('abbreviation')==source:result[sport+':'+target]=entry
    if sport=='NBA':
        for source,target in {'GSW':'GS','NYK':'NY','NOP':'NO','SAS':'SA','UTA':'UTAH','WAS':'WSH','LA Clippers':'Los Angeles Clippers'}.items():
            if sport+':'+target in result:result[sport+':'+source]=result[sport+':'+target]
            elif sport+':'+source in result:result[sport+':'+target]=result[sport+':'+source]
    return result

def remember_teams(scoreboard,sport):
    import streamlit as st
    entries=directory_index(sport)
    entries.update(team_index([c for e in scoreboard.get('events',[]) for c in e.get('competitions',[])],sport))
    current=st.session_state.setdefault('team_emblems',{})
    for key,value in entries.items():
        if not value.get('logo') and current.get(key,{}).get('logo'):value=dict(value,logo=current[key]['logo'])
        current[key]=value

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


def directory_index(sport):
    """Cached full-league directory covers games outside the selected scoreboard."""
    import streamlit as st
    import json
    from urllib.request import urlopen
    @st.cache_data(ttl=86400,show_spinner=False)
    def fetch(league,emblem_schema=2):
        path='football/nfl' if league=='NFL' else 'basketball/nba'
        data=json.load(urlopen('https://site.api.espn.com/apis/site/v2/sports/'+path+'/teams?limit=100',timeout=12))
        competitors=[entry for s in data.get('sports',[]) for l in s.get('leagues',[]) for entry in l.get('teams',[])]
        return team_index([{'competitors':competitors}],league)
    try:return fetch(sport,2)
    except (OSError,ValueError,KeyError,TypeError):return {}

def enrich_rows(rows,sport,index,team=None):
    """Return display copies; never add image URLs to model inputs or saved records."""
    output=[]
    fields=('Team','TEAM_NAME','TEAM_ABBREVIATION','Current roster team','Home team','Away team','Defense','Opposing offense','Team to research','Player/team','Player / team','Saved team')
    for original in rows:
        row=dict(original);images={}
        for field in fields:
            value=row.get(field)
            if value is not None:
                match=index.get(sport+':'+str(value))
                if match and match.get('logo'):images[field+' emblem']=match['logo']
        if not images and team is not None:
            match=index.get(sport+':'+str(team))
            if match and match.get('logo'):images['Team emblem']=match['logo']
        if not images and ' at ' in str(row.get('Game','')):
            away,home=row['Game'].split(' at ',1)
            for label,name in (('Away emblem',away),('Home emblem',home)):
                match=index.get(sport+':'+name)
                if match and match.get('logo'):images[label]=match['logo']
        output.append({**images,**row})
    return output

def render_team_table(rows,sport,team=None,**kwargs):
    import streamlit as st
    index=st.session_state.get('team_emblems',{})
    display=enrich_rows(rows,sport,index,team)
    columns=dict(kwargs.pop('column_config',{}) or {})
    for row in display:
        for key in row:
            if key.endswith(' emblem'):columns[key]=st.column_config.ImageColumn('',width='small')
    st.dataframe(display,column_config=columns,**kwargs)

