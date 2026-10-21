"""Research workload candidates, grouped chronological benchmarks and sensitivity.
Never promote these estimates into picks or infer a DNP from a missing stat row.
"""
import math
import statistics
from collections import defaultdict
from nfl_season_prior import estimate as nfl_base,indexes as nfl_indexes,SPECS
from nba_season_prior import season_projection,season_year

WEIGHTS=(0.,.25,.5,.75,1.)

def mean(values):return statistics.mean(values) if values else None

def finite(value):return isinstance(value,(int,float)) and math.isfinite(value) and value>=0

def nfl_sample(row,market,idx,cache=None):
    season,week=row['season'],row['week'];pid,team,opp=row['player_id'],row['team'],row['opponent_team']
    f=nfl_base(pid,season,week,team,opp,market,idx,cache)
    if not f or f['coverage_gap'] or f['role_uncertain']:return None
    field,workload,_=SPECS[market]
    prior=idx[0].get((season-1,pid),[])
    current=[r for r in idx[0].get((season,pid),[]) if r['week']<week and r['team']==team]
    def share(rows):
        # Join the actual team-game for each player row; old-team IDs stay old.
        pairs=[]
        for r in rows:
            candidates=[x for x in idx[1].get((r['season'],r['team']),[]) if x['game_id']==r['game_id']]
            if len(candidates)==1 and finite(r.get(workload)) and finite(candidates[0].get(workload)):pairs.append((r[workload],candidates[0][workload]))
        total=sum(b for a,b in pairs)
        return sum(a for a,b in pairs)/total if total>0 and len(pairs)==len(rows) else None
    ps=share(prior);cs=share(current[-4:]) if current else ps
    tp=idx[1].get((season-1,team),[])
    tc=[r for r in idx[1].get((season,team),[]) if r['week']<week][-4:]
    if ps is None or cs is None or len(tp)<4 or any(not finite(r.get(workload))for r in tp+tc):return None
    tw=len(tc)/(len(tc)+4.)
    team_volume=(1-tw)*mean([r[workload]for r in tp])+tw*(mean([r[workload]for r in tc]) if tc else mean([r[workload]for r in tp]))
    expected=team_volume*((1-f['current_weight'])*ps+f['current_weight']*cs)
    if not finite(expected):return None
    recent=current[-4:] if len(current)>=4 else prior
    return dict(base=f['opportunities'],target=expected,base_stat=f['projected'],baseline_workload=mean([r[workload]for r in recent]),actual_workload=row.get(workload),actual_stat=row.get(field),cohort=f['cohort'],history=prior+current,workload_field=workload,team_volume=team_volume,player_share=(1-f['current_weight'])*ps+f['current_weight']*cs)


def nba_sample(row,history,field):
    f=season_projection(history,field,season_year(row),row['team'],row['date'])
    if not f or f['role_uncertain']:return None
    relevant=[r for r in history if r['date']<row['date'] and season_year(r) in (season_year(row)-1,season_year(row))]
    recent=sorted(relevant,key=lambda r:(r['date'],r['game']))[-5:]
    target=min(40.,max(1.,mean([r['minutes']for r in recent])))
    current=[r for r in relevant if season_year(r)==season_year(row) and r['team']==row['team']]
    baseline=mean([r['minutes']for r in (current[-8:] if len(current)>=8 else relevant if not current else current)])
    rest=appearance_context(row['date'],relevant)
    return dict(schedule_context=rest,base=f['minutes'],target=target,base_stat=f['projected'],baseline_workload=baseline,actual_workload=row.get('minutes'),actual_stat=row.get(field),cohort=f['cohort'],history=relevant,workload_field='minutes')


def evaluate(samples):
    """Choose movement weight on the earlier season, assess later games equally."""
    groups=defaultdict(lambda:{'train':[],'test':[]})
    for key,phase,game,f in samples:
        if not finite(f['actual_workload']) or not finite(f['actual_stat']) or f['base']<=0:continue
        groups[key][phase].append((game,f))
    reports={}
    for key,parts in groups.items():
        train,test=parts['train'],parts['test']
        def errors(rows,w):
            by_game=defaultdict(list)
            for game,f in rows:
                candidate=max(0.,f['base']+w*(f['target']-f['base']))
                by_game[game].append((abs(candidate-f['actual_workload']),abs(f['base']-f['actual_workload']),abs(f['baseline_workload']-f['actual_workload']),abs(f['base_stat']*candidate/f['base']-f['actual_stat']),abs(f['base_stat']-f['actual_stat'])))
            return [mean([mean([v[i]for v in values])for values in by_game.values()])for i in range(5)],len(by_game)
        weight=min(WEIGHTS,key=lambda w:errors(train,w)[0][0]) if len(train)>=50 else 0.
        values,n=errors(test,weight)
        passed=bool(weight>0 and len(train)>=50 and n>=20 and values[0]<min(values[1],values[2]) and values[3]<values[4])
        reports[key]=dict(weight=weight,training_examples=len(train),validation_games=n,candidate_workload_mae=values[0],incumbent_workload_mae=values[1],simple_workload_mae=values[2],candidate_stat_mae=values[3],incumbent_stat_mae=values[4],passed=passed,status='Stat/workload benchmark passed — probability validation still required' if passed else 'Research only — did not beat all workload and stat benchmarks')
    return reports


def validate_nfl(players,teams):
    idx=nfl_indexes(players,teams);cache={};samples=[]
    for r in players:
        if r['season']not in (2024,2025):continue
        for market,(field,workload,minimum)in SPECS.items():
            allowed=('QB',)if 'pass_'in market else ('WR','TE','RB','HB','FB')if 'reception'in market else ('RB','HB','FB')
            if r.get('position')not in allowed:continue
            f=nfl_sample(r,market,idx,cache)
            if f:samples.append(((market,f['cohort']),'train'if r['season']==2024 else 'test',r['game_id'],f))
    return evaluate(samples)


def validate_nba(logs):
    samples=[];history=defaultdict(list)
    for row in sorted(logs,key=lambda r:(r['date'],r['game'],r['player'])):
        year=season_year(row)
        if year in (2025,2026):
            for field in ('PTS','REB','AST','FG3M'):
                f=nba_sample(row,history[row['player']],field)
                if f:samples.append(((field,f['cohort']),'train'if year==2025 else 'test',row['game'],f))
        history[row['player']].append(row)
    return evaluate(samples)


def sensitivity(f):
    values=sorted(r[f['workload_field']]for r in f['history'][-12:]if finite(r.get(f['workload_field'])))
    if len(values)<4 or f['base']<=0:return []
    low=values[int(.2*(len(values)-1))];high=values[int(.8*(len(values)-1))]
    return [{'Scenario':label,'Workload':round(v,2),'Stat projection if efficiency stays unchanged':round(f['base_stat']*v/f['base'],2)}for label,v in [('Observed lower workload',low),('Base workload forecast',f['base']),('Observed higher workload',high)]]


def attach(row,f,report,absences=()):
    if not f:return row
    report=report or {};weight=report.get('weight',0.)
    candidate=max(0.,f['base']+weight*(f['target']-f['base']))
    row.update({'Workload candidate version':'workload-candidates-v1','Workload candidate baseline opportunities':f['base'],'Workload candidate baseline projection':f['base_stat'],'Workload candidate opportunities':round(candidate,2),'Workload candidate projection':round(f['base_stat']*candidate/f['base'],2),'Workload candidate status':report.get('status','Research only — insufficient chronological validation'),'Workload candidate benchmark':report,'Workload sensitivity scenarios':sensitivity(f),'Confirmed unavailable teammates':', '.join(sorted(absences))or 'None identified in the checked report','Lineup scenario limitation':'Unavailable teammates may change roles. Their opportunities are not automatically assigned to this player. Scenario rows are sensitivity examples, not picks or scenario probabilities.'})
    if f.get('schedule_context'):row['Schedule and rest context']=f['schedule_context']
    if 'team_volume'in f:row.update({'Supporting team workload':round(f['team_volume'],2),'Supporting player workload share %':round(100*f['player_share'],2)})
    return row


def appearance_context(cutoff,history):
    from datetime import date
    ordered=sorted([r for r in history if r['date']<str(cutoff)],key=lambda r:(r['date'],r['game']))
    if not ordered:return {'Status':'No prior appearance dates'}
    days=(date.fromisoformat(str(cutoff))-date.fromisoformat(ordered[-1]['date'])).days
    buckets=defaultdict(list)
    for previous,current in zip(ordered,ordered[1:]):
        gap=(date.fromisoformat(current['date'])-date.fromisoformat(previous['date'])).days
        if 0<gap<=7:buckets['At most 1 calendar day' if gap<=1 else '2–7 calendar days'].append(current['minutes'])
    return {'Days since last observed appearance':days,'Historical minutes by appearance-gap bucket':{key:{'Games':len(v),'Average minutes':round(mean(v),2) if len(v)>=4 else None}for key,v in buckets.items()},'Limitation':'Appearance gap is a rest proxy, not a verified team back-to-back or travel schedule. No automatic rest penalty is applied.'}


def saved_reviews(records):
    """Aggregate frozen prospective candidate errors; no causal claims or refits."""
    from datetime import datetime
    groups=defaultdict(list);seen=set()
    ordered=sorted(records,key=lambda r:r.get('published_utc') or '9999')
    for r in ordered:
        if r.get('strategy')not in ('Original','Analysis')or r.get('evidence')not in ('Personal paper record','Published before kickoff')or r.get('season_type')!='Regular season':continue
        try:
            if datetime.fromisoformat(r['published_utc'].replace('Z','+00:00'))>=datetime.fromisoformat(r['starts_utc'].replace('Z','+00:00')):continue
        except (ValueError,TypeError,KeyError):continue
        context=r.get('forecast_context',{})
        if context.get('Workload candidate version')!='workload-candidates-v1':continue
        key=(r.get('sport','NFL'),r.get('event_id'),r.get('player'),r.get('category'))
        if key in seen:continue
        seen.add(key)
        if r.get('result')not in ('Win','Loss','Push'):continue
        values=[r.get('actual_opportunities'),context.get('Workload candidate opportunities'),context.get('Workload candidate baseline opportunities'),r.get('actual'),context.get('Workload candidate projection'),context.get('Workload candidate baseline projection')]
        if not all(finite(v)for v in values):continue
        actual,candidate,baseline,stat,cp,bp=values
        group=(key[0],key[3],context.get('Season stage','Unknown'))
        groups[group].append((r['event_id'],abs(actual-candidate),abs(actual-baseline),abs(stat-cp),abs(stat-bp)))
    rows=[]
    for (sport,category,stage),values in sorted(groups.items()):
        games=defaultdict(list)
        for event,*errors in values:games[event].append(errors)
        averages=[mean([mean([v[i]for v in errors])for errors in games.values()])for i in range(4)]
        rows.append(dict(sport=sport,category=category,season_stage=stage,forecasts=len(values),distinct_games=len(games),candidate_workload_mae=averages[0],baseline_workload_mae=averages[1],candidate_stat_mae=averages[2],baseline_stat_mae=averages[3]))
    from nba_role_usage import saved_role_reviews
    return {'schema':1,'version':'workload-candidates-v1','groups':rows,'nba_role_groups':saved_role_reviews(records),'status':'Prospective research comparison only. No automatic promotion or causal diagnosis.'}


def write_saved_reviews(records,path='workload_reviews.json'):
    import json
    from pathlib import Path
    result=saved_reviews(records);target=Path(path)
    text=json.dumps(result,indent=2)+'\n'
    if not target.exists()or target.read_text()!=text:
        temp=target.with_suffix('.tmp');temp.write_text(text);temp.replace(target)
    return result

