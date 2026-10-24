"""Free research readiness shortlist; never calls an odds provider."""
from datetime import datetime, timezone, timedelta
from math import isfinite

CATEGORIES = {
    'NFL': {'Passing yards','Rushing yards','Receiving yards','Anytime touchdown'},
    'NBA': {'Points','Assists','Rebounds','Three-pointers made','PRA'},
}
def utc(value):
    return datetime.fromisoformat(str(value).replace('Z','+00:00'))
def valid(value):
    return isinstance(value,(int,float)) and not isinstance(value,bool) and isfinite(value) and value>=0

def build(report, sport, scoreboard, now=None):
    now=now or datetime.now(timezone.utc)
    try:
        generated=utc(report['generated_utc'])
        fresh=timedelta(0)<=now-generated<=timedelta(hours=6)
    except (KeyError,TypeError,ValueError):
        fresh=False
    item=report.get('sports',{}).get(sport,{})
    grouped={}
    for p in item.get('projections',[]):
        grouped.setdefault(str(p.get('event_id')),[]).append(p)
    rows=[]
    for event in scoreboard.get('events',[]):
        status=event.get('status',{}).get('type',{})
        if not status:
            status=(event.get('competitions') or [{}])[0].get('status',{}).get('type',{})
        try:
            start=utc(event['date'])
        except (KeyError,ValueError,TypeError):continue
        if start<=now or status.get('state')!='pre' or status.get('completed'):continue
        if event.get('season',scoreboard.get('season',{})).get('type')!=2:continue
        projections=grouped.get(str(event.get('id')),[])
        # Require this exact scheduled game and pregame research; no late observations.
        checked=[]
        for p in projections:
            try:
                if utc(p['starts_utc'])!=start or utc(p['published_utc'])>=start:continue
            except (KeyError,ValueError,TypeError):continue
            if p.get('category') in CATEGORIES.get(sport,set()) and valid(p.get('projection')):
                checked.append(p)
        unique={(p.get('player'),p.get('category')):p for p in checked}
        checked=list(unique.values())
        reliable=[p for p in checked if p.get('role_uncertain') is False and valid(p.get('workload')) and p['workload']>0]
        players=sorted({p['player'] for p in reliable})
        categories=sorted({p['category'] for p in reliable})
        ratio=len(reliable)/len(checked) if checked else 0
        latest=max((p.get('published_utc','') for p in checked),default='')
        try:game_fresh=fresh and timedelta(0)<=now-utc(latest)<=timedelta(hours=6)
        except (ValueError,TypeError):game_fresh=False
        ready=game_fresh and len(players)>=2 and len(categories)>=2
        if not checked:reason='No prepared forecasts for this exact selected-date game. The latest job may cover different games; see research timestamps.'
        elif not game_fresh:reason=f'{len(checked)} forecasts exist, but their research is older than six hours; refresh of free preparation is needed.'
        elif not reliable:reason=f'{len(checked)} forecasts exist, but all workload roles are flagged uncertain.'
        elif not ready:reason=f'Research exists, but only {len(players)} clear-role players across {len(categories)} categories qualify for prioritization.'
        else:reason=f'{len(players)} players across {len(categories)} categories have prepared projections without a flagged role uncertainty.'
        rows.append({
            'Game':event.get('name') or event.get('shortName') or str(event.get('id')),
            'Research priority':'Research first' if ready else 'Research available — refresh needed' if checked and not game_fresh else 'Research available — role caution' if checked else 'Not prepared for selected game',
            'Categories to inspect':', '.join(categories or sorted({p['category'] for p in checked})) if checked else 'No prepared categories',
            'Players with clearer workload evidence':', '.join(players[:6]) if ready else 'Not enough fresh evidence',
            'Reason':reason,
            'Role-uncertain forecasts':len(checked)-len(reliable),
            'Prepared forecasts':len(checked),
            'Kickoff UTC':start.isoformat(),
            'Research updated UTC':latest or report.get('generated_utc'),
            '_rank':(int(ready),ratio,len(categories),min(len(players),10)),
        })
    rows.sort(key=lambda r:r['_rank'],reverse=True)
    ready=[r for r in rows if r['Research priority']=='Research first'][:3]
    for r in rows:r.pop('_rank',None)
    return {'shortlist':ready,'all_games':rows,'fresh':fresh,'issues':item.get('issues',[])}

def research_board(report,sport,scoreboard,now=None):
    now=now or datetime.now(timezone.utc)
    def upcoming_regular(board):
        for event in board.get('events',[]):
            try:
                status=event.get('status',{}).get('type') or (event.get('competitions') or [{}])[0].get('status',{}).get('type',{})
                if utc(event['date'])>now and status.get('state')=='pre' and not status.get('completed') and event.get('season',board.get('season',{})).get('type')==2:
                    return True
            except (KeyError,ValueError,TypeError):continue
        return False
    if upcoming_regular(scoreboard):return scoreboard,False
    prepared=report.get('sports',{}).get(sport,{}).get('scoreboard',{})
    if upcoming_regular(prepared):return prepared,True
    return scoreboard,False

def render(sport,scoreboard):
    import streamlit as st
    from pathlib import Path
    import json
    st.subheader('Games to research for props — 0 odds credits')
    st.caption('Research priority, not a best-bet ranking or hit probability. Uses saved free player/workload research for upcoming regular-season games. It does not load odds, select bets or spend credits.')
    try:
        from runtime_health import snapshot
        def compact(data):
            return {'generated_utc':data.get('generated_utc'),'sports':{league:{'projections':part.get('projections',[]),'issues':part.get('issues',[]),'scoreboard':part.get('scoreboard',{})} for league,part in data.get('sports',{}).items()}}
        report=snapshot('background_research.json','free-shortlist-source-v3',compact,{})
        research_scoreboard,using_upcoming=research_board(report,sport,scoreboard)
        ids={str(e.get('id')) for e in research_scoreboard.get('events',[])}
        existing=report.get('sports',{}).get(sport,{}).get('projections',[])
        covered={str(p.get('event_id')) for p in existing}
        if ids-covered:
            def matching_history(data):
                return [p for p in data.get('records',[]) if p.get('sport')==sport and str(p.get('event_id')) in ids-covered]
            prior=snapshot('background_projection_history.json','free-shortlist-history-'+sport+'-'+','.join(sorted(ids-covered)),matching_history,[])
            report.setdefault('sports',{}).setdefault(sport,{}).setdefault('projections',[]).extend(prior)
    except (OSError,ValueError):
        report={}
    st.caption('Latest free preparation (UTC): '+str(report.get('generated_utc','Not available'))+'. Selected-game research is matched by game ID and scheduled start; older saved research is labeled separately.')
    research_scoreboard,using_upcoming=research_board(report,sport,scoreboard)
    if using_upcoming:
        st.info('No upcoming regular-season '+sport+' games on the selected score date. Showing prepared upcoming games within '+('72' if sport=='NFL' else '30')+' hours instead. Change the score date to that game date before loading its sportsbook props.')
    result=build(report,sport,research_scoreboard)
    if result['shortlist']:
        from team_emblems import render_team_table
        render_team_table(result['shortlist'],sport=sport,hide_index=True,use_container_width=True)
    else:
        st.info('No game currently qualifies for the research-first shortlist. The coverage table below distinguishes existing research, stale research, role cautions and games not yet prepared. No odds request was made.')
    with st.expander('All upcoming games — research coverage and cautions'):
        if result['all_games']:st.dataframe(result['all_games'],hide_index=True,use_container_width=True)
        if result['issues']:st.write(result['issues'])
        st.caption('Ranking uses research coverage and unflagged workload roles; it has not been validated as a predictor of winning bets. Availability, starting lineups and the exact sportsbook line still require checking. Games can produce no qualifying picks after lines are analyzed.')
