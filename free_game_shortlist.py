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
        ready=fresh and len(players)>=2 and len(categories)>=2
        rows.append({
            'Game':event.get('name') or event.get('shortName') or str(event.get('id')),
            'Research priority':'Research first' if ready else 'Needs more research',
            'Categories to inspect':', '.join(categories) if ready else 'No supported shortlist yet',
            'Players with clearer workload evidence':', '.join(players[:6]) if ready else 'Not enough fresh evidence',
            'Reason':(f'{len(players)} players across {len(categories)} categories have prepared projections without a flagged role uncertainty.' if ready else 'Research is missing, older than six hours, or has insufficient clear-role coverage.'),
            'Role-uncertain forecasts':len(checked)-len(reliable),
            'Prepared forecasts':len(checked),
            'Kickoff UTC':start.isoformat(),
            'Research updated UTC':report.get('generated_utc'),
            '_rank':(int(ready),ratio,len(categories),min(len(players),10)),
        })
    rows.sort(key=lambda r:r['_rank'],reverse=True)
    ready=[r for r in rows if r['Research priority']=='Research first'][:3]
    for r in rows:r.pop('_rank',None)
    return {'shortlist':ready,'all_games':rows,'fresh':fresh,'issues':item.get('issues',[])}

def render(sport,scoreboard):
    import streamlit as st
    from pathlib import Path
    import json
    st.subheader('Games to research for props — 0 odds credits')
    st.caption('Research priority, not a best-bet ranking or hit probability. Uses saved free player/workload research for upcoming regular-season games. It does not load odds, select bets or spend credits.')
    try:
        report=json.loads(Path('background_research.json').read_text())
    except (OSError,ValueError):
        report={}
    result=build(report,sport,scoreboard)
    if result['shortlist']:
        from team_emblems import render_team_table
        render_team_table(result['shortlist'],sport=sport,hide_index=True,use_container_width=True)
    else:
        st.info('No game has enough fresh prepared research for a shortlist yet. Free background research updates automatically; no odds request was made.')
    with st.expander('All upcoming games — research coverage and cautions'):
        if result['all_games']:st.dataframe(result['all_games'],hide_index=True,use_container_width=True)
        if result['issues']:st.write(result['issues'])
        st.caption('Ranking uses research coverage and unflagged workload roles; it has not been validated as a predictor of winning bets. Availability, starting lineups and the exact sportsbook line still require checking. Games can produce no qualifying picks after lines are analyzed.')
