"""Conditional starter/bench usage evidence and pregame role-mismatch checks.

Role scenarios are research estimates, never silently applied to probabilities.
"""
import statistics
from nba_game_context import athlete_rows,completed_game,key,utc

VERSION='nba-role-usage-v1'


def mean(values):return statistics.mean(values)if values else None


def role_usage(summaries,cutoff,team_id,player,current_starter,base_minutes,base_projection,field):
    samples=[];seen=set()
    for data in summaries:
        if not completed_game(data,cutoff):continue
        eid=str(data['header']['id'])
        if eid in seen:continue
        seen.add(eid)
        target=athlete_rows(data).get((str(team_id),key(player)))
        if not target or target['didNotPlay']is not False or target['starter']is None or not target.get('minutes'):continue
        samples.append((utc(data['header']['competitions'][0]['date']),target))
    samples=[r for _,r in sorted(samples,key=lambda item:item[0])[-12:]]
    groups={True:[r for r in samples if r['starter']is True],False:[r for r in samples if r['starter']is False]}
    def group(rows):
        values=[r[field]for r in rows if r.get(field)is not None]
        result={'Games':len(rows),'Average minutes':mean([r['minutes']for r in rows]),'Median minutes':statistics.median(r['minutes']for r in rows)if rows else None,'Stat average':mean(values),'Stat sample games':len(values)}
        for name in ('FGA','FG3A','FTA'):
            valid=[r for r in rows if r.get(name)is not None]
            result[name+' average']=mean([r[name]for r in valid])
            result[name+' sample games']=len(valid)
            result[name+' per minute']=sum(r[name]for r in valid)/sum(r['minutes']for r in valid)if valid else None
        return result
    report={'Version':VERSION,'Starter history':group(groups[True]),'Bench history':group(groups[False]),'Reported current starter':current_starter if isinstance(current_starter,bool)else None,'Base minutes':base_minutes,'Base stat forecast':base_projection,'Role sample games':0,'Candidate minutes':None,'Candidate stat':None,'Material role disagreement':False,'New role without matching history':False,'Status':'Current starting/bench role unconfirmed; no role-specific minutes assumed','Method':'Same-team explicit historical starter/bench flags, up to 12 observed regular-season appearances. Matching-role median minutes; candidate stat holds base production per minute unchanged. Role scenarios are not validated forecasts or separate picks.'}
    if not isinstance(current_starter,bool):return report
    matching=groups[current_starter];opposite=groups[not current_starter]
    report['Role sample games']=len(matching)
    report['New role without matching history']=len(matching)<3 and len(opposite)>=3
    if len(matching)<3:
        report['Status']='Reported role differs from observed history; need more same-role evidence'if report['New role without matching history']else'Insufficient same-role history (need 3 observations)'
        return report
    minutes=min(40.,max(1.,statistics.median(r['minutes']for r in matching)))
    report.update({'Candidate minutes':minutes,'Candidate stat':base_projection*minutes/base_minutes if base_minutes>0 else None,'Material role disagreement':abs(minutes-base_minutes)>=max(4.,.15*base_minutes),'Status':'Conditional role scenario only; not applied to the projection or probability'})
    for name in ('FGA','FG3A','FTA'):
        value=report['Starter history'if current_starter else'Bench history'][name+' per minute']
        report['Candidate '+name]=minutes*value if value is not None else None
    return report


def attach_role_usage(row,context,cutoff,team_id,player,minutes,projection,field):
    starter=row.get('Starting lineup check',{}).get('Starter')
    report=role_usage((context or {}).get('history',[]),cutoff,team_id,player,starter,minutes,projection,field)
    row['NBA role usage']=report
    row['NBA role usage version']=VERSION
    row['NBA role review required']=report['New role without matching history']
    candidate=report.get('Candidate stat');line=row.get('Line')
    try:line=float(line)
    except (TypeError,ValueError):line=None
    if report['Material role disagreement']and candidate is not None and line is not None:
        conflict=candidate>=line if row.get('Selection')=='Under'else candidate<=line
        row['NBA role review required']=row['NBA role review required']or conflict
    row['NBA role status']='Reported role and historical minutes conflict with the selection; verify workload before use'if row['NBA role review required']else report['Status']
    return row


def saved_role_reviews(records):
    """Compare frozen pregame role scenarios without changing old picks."""
    import math
    from collections import defaultdict
    groups=defaultdict(list);seen=set()
    for r in sorted(records,key=lambda r:r.get('published_utc')or'9999'):
        if r.get('sport')!='NBA'or r.get('strategy')not in ('Original','Analysis')or r.get('evidence')not in ('Published before kickoff','Personal paper record')or r.get('season_type')!='Regular season':continue
        try:
            if utc(r['published_utc'])>=utc(r['starts_utc']):continue
        except (KeyError,ValueError,TypeError):continue
        report=(r.get('forecast_context')or{}).get('NBA role usage')or{}
        if report.get('Version')!=VERSION:continue
        identity=(r.get('event_id'),r.get('player'),r.get('category'))
        if identity in seen:continue
        seen.add(identity)
        if r.get('result')not in ('Win','Loss','Push'):continue
        values=[r.get('actual_opportunities'),report.get('Candidate minutes'),report.get('Base minutes'),r.get('actual'),report.get('Candidate stat'),report.get('Base stat forecast')]
        if not all(isinstance(v,(int,float))and math.isfinite(v)and v>=0 for v in values):continue
        actual,cm,bm,stat,cp,bp=values
        groups[r['category'],report.get('Reported current starter')].append((r['event_id'],abs(actual-cm),abs(actual-bm),abs(stat-cp),abs(stat-bp)))
    output=[]
    for (category,starter),rows in sorted(groups.items()):
        games=defaultdict(list)
        for eid,*errors in rows:games[eid].append(errors)
        errors=[mean([mean([v[i]for v in values])for values in games.values()])for i in range(4)]
        output.append({'sport':'NBA','category':category,'reported_role':'Starter'if starter else'Bench','forecasts':len(rows),'distinct_games':len(games),'role_minutes_mae':errors[0],'base_minutes_mae':errors[1],'role_stat_mae':errors[2],'base_stat_mae':errors[3],'status':'Prospective comparison only; no automatic promotion'})
    return output
