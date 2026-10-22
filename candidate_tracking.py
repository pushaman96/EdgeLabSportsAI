"""Compare candidate predictions actually frozen before outcomes, equally by game."""
import statistics
from collections import defaultdict
from online_learning import eligible,number
from datetime import datetime,timezone


def summary(records,now=None):
    now=now or datetime.now(timezone.utc);groups=defaultdict(lambda:defaultdict(list));seen=set()
    for r in sorted(records,key=lambda r:(str(r.get('published_utc')or'9999'),str(r.get('id')or''))):
        if not eligible(r,now):continue
        comparisons=(r.get('forecast_context')or{}).get('Research model comparison')or[]
        for c in comparisons:
            identity=(r.get('sport','NFL'),r['event_id'],r['player'],r['category'],c.get('version'))
            if identity in seen:continue
            if c.get('line')!=r.get('line')or c.get('selection')!=r.get('direction'):continue
            seen.add(identity)
            actual=number(r.get('actual'));base=number(c.get('incumbent_projection'));candidate=number(c.get('candidate_projection'))
            bp=number(c.get('incumbent_probability'));cp=number(c.get('candidate_probability'))
            mae=abs(candidate-actual)-abs(base-actual)if all(v is not None for v in (actual,base,candidate))else None
            brier=(cp-int(r['result']=='Win'))**2-(bp-int(r['result']=='Win'))**2 if r['result']in ('Win','Loss')and bp is not None and cp is not None and 0<bp<1 and 0<cp<1 else None
            groups[r.get('sport','NFL'),r['category'],c.get('version')][r['event_id']].append((mae,brier))
    output=[]
    for (sport,category,version),games in sorted(groups.items()):
        def metric(index):
            measured=[statistics.mean(v[index]for v in rows if v[index]is not None)for rows in games.values()if any(v[index]is not None for v in rows)]
            return (statistics.mean(measured),len(measured))if measured else(None,0)
        stat,stat_games=metric(0);brier,prob_games=metric(1)
        output.append({'sport':sport,'Category':category,'Candidate':version,'Distinct games':len(games),
                       'Stat comparison games':stat_games,'Candidate minus incumbent MAE':stat,
                       'Probability comparison games':prob_games,'Candidate minus incumbent Brier':brier,
                       'Status':'Frozen prospective comparison; negative differences favor candidate, not proof of profitability'})
    return output
