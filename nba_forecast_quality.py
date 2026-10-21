"""Observed NBA minutes sensitivity and empirical forecast bands, not new picks."""
import math
import statistics


def quantile(values, fraction):
    values=sorted(v for v in values if isinstance(v,(int,float)) and math.isfinite(v))
    if not values:return None
    index=(len(values)-1)*fraction
    low=int(index);high=min(len(values)-1,low+1)
    return values[low]+(values[high]-values[low])*(index-low)


def stat_band(projected, errors):
    errors=[v for v in errors if isinstance(v,(int,float)) and math.isfinite(v)]
    if len(errors)<50:return None
    scale=max(1.,math.sqrt(max(0.,projected)))
    return (max(0.,projected+scale*quantile(errors,.1)),max(0.,projected+scale*quantile(errors,.9)))


def attach_quality(row, history, cutoff, team, projected, minutes, errors):
    """Use strictly earlier observed appearances; missing minutes are not zero."""
    from nba_season_prior import season_year
    target=season_year({'date':str(cutoff)})
    earlier=sorted((r for r in history if r['date']<str(cutoff)),key=lambda r:(r['date'],r['game']))
    season=[r for r in earlier if season_year(r)==target]
    other=[r['date'] for r in season if r['team']!=team]
    last_other=max(other,default='')
    current=[r for r in season if r['team']==team and r['date']>last_other]
    # No prior-team minutes masquerade as a verified current-team role.
    relevant=current or [r for r in earlier if season_year(r)==target-1 and r['team']==team]
    sample=[r['minutes'] for r in relevant[-12:] if isinstance(r.get('minutes'),(int,float)) and math.isfinite(r['minutes']) and r['minutes']>0]
    row['Minutes sample games']=len(sample)
    row['Minutes sample basis']='Current-team current stint' if current else 'Prior-season same-team appearances'
    if len(sample)>=4 and minutes>0:
        low,high=quantile(sample,.1),quantile(sample,.9)
        average=statistics.mean(sample)
        volatile=high-low>=12 or statistics.pstdev(sample)/average>=.25
        row.update({'Observed minutes low':round(low,1),'Observed minutes high':round(high,1),'Minutes risk':'Variable observed minutes' if volatile else 'Steadier observed minutes'})
        lo,hi=projected*low/minutes,projected*high/minutes
        try:line=float(row.get('Line'))
        except (ValueError,TypeError):line=None
        crosses=line is not None and math.isfinite(line) and lo<=line<=hi
        row['Minutes sensitivity']='Observed minutes scenarios cross the line' if crosses else 'Observed minutes scenarios stay on one side'
        row['Minutes sensitivity scenarios']=[{'Scenario':label,'Minutes':round(value,1),'Stat if production per minute stays unchanged':round(projected*value/minutes,2)} for label,value in [('Observed lower minutes',low),('Base minutes forecast',minutes),('Observed higher minutes',high)]]
    else:
        row['Minutes risk']='Insufficient current-role minutes evidence'
        row['Minutes sensitivity']='Unavailable; missing appearances are not assigned zero minutes'
    band=stat_band(projected,errors)
    if band:
        row.update({'Stat range low':round(band[0],2),'Stat range high':round(band[1],2),'Stat range method':'Earlier season-stage residual 10th–90th percentiles; empirical band, not guaranteed 80% coverage','Range calibration examples':len(errors)})
        row.update({'Historical error range low':row['Stat range low'],'Historical error range high':row['Stat range high'],'Range method':row['Stat range method']})
    return row


def settled_quality(records):
    """Game-weighted prospective diagnostics; never refit or infer missing stats."""
    from collections import defaultdict
    from datetime import datetime
    groups=defaultdict(list);seen=set()
    def finite(v):return isinstance(v,(int,float)) and math.isfinite(v)
    for r in sorted(records,key=lambda r:r.get('published_utc','9999')):
        if r.get('sport')!='NBA' or r.get('strategy')!='Original' or r.get('evidence')not in ('Published before kickoff','Personal paper record') or r.get('season_type')!='Regular season':continue
        try:
            if datetime.fromisoformat(r['published_utc'].replace('Z','+00:00'))>=datetime.fromisoformat(r['starts_utc'].replace('Z','+00:00')):continue
        except (ValueError,TypeError,KeyError):continue
        key=(r.get('event_id'),r.get('player'),r.get('category'))
        if key in seen:continue
        seen.add(key)
        if r.get('result')not in ('Win','Loss','Push'):continue
        c=r.get('forecast_context') or {}
        if not c.get('Minutes risk'):continue
        actual,projection=r.get('actual'),r.get('projected_count')
        minutes,expected=r.get('actual_opportunities'),r.get('expected_opportunities')
        low,high=c.get('Historical error range low'),c.get('Historical error range high')
        groups[r['category']].append((r['event_id'],actual-projection if finite(actual) and finite(projection) else None,minutes-expected if finite(minutes) and finite(expected) else None,low<=actual<=high if all(finite(v)for v in (actual,low,high)) else None))
    result=[]
    for category,values in sorted(groups.items()):
        def metric(index,absolute=False):
            games=defaultdict(list)
            for row in values:
                if row[index] is not None:games[row[0]].append(abs(row[index]) if absolute else row[index])
            return statistics.mean(statistics.mean(v)for v in games.values()) if games else None
        coverage=metric(3)
        result.append({'Category':category,'Distinct games':len({v[0]for v in values}),'Stat comparisons':sum(v[1]is not None for v in values),'Stat average absolute error':metric(1,True),'Average actual minus forecast':metric(1),'Minutes comparisons':sum(v[2]is not None for v in values),'Minutes average absolute error':metric(2,True),'Range comparisons':sum(v[3]is not None for v in values),'Measured range coverage %':100*coverage if coverage is not None else None})
    return result
