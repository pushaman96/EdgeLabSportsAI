"""NFL season-prior candidate: observed usage only, chronological validation."""
import math
import statistics
from collections import defaultdict

VERSION='NFL season-prior workload v1 / 2024 calibration / 2025 development'
SPECS={
 'player_pass_yds':('passing_yards','attempts',20),
 'player_rush_yds':('rushing_yards','carries',8),
 'player_reception_yds':('receiving_yards','targets',3),
 'player_receptions':('receptions','targets',3),
 'player_pass_attempts':('attempts','attempts',20),
 'player_rush_attempts':('carries','carries',8),
 'player_pass_completions':('completions','attempts',20),
 'player_pass_tds':('passing_tds','attempts',20),
 'player_pass_interceptions':('passing_interceptions','attempts',20),
}

def average(rows,field):
    values=[r.get(field) for r in rows]
    if not values or any(not isinstance(v,(int,float)) or not math.isfinite(v) or v<0 for v in values):return None
    return statistics.mean(values)


def estimate(pid,season,week,team,opponent,market,idx,league_cache=None):
    if market not in SPECS:return None
    pi,ti,defense=idx;stat,workload,minimum=SPECS[market]
    prior=list(pi.get((season-1,pid),[]))
    current=[r for r in pi.get((season,pid),[]) if r['week']<week and r['team']==team]
    prior=sorted(prior,key=lambda r:r['week']);current=sorted(current,key=lambda r:r['week'])
    # End a current-team stint after a later appearance for another team.
    away=[r['week'] for r in pi.get((season,pid),[]) if r['week']<week and r['team']!=team]
    if away:current=[r for r in current if r['week']>max(away)]
    if len(prior)<4:return None
    team_current=sorted([r for r in ti.get((season,team),[]) if r['week']<week],key=lambda r:r['week'])
    expected={r['game_id'] for r in team_current[-4:]}
    observed={r['game_id'] for r in current}
    gap=bool(expected-observed)
    prior_work=average(prior,workload);prior_stat=average(prior,stat)
    if prior_work is None or prior_stat is None or prior_work<minimum:return None
    recent=current[-4:];weight=len(current)/(len(current)+4.)
    cw=average(recent,workload) if recent else prior_work
    cs=average(recent,stat) if recent else prior_stat
    if cw is None or cs is None or cw<=0:return None
    volume=(1-weight)*prior_work+weight*cw
    rate=(1-weight)*(prior_stat/prior_work)+weight*(cs/cw)
    # Defense begins with last season too. Missing coverage is explicitly neutral.
    previous_opp=list(defense.get((season-1,opponent),[]))
    current_opp=[r for r in defense.get((season,opponent),[]) if r['week']<week][-4:]
    prior_opp=average(previous_opp,stat);now_opp=average(current_opp,stat)
    cache=league_cache if league_cache is not None else {}
    def league_average(year,limit):
        key=(year,limit,stat)
        if key not in cache:cache[key]=average([r for (y,code),values in ti.items() if y==year for r in values if r['week']<limit],stat)
        return cache[key]
    lp=league_average(season-1,99);ln=league_average(season,week)
    defense_weight=len(current_opp)/(len(current_opp)+4.)
    ratio=1.;defense_status='Historical opponent comparison unavailable — neutral effect'
    if prior_opp is not None and lp and len(previous_opp)>=4:
        opponent_mean=(1-defense_weight)*prior_opp+defense_weight*(now_opp if now_opp is not None else prior_opp)
        league_mean=(1-defense_weight)*lp+defense_weight*(ln if ln is not None else lp)
        ratio=max(.75,min(1.25,opponent_mean/league_mean));defense_status='Last-season opponent production allowed blended with current-season games'
    projected=volume*rate*(1+.2*(ratio-1))
    changed=prior[-1]['team']!=team or bool(away)
    uncertain=changed and len(current)<4
    baseline=prior_stat if len(current)<4 else cs
    return dict(projected=projected,opportunities=volume,baseline=baseline,prior_games=len(prior),current_games=len(current),current_weight=weight,role_uncertain=uncertain,coverage_gap=gap,defense_status=defense_status,uncertainty=math.sqrt(1+.5*(1-weight)+(.5 if uncertain else 0)),cohort='Early season (0–3 appearances)' if len(current)<4 else 'Established season',latest_season=season if current else season-1,latest_week=current[-1]['week'] if current else prior[-1]['week'])


def indexes(players,teams):
    pi,ti,defense=defaultdict(list),defaultdict(list),defaultdict(list)
    for r in players:pi[r['season'],r['player_id']].append(r)
    for r in teams:ti[r['season'],r['team']].append(r);defense[r['season'],r['opponent_team']].append(r)
    return pi,ti,defense


def error_scale(projected):return max(1.,math.sqrt(projected))


def validate(players,teams):
    idx=indexes(players,teams);league_cache={};errors=defaultdict(list);samples=defaultdict(lambda:defaultdict(list))
    for r in players:
        if r['season'] not in (2024,2025):continue
        for market,(stat,_,_) in SPECS.items():
            if average([r],stat) is None:continue
            allowed=('QB',) if 'pass_' in market else ('WR','TE','RB','HB','FB') if market in ('player_receptions','player_reception_yds') else ('RB','HB','FB')
            if r.get('position') not in allowed:continue
            f=estimate(r['player_id'],r['season'],r['week'],r['team'],r['opponent_team'],market,idx,league_cache)
            if not f or f['coverage_gap'] or f['role_uncertain']:continue
            key=(market,f['cohort'])
            if r['season']==2024:errors[key].append((r[stat]-f['projected'])/error_scale(f['projected'])/f['uncertainty'])
            else:samples[key][r['game_id']].append((abs(r[stat]-f['projected']),abs(r[stat]-f['baseline']),(r[stat]-f['projected'])/error_scale(f['projected'])/f['uncertainty'],r[stat]-f['projected']))
    reports={}
    for market in SPECS:
        for cohort in ('Early season (0–3 appearances)','Established season'):
            key=(market,cohort);groups=samples[key];cal=errors[key]
            fm=statistics.mean(statistics.mean(x[0] for x in v)for v in groups.values()) if groups else None
            bm=statistics.mean(statistics.mean(x[1] for x in v)for v in groups.values()) if groups else None
            ordered=sorted(cal)
            low=ordered[int(.1*(len(ordered)-1))]if len(ordered)>=50 else None
            high=ordered[math.ceil(.9*(len(ordered)-1))]if len(ordered)>=50 else None
            coverage=statistics.mean(statistics.mean(low<=x[2]<=high for x in values)for values in groups.values())if groups and low is not None else None
            bias=statistics.mean(statistics.mean(x[3]for x in values)for values in groups.values())if groups else None
            reports[key]=dict(validation_games=len(groups),calibration_examples=len(cal),forecast_mae=fm,baseline_mae=bm,passed=bool(len(groups)>=20 and len(cal)>=50 and fm<bm),residuals=ordered,training_season=2024,validation_season=2025,empirical_band_validation_coverage=coverage,mean_actual_minus_forecast=bias)
    from nfl_opportunity import validate as validate_opportunity
    candidates=validate_opportunity(players,teams)
    for key,report in reports.items():report['opportunity_report']=candidates.get(key,{'passed':False,'residuals':[]})
    return reports


def evaluated_row(row,forecast,report):
    result=dict(row);projection=forecast['projected'];count='yards' not in row['Category'].lower()
    result['Model']=VERSION;result['Base model']=VERSION
    result['Projection (count)' if count else 'Projection (yards)']=round(projection,2)
    result.update({'Expected opportunities':round(forecast['opportunities'],2),'Last-season games':forecast['prior_games'],'Current-season appearances':forecast['current_games'],'Current-season weight %':round(100*forecast['current_weight'],1),'Season stage':forecast['cohort'],'History source':'Completed nflverse regular-season weekly statistics','Role uncertainty':'New-team role unverified' if forecast['role_uncertain'] else 'Historical role assumption; lineup changes may differ','Uncertainty multiplier':round(forecast['uncertainty'],3),'Validation':{k:v for k,v in report.items()if k not in ('residuals','opportunity_report')},'Opportunity type':'Passing attempts' if 'Passing' in row['Category'] else 'Carries' if 'Rushing' in row['Category'] else 'Targets'})
    residuals=report.get('residuals',[])
    reason='Last-season starting estimate blended with current-season usage; '+forecast['defense_status']+'. '
    if len(residuals)<20:result['Reason']=reason+'Insufficient earlier calibration; stat projection only';return result
    over=over_probability(projection,float(row['Line']),report,forecast['uncertainty'])
    p=1-over if row['Selection']=='Under' else over
    odds=float(row['Odds']);be=100/(odds+100)if odds>0 else abs(odds)/(abs(odds)+100)
    result.update({'Estimated win %':round(100*p,1),'Raw estimated win %':round(100*p,1),'Break-even %':round(100*be,1),'Model edge (pp)':round(100*(p-be),1)})
    if forecast['coverage_gap']:reason+='Recent player-stat coverage gap; missing games are not zero or DNP.'
    elif forecast['role_uncertain']:reason+='New-team role needs four observed current-team appearances.'
    elif not report.get('passed'):reason+='Season-stage model has not beaten its baseline on later games; research projection only.'
    elif p<=.5:reason+='Selected outcome is not more likely than its alternative.'
    else:result['Decision']='Watch — experimental';reason+='Season-stage stat baseline passed; probabilities and price profitability are unverified. Teammate injury effects are not numerically included in this candidate.'
    result['Reason']=reason
    return result


def over_probability(projected,line,report,uncertainty=1.):
    residuals=report.get('residuals',[])
    if len(residuals)<20:return None
    if 'temperature'in report:
        from forecast_benchmark import probability
        return probability(projected,line,residuals,report['temperature'])
    threshold=(line-projected)/error_scale(projected)/uncertainty
    return max(.05,min(.95,.5+.8*((1+sum(e>threshold for e in residuals))/(len(residuals)+2)-.5)))


