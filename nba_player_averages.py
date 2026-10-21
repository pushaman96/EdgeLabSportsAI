"""Pregame observed NBA averages and attempt-weighted shooting percentages."""
import math
import statistics
from nba_season_prior import season_year


def finite(value):
    return isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value) and value>=0


def average(values):return statistics.mean(values)if values else None


def summarize(rows,field,line=None):
    values=[r[field]for r in rows if finite(r.get(field))]
    minutes=[r['minutes']for r in rows if finite(r.get('minutes'))and r['minutes']>0]
    paired=[r for r in rows if finite(r.get(field))and finite(r.get('minutes'))and r['minutes']>0]
    result={'Games':len(rows),'Stat sample games':len(values),'Average':average(values),'Median':statistics.median(values)if values else None,'Stat standard deviation':statistics.pstdev(values)if len(values)>=2 else None,'Minutes average':average(minutes),'Minutes sample games':len(minutes),'Stat per minute':sum(r[field]for r in paired)/sum(r['minutes']for r in paired)if paired else None}
    for label,made,attempted in (('FG','FGM','FGA'),('3PT','FG3M','FG3A'),('FT','FTM','FTA')):
        sample=[r for r in rows if finite(r.get(made))and finite(r.get(attempted))and r[made]<=r[attempted]]
        total_attempts=sum(r[attempted]for r in sample)
        result.update({label+' shooting games':len(sample),label+' makes/game':average([r[made]for r in sample]),label+' attempts/game':average([r[attempted]for r in sample]),label+' %':100*sum(r[made]for r in sample)/total_attempts if total_attempts>0 else None})
    if finite(line):
        over=sum(v>line for v in values);under=sum(v<line for v in values);push=sum(v==line for v in values)
        result.update({'Compared line':line,'Historical overs':over,'Historical unders':under,'Historical pushes':push,'Historical over % (excluding pushes)':100*over/(over+under)if over+under else None})
    return result


def player_averages(history,field,year,team,cutoff,line=None):
    # One observed game per player. Preseason and future/same-day records are
    # excluded upstream and here; no blank statistic is converted to zero.
    before=[];seen=set()
    for row in sorted(history,key=lambda r:(r['date'],r['game'])):
        if row['date']>=str(cutoff)or season_year(row)not in (year-1,year):continue
        if row.get('season_type',2)!=2:continue
        identity=(row.get('player'),row['game'])
        if identity in seen:continue
        seen.add(identity);before.append(row)
    prior=[r for r in before if season_year(r)==year-1]
    current=[r for r in before if season_year(r)==year]
    last_other=max((r['date']for r in current if r['team']!=team),default='')
    stint=[r for r in current if r['team']==team and r['date']>last_other]
    groups=[('Last season — all teams',prior),('This season — all teams',current),('Current-team current stint',stint),('Last 5 appearances',before[-5:]),('Last 10 appearances',before[-10:])]
    result=[]
    for label,rows in groups:
        result.append({'Sample':label,'Includes prior season':any(season_year(r)==year-1 for r in rows),'Includes prior team':any(r['team']!=team for r in rows),'First game date':min((r['date']for r in rows),default=None),'Latest game date':max((r['date']for r in rows),default=None),**summarize(rows,field,line)})
    return result


def attach_averages(row,history,field,year,team,cutoff,current_history_verified=True):
    try:line=float(row['Line'])
    except (ValueError,TypeError,KeyError):line=None
    profile=player_averages(history,field,year,team,cutoff,line)
    if not current_history_verified:
        for sample in profile:
            sample['Coverage']='Current-season history unavailable; sample may omit new appearances'
            if sample['Sample']in ('This season — all teams','Current-team current stint'):
                for field_name in ('Games','Stat sample games','Minutes sample games'):sample[field_name]=None
    row['Player averages']=profile
    row['Player averages method']='Observed regular-season appearances before game date. Last-5/10 may span seasons or teams as labeled. Shooting percentages use total paired makes/attempts. Historical line results are descriptive, not forecast probabilities.'+(' Current-season history could not be verified; no zero-game or zero-stat assumption is made.'if not current_history_verified else'')
    lookup={r['Sample']:r for r in profile}
    row.update({'Last-season average':lookup['Last season — all teams']['Average'],'This-season average':lookup['This season — all teams']['Average'],'Last-5 average':lookup['Last 5 appearances']['Average'],'Last-10 average':lookup['Last 10 appearances']['Average']})
    return row
