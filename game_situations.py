"""Descriptive play situations for reviewing forecasts, never pregame inputs."""
import math
from collections import defaultdict

def numeric(value):
    try:
        value=float(value)
        return value if math.isfinite(value) else None
    except (ValueError,TypeError):return None

def situation_snapshot(data,sport='NFL'):
    header=data.get('header',{});competition=(header.get('competitions') or [{}])[0]
    teams={str(t.get('team',{}).get('id',t.get('id',''))):t.get('team',{}).get('displayName','Unknown') for t in competition.get('competitors',[])}
    home=next((str(t.get('team',{}).get('id',t.get('id',''))) for t in competition.get('competitors',[]) if t.get('homeAway')=='home'),None)
    drives=list(data.get('drives',{}).get('previous',[]))
    current=data.get('drives',{}).get('current')
    if isinstance(current,dict):drives.append(current)
    raw=[(p,d.get('team',{}).get('id')) for d in drives for p in d.get('plays',[])] if sport=='NFL' else [(p,None) for p in data.get('plays',[])]
    if raw and all(numeric(p.get('sequenceNumber')) is not None for p,_ in raw):raw.sort(key=lambda pair:numeric(pair[0]['sequenceNumber']))
    rows=[];seen=set();previous=None;counts=defaultdict(lambda:dict(passes=0,runs=0,sacks=0))
    for play,drive_team in raw:
        ident=str(play.get('id',''))
        if not ident or ident in seen:continue
        seen.add(ident)
        start=play.get('start') or {};team=str(start.get('team',{}).get('id') or play.get('team',{}).get('id') or drive_team or '')
        before=previous
        h=numeric(play.get('homeScore'));a=numeric(play.get('awayScore'))
        if h is not None and a is not None:previous=(h,a)
        margin=(before[0]-before[1])*(1 if team==home else -1) if before is not None and team in teams and home else None
        state='Unknown' if margin is None else 'Trailing by 8+' if margin<=-8 else 'Leading by 8+' if margin>=8 else 'Within 7'
        text=str(play.get('text',''));kind=str(play.get('type',{}).get('text',''))
        lower=text.lower();typ=kind.lower();category='Other'
        if sport=='NFL':
            if 'no play' in lower or 'penalty' in typ:category='No play / penalty'
            elif 'kneel' in lower or 'kneel' in typ:category='Kneel'
            elif 'spike' in typ or 'spikes the ball' in lower:category='Spike'
            elif 'sack' in typ or 'sacked' in lower:category='Sack'
            elif 'scrambl' in lower:category='QB scramble'
            elif 'pass' in typ or 'interception' in typ:category='Pass attempt'
            elif 'rush' in typ:category='Designed run'
        period=play.get('period',{}).get('number')
        row={'Play ID':ident,'Team':teams.get(team),'Period':period,'Clock':play.get('clock',{}).get('displayValue'),'Down':start.get('down') if sport=='NFL' else None,'Distance':start.get('distance') if sport=='NFL' else None,'Yard line':start.get('yardLine') if sport=='NFL' else None,'Score margin before play':margin,'Situation':state,'Classification':category if sport=='NFL' else kind,'Text':text}
        rows.append(row)
        if sport=='NFL' and team in teams and category in ('Pass attempt','Designed run','Sack','QB scramble'):
            bucket=counts[(teams[team],state,'Unknown' if not isinstance(period,int) else 'Overtime' if period>4 else 'Regulation')]
            bucket['passes']+=int(category in ('Pass attempt','QB scramble','Sack'));bucket['runs']+=int(category=='Designed run');bucket['sacks']+=int(category=='Sack')
    splits=[]
    for (team,state,phase),count in counts.items():
        total=count['passes']+count['runs']
        splits.append({'Team':team,'Situation':state,'Phase':phase,'Classified dropbacks':count['passes'],'Designed runs':count['runs'],'Sacks':count['sacks'],'Pass-call %':round(100*count['passes']/total,1) if total else None})
    status=competition.get('status',{})
    return {'schema':1,'sport':sport,'event_id':str(header.get('id','')),'completed':bool(status.get('type',{}).get('completed')),'plays':rows,'situation_splits':splits,'last_play':rows[-1] if rows else None,'coverage':'Available ESPN plays only; first pre-play score is unknown, missing fields stay unknown. Play classification is descriptive. No injury or substitution is inferred.','training_status':'Postgame review only. Must join strictly prior games and validate before model use.'}

def forecast_situation_reviews(records,snapshot):
    reviews=[]
    for r in records:
        if str(r.get('event_id'))!=snapshot['event_id'] or r.get('sport','NFL')!=snapshot['sport']:continue
        if r.get('strategy')!='Original' or r.get('evidence') not in ('Personal paper record','Published before kickoff'):continue
        reviews.append({'Pick ID':r['id'],'Player':r.get('player'),'Category':r.get('category'),'Original forecast':r.get('projected_yards') if r.get('projected_yards') is not None else r.get('projected_count'),'Expected opportunities':r.get('expected_opportunities'),'Actual':r.get('actual'),'Actual opportunities':r.get('actual_opportunities'),'Result':r.get('result'),'Interpretation':'Compare workload error with game situations; association does not establish cause.'})
    return reviews
