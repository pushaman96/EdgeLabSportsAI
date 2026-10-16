"""Live roster/injury eligibility screen. Does not invent injury-adjusted win odds."""
from collections import defaultdict
from datetime import datetime,timezone
from concurrent.futures import ThreadPoolExecutor
import streamlit as st
from nfl_prop_model import name_key,num,ALIASES,injury_context,current_roster,load_season_stats

def utc(v):return datetime.fromisoformat(str(v).replace('Z','+00:00'))

def screen_team(team,code,roster,injuries,players,season,week,now=None):
    now=now or datetime.now(timezone.utc)
    result={'team':team,'eligible':False,'reason':'Injury verification unavailable','issues':[],'reported_injuries':[],'checked_utc':now.isoformat(),'source':'ESPN injury report + current roster + completed nflverse usage','source_updated':injuries.get('source_updated') if injuries else None}
    if not roster or not injuries or team not in injuries.get('teams',set()):return result
    try:
        if int(injuries.get('season') or 0)!=season or not -600<=(now-utc(injuries['source_updated'])).total_seconds()<=21600 or not 0<=(now-utc(injuries['retrieved'])).total_seconds()<=900:
            result['reason']='Injury report stale or from another season';return result
    except (ValueError,KeyError,TypeError):return result
    names=defaultdict(list)
    for p in roster:names[name_key(p['name'])].append(p)
    rows=[r for r in players if r['season']==season and r['week']<week and r['team']==code]
    weeks=sorted({r['week'] for r in rows})[-4:]
    rows=[r for r in rows if r['week'] in weeks]
    usage=defaultdict(lambda:{'attempts':0,'carries':0,'targets':0,'position':None,'name':None})
    for r in rows:
        key=name_key(r['player_display_name'])
        if len(names.get(key,[]))!=1:continue
        u=usage[key];u['position']=r['position'];u['name']=r['player_display_name']
        for field in ('attempts','carries','targets'):u[field]+=num(r.get(field)) or 0
    passers=[(k,u) for k,u in usage.items() if u['position']=='QB' and u['attempts']>0]
    if not passers:
        result['reason']='Recent primary quarterback cannot be verified on the current roster';return result
    qb=max(passers,key=lambda x:x[1]['attempts'])[0]
    totals={f:sum(u[f] for u in usage.values()) for f in ('attempts','carries','targets')}
    key_players={qb}
    for key,u in usage.items():
        if (totals['carries'] and u['carries']/totals['carries']>=.2) or (totals['targets'] and u['targets']/totals['targets']>=.15):key_players.add(key)
    result['recent_primary_qb']=usage[qb]['name']
    for key,entries in names.items():
        if len(entries)!=1:continue
        athlete=entries[0]
        status=injuries.get('statuses',{}).get((team,key),'Not listed')
        roster_status=str(athlete.get('status','Unknown'))
        if status.lower() in ('active','not listed') and (roster_status.lower()=='active' or (key not in key_players and roster_status.lower()=='practice squad')):continue
        item={'Player':athlete['name'],'Injury status':status,'Roster status':roster_status,'Key recent offensive role':key in key_players}
        result['reported_injuries'].append(item)
        if key in key_players:
            result['issues'].append(athlete['name']+': '+status+' / roster '+roster_status)
    if result['issues']:
        result['reason']='Key-player availability changes are not modeled: '+'; '.join(result['issues'])
    else:
        result['eligible']=True;result['reason']='Recent primary QB and major usage players passed availability checks; Elo remains unadjusted for injuries, replacements, offensive line and defense.'
    return result

@st.cache_data(ttl=300)
def load_matchup_screens(scoreboard):
    events=scoreboard.get('events',[]);teams={};years=set()
    for event in events:
        season=event.get('season',scoreboard.get('season',{}))
        if int(season.get('type') or 0)!=2:continue
        year=int(season['year']);years.add(year)
        for c in event.get('competitions',[{}])[0].get('competitors',[]):
            t=c.get('team',{});teams[t.get('displayName')]=t
    reports={};rosters={};stats={}
    try:injuries=injury_context()
    except Exception:injuries=None
    for year in years:
        try:stats[year]=load_season_stats('player',year)
        except Exception:stats[year]=[]
    with ThreadPoolExecutor(max_workers=6) as pool:
        tasks={name:pool.submit(current_roster,t['id']) for name,t in teams.items() if t.get('id')}
        for name,task in tasks.items():
            try:rosters[name]=task.result()
            except Exception:rosters[name]=[]
    for event in events:
        season=event.get('season',scoreboard.get('season',{}))
        if int(season.get('type') or 0)!=2:continue
        year=int(season['year']);week=int(event.get('week',scoreboard.get('week',{})).get('number') or 0)
        competition=event.get('competitions',[{}])[0];home=away=None;sides=[]
        for c in competition.get('competitors',[]):
            t=c.get('team',{});name=t.get('displayName');code=ALIASES.get(t.get('abbreviation'),t.get('abbreviation'))
            screen=screen_team(name,code,rosters.get(name,[]),injuries,stats.get(year,[]),year,week)
            sides.append(screen)
            if c.get('homeAway')=='home':home=name
            elif c.get('homeAway')=='away':away=name
        if home and away:
            ok=len(sides)==2 and all(s['eligible'] for s in sides)
            reports[home,away]={'eligible':ok,'reason':' | '.join(s['team']+': '+s['reason'] for s in sides),'teams':sides,'checked_utc':datetime.now(timezone.utc).isoformat(),'source_updated':injuries.get('source_updated') if injuries else None}
    return reports

def render_matchup_screen(scoreboard,home_code,away_code):
    reports=load_matchup_screens(scoreboard)
    for event in scoreboard.get('events',[]):
        comp=event.get('competitions',[{}])[0];home=next((c.get('team',{}) for c in comp.get('competitors',[]) if c.get('homeAway')=='home'),{});away=next((c.get('team',{}) for c in comp.get('competitors',[]) if c.get('homeAway')=='away'),{})
        if ALIASES.get(home.get('abbreviation'),home.get('abbreviation'))!=home_code or ALIASES.get(away.get('abbreviation'),away.get('abbreviation'))!=away_code:continue
        report=reports.get((home.get('displayName'),away.get('displayName')))
        if report:
            if report['eligible']:st.info(report['reason'])
            else:st.warning('Injury warning — historical Elo does not account for these availability changes. '+report['reason'])
            rows=[dict(item,Team=s['team']) for s in report['teams'] for item in s['reported_injuries']]
            if rows:st.dataframe(rows,hide_index=True,use_container_width=True)
            st.caption('Injury source updated: '+str(report['source_updated'])+'; verified: '+report['checked_utc']+'. No numerical injury adjustment has been validated.')
            return report
    st.warning('No selected-date matchup could be matched for injury verification. Elo percentages below are historical-only and are not a verified pick.')
    return None
