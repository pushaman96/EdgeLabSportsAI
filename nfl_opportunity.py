"""NFL team-volume/player-share candidate; earlier calibration and later tests."""
import math
from collections import defaultdict
from nfl_season_prior import SPECS,estimate,indexes,average

VERSION='NFL season-prior workload v2 / team-share matchup'


def candidate(pid,season,week,team,opponent,market,idx,cache=None):
    from workload_candidates import nfl_sample
    base=estimate(pid,season,week,team,opponent,market,idx,cache)
    f=nfl_sample(dict(player_id=pid,season=season,week=week,team=team,opponent_team=opponent),market,idx,cache)
    if not base or not f or not 0<=f['player_share']<=1:return None
    stat,workload,_=SPECS[market]
    old=idx[2].get((season-1,opponent),[])
    current=[r for r in idx[2].get((season,opponent),[])if r['week']<week]
    expected=f['base']+.5*(f['target']-f['base'])
    prior_allowed=average(old,workload)
    own_prior=idx[1].get((season-1,team),[])
    own_current=[r for r in idx[1].get((season,team),[])if r['week']<week]
    lookup=cache if cache is not None else {}
    def league(year,limit):
        key=('opportunity_league',year,limit,workload)
        if key not in lookup:lookup[key]=average([r for (s,t),rows in idx[1].items()if s==year for r in rows if r['week']<limit],workload)
        return lookup[key]
    prior_league=league(season-1,99);current_league=league(season,week)
    weight=len(current)/(len(current)+4.)
    now_allowed=average(current[-4:],workload)
    ratio=None
    if len(old)>=4 and prior_allowed is not None and prior_league:
        allowed=(1-weight)*prior_allowed+weight*(now_allowed if now_allowed is not None else prior_allowed)
        reference=(1-weight)*prior_league+weight*(current_league or prior_league)
        ratio=allowed/reference
        expected*=1+.1*(max(.75,min(1.25,ratio))-1)
    expected=max(.8*base['opportunities'],min(1.2*base['opportunities'],expected))
    result=dict(base,projected=base['projected']*expected/base['opportunities'],opportunities=expected)
    def tendency(rows):
        rows=[r for r in rows if average([r],'attempts')is not None and average([r],'carries')is not None]
        total=sum(r['attempts']+r['carries']for r in rows)
        return {'games':len(rows),'pass_attempt_share':sum(r['attempts']for r in rows)/total if total else None}
    result['homework']={'team_volume':f['team_volume'],'player_share':f['player_share'],'opponent_workload_ratio':ratio,
        'prior_team_tendency':tendency(own_prior),'current_team_tendency':tendency(own_current[-4:]),
        'method':'Team workload × observed player share blended with incumbent volume; bounded opponent workload adjustment. Existing efficiency/defense model retained. Attempts + carries exclude sacks; observed tendencies do not identify a coaching system.'}
    return result


def validate(players,teams):
    from forecast_benchmark import validate as benchmark
    idx=indexes(players,teams);cache={};samples=defaultdict(list)
    for r in players:
        if r['season']not in (2024,2025):continue
        for market,(stat,workload,_)in SPECS.items():
            allowed=('QB',)if 'pass_'in market else ('WR','TE','RB','HB','FB')if 'reception'in market else ('RB','HB','FB')
            if r.get('position')not in allowed or average([r],stat)is None or average([r],workload)is None:continue
            base=estimate(r['player_id'],r['season'],r['week'],r['team'],r['opponent_team'],market,idx,cache)
            f=candidate(r['player_id'],r['season'],r['week'],r['team'],r['opponent_team'],market,idx,cache)
            if not base or not f:continue
            samples[market,base['cohort']].append(dict(date=f"{r['season']}-{r['week']:02d}",season=r['season'],game=r['game_id'],
                candidate=f['projected'],base=base['projected'],base_uncertainty=base['uncertainty'],baseline=base['baseline'],actual=r[stat],
                workload=f['opportunities'],base_workload=base['opportunities'],actual_workload=r[workload]))
    return {key:benchmark(rows)for key,rows in samples.items()}
