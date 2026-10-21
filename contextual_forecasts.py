"""Conservative numerical workload scenarios; coefficients are experimental."""
import math
import re
import statistics
from collections import defaultdict
from datetime import date

OUT = {'out', 'injured reserve', 'ir', 'suspended', 'inactive', 'pup'}


def name(value):
    return re.sub('[^a-z0-9]', '', str(value).lower())


def nfl_availability(player, category, team, team_name, season, week, rows, roster, injuries):
    field = {'Passing yards':'attempts','Passing attempts':'attempts','Rushing yards':'carries','Rushing attempts':'carries','Receiving yards':'targets','Receptions':'targets'}.get(category)
    neutral = dict(workload_factor=1., efficiency_factor=1., reason='No quantified confirmed-absence effect')
    if not field or not roster or not injuries:
        return neutral
    current = {name(p['name']):p for p in roster}
    statuses = injuries.get('statuses', {})
    def unavailable(key):
        return str(statuses.get((team_name,key),'')).lower() in OUT or str(current.get(key,{}).get('status','')).lower() in OUT
    prior = [r for r in rows if r['season']==season and r['week']<week and r['team']==team]
    weeks=sorted({r['week'] for r in prior})[-4:]
    prior=[r for r in prior if r['week'] in weeks]
    if len(weeks)<3 or name(player) not in current:
        return neutral
    usage=defaultdict(float)
    for r in prior:
        key=name(r['player_display_name'])
        if key in current:
            value=r.get(field)
            if not isinstance(value,(int,float))or not math.isfinite(value)or value<0:
                return dict(neutral,reason='Incomplete teammate workload; no numerical redistribution inferred')
            usage[key]+=value
    active=sum(v for key,v in usage.items() if not unavailable(key))
    missing=sum(v for key,v in usage.items() if unavailable(key))
    # Only half of missing historical opportunity is redistributed. The rest
    # represents uncertain role changes or reduced team volume. No fixed boost
    # for Questionable/Doubtful players whose absence is unconfirmed.
    factor=1+min(.15,.5*missing/active) if active>0 and usage.get(name(player),0)>0 and field!='attempts' else 1.
    efficiency=1.
    if category in ('Passing yards','Receiving yards'):
        qbs=defaultdict(lambda:[0.,0.])
        for r in prior:
            if r.get('position')=='QB' and name(r['player_display_name']) in current:
                attempts,yards=r.get('attempts'),r.get('passing_yards')
                if not isinstance(attempts,(int,float))or not isinstance(yards,(int,float))or not math.isfinite(attempts+yards)or attempts<0:continue
                a=qbs[name(r['player_display_name'])];a[0]+=attempts;a[1]+=yards
        if qbs:
            primary=max(qbs,key=lambda p:qbs[p][0])
            backups=[v for key,v in qbs.items() if key!=primary and not unavailable(key) and v[0]>=30]
            if unavailable(primary) and qbs[primary][0]>=30 and len(backups)==1:
                primary_rate=qbs[primary][1]/qbs[primary][0]
                if primary_rate>0:efficiency=max(.85,min(1.1,(backups[0][1]/backups[0][0])/primary_rate))
    notes=[]
    if factor!=1:notes.append(f'Confirmed absent teammate workload: +{100*(factor-1):.1f}% allocated from recent team usage, capped at 15%')
    if efficiency!=1:notes.append(f'Observed replacement-QB efficiency ratio {efficiency:.3f}; at least 30 prior attempts per QB')
    return dict(workload_factor=factor,efficiency_factor=efficiency,reason='; '.join(notes) if notes else neutral['reason'])


def nfl_situation(team, opponent, cutoff, schedule, team_rows):
    """Predict final-margin scenarios from strictly older point margins.

    Final-margin states approximate broad game context, not time spent leading.
    The small workload adjustment must be evaluated prospectively.
    """
    prior=[]
    for game in schedule:
        if game.get('game_type')!='REG' or str(game.get('gameday',''))>=str(cutoff):continue
        try:
            home,away=float(game['home_score']),float(game['away_score'])
            day=date.fromisoformat(game['gameday'])
            if not math.isfinite(home+away) or (date.fromisoformat(str(cutoff))-day).days>400:continue
        except (KeyError,TypeError,ValueError):continue
        prior.append((game,home-away))
    prior.sort(key=lambda item:(item[0]['gameday'],str(item[0].get('game_id',''))))
    def history(code):
        return [(g,m if g['home_team']==code else -m) for g,m in prior if code in (g['home_team'],g['away_team'])][-12:]
    own,opp=history(team),history(opponent)
    if len(own)<6 or len(opp)<6:return None
    expected=(statistics.mean(m for g,m in own)-statistics.mean(m for g,m in opp))/2
    # Empirical margin variation around the current expected margin.
    centered=[m-statistics.mean(v for g,v in own) for g,m in own]+[-m+statistics.mean(v for g,v in opp) for g,m in opp]
    counts=[sum(expected+v>=8 for v in centered),sum(-8<expected+v<8 for v in centered),sum(expected+v<=-8 for v in centered)]
    probabilities=[(n+2)/(len(centered)+6) for n in counts]
    game_margins={g['game_id']:m for g,m in own}
    scenarios=defaultdict(list)
    for r in team_rows:
        if r.get('team')!=team or r.get('game_id') not in game_margins:continue
        margin=game_margins[r['game_id']]
        label=0 if margin>=8 else 2 if margin<=-8 else 1
        attempts,carries=r.get('attempts'),r.get('carries')
        if attempts is not None and carries is not None:scenarios[label].append((attempts,carries))
    total=[v for bucket in scenarios.values() for v in bucket]
    if len(total)<6:return None
    factors=[]
    for index in (0,1):
        overall=statistics.mean(v[index] for v in total)
        means=[(sum(v[index] for v in scenarios[k])+4*overall)/(len(scenarios[k])+4) for k in range(3)]
        weighted=sum(p*m for p,m in zip(probabilities,means))
        factors.append(max(.9,min(1.1,weighted/overall)) if overall>0 else 1.)
    return dict(passing_factor=factors[0],rushing_factor=factors[1],probabilities={'Win by 8+':probabilities[0],'Within 7':probabilities[1],'Lose by 8+':probabilities[2]},expected_margin=expected,prior_games=len(total),method='Prior-margin empirical scenarios; not live score-state probabilities')

