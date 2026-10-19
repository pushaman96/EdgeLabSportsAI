"""Chronological NFL count forecasts and receiver workload explanations.

Completions and passing TDs use a mixture of attempt counts and beta-binomial
conversion uncertainty. Benchmarks are fixed pregame thresholds, not past odds.
"""
import math
import statistics
from collections import Counter, defaultdict

MARKETS = {'player_pass_completions':('Passing completions','completions'), 'player_pass_tds':('Passing touchdowns','passing_tds')}
VERSION = 'NFL attempts-conversion counts v1'


def valid(row, field):
    a=row.get('attempts');v=row.get(field)
    return isinstance(a,(float,int)) and isinstance(v,(float,int)) and math.isfinite(a+v) and a>0 and 0<=v<=a


def beta_binomial(n, rate, concentration):
    if not isinstance(n,int) or not 0<=n<=100 or not 0<rate<1 or concentration<=0:
        raise ValueError('Invalid count distribution parameters')
    a,b=rate*concentration,(1-rate)*concentration
    def lbeta(x,y):return math.lgamma(x)+math.lgamma(y)-math.lgamma(x+y)
    values=[math.exp(math.lgamma(n+1)-math.lgamma(k+1)-math.lgamma(n-k+1)+lbeta(k+a,n-k+b)-lbeta(a,b)) for k in range(n+1)]
    total=sum(values)
    return [p/total for p in values]


def distribution(attempts, rate, concentration):
    weights=Counter(attempts);pmf=[0.]*(max(weights)+1)
    for n,weight in weights.items():
        for k,p in enumerate(beta_binomial(n,rate,concentration)):
            pmf[k]+=p*weight/len(attempts)
    return pmf


def tail(pmf,line):
    if not math.isfinite(float(line)):raise ValueError('Invalid threshold')
    return sum(p for count,p in enumerate(pmf) if count>line)


def quantile(pmf,level):
    cumulative=0.
    for n,p in enumerate(pmf):
        cumulative+=p
        if cumulative>=level:return n
    return len(pmf)-1


def estimate(player, season, week, team, opponent, idx, field):
    if field not in ('completions','passing_tds'):raise ValueError('Unsupported count field')
    history=sorted([r for (year,pid),values in idx[0].items() if pid==player and season-1<=year<=season for r in values if (r['season'],r['week'])<(season,week) and r.get('position')=='QB' and (r.get('attempts') or 0)>=15 and valid(r,field)],key=lambda r:(r['season'],r['week']))[-12:]
    current=[r for r in history if r['season']==season and r['team']==team]
    own=[r for r in idx[1].get((season,team),[]) if r['week']<week][-4:]
    if len(history)<8 or len(current)<4 or len(own)<4:
        return None,'Needs 8 prior QB starts and the latest 4 current-team games'
    if not {r['game_id'] for r in own}.issubset({r['game_id'] for r in current}):
        return None,'Recent QB/team coverage gap; missing games are not treated as zero'
    league=[r for (year,_),values in idx[1].items() if year==season for r in values if r['week']<week and valid(r,field)]
    allowed=[r for r in idx[2].get((season,opponent),[]) if r['week']<week and valid(r,field)][-8:]
    if len(league)<40 or len(allowed)<4:return None,'League/opponent conversion-rate history is incomplete'
    league_rate=sum(r[field] for r in league)/sum(r['attempts'] for r in league)
    if not 0<league_rate<1:return None,'League conversion-rate prior unavailable'
    recent=current[-4:]
    attempts=.6*statistics.mean(r['attempts'] for r in recent[-2:])+.4*statistics.mean(r['attempts'] for r in recent)
    total_attempts=sum(r['attempts'] for r in history)
    qb_rate=(sum(r[field] for r in history)+100*league_rate)/(total_attempts+100)
    allowed_rate=(sum(r[field] for r in allowed)+150*league_rate)/(sum(r['attempts'] for r in allowed)+150)
    factor=max(.8,min(1.2,allowed_rate/league_rate))
    rate=max(.001,min(.999,qb_rate*factor))
    centered=statistics.mean(r['attempts'] for r in history)
    ns=[max(5,min(75,round(attempts+r['attempts']-centered))) for r in history]
    concentration=80 if field=='completions' else 40
    pmf=distribution(ns,rate,concentration)
    return dict(expected=sum(k*p for k,p in enumerate(pmf)),attempts=statistics.mean(ns),attempt_counts=ns,rate=rate,league_rate=league_rate,qb_rate=qb_rate,opponent_rate=allowed_rate,opponent_factor=factor,concentration=concentration,pmf=pmf,low=quantile(pmf,.1),high=quantile(pmf,.9),games=len(history),current_team_games=len(current),baseline=statistics.mean(r[field] for r in recent),prior_counts=[r[field] for r in history],field=field),''


def validate(players,teams,year=2025):
    # No parameters are selected using these outcomes. Every estimate filters
    # its inputs to strictly earlier weeks; all same-game forecasts stay grouped.
    pi,ti,defense=defaultdict(list),defaultdict(list),defaultdict(list)
    for r in players:pi[r['season'],r['player_id']].append(r)
    for r in teams:
        ti[r['season'],r['team']].append(r);defense[r['season'],r['opponent_team']].append(r)
    idx=(pi,ti,defense);reports={}
    for label,field in MARKETS.values():
        # Select probability blending on the preceding season only. The later
        # validation season never chooses this weight.
        tuning=defaultdict(list)
        for r in players:
            if r['season']!=year-1 or r.get('position')!='QB' or (r.get('attempts') or 0)<15 or not valid(r,field):continue
            f,_=estimate(r['player_id'],year-1,r['week'],r['team'],r['opponent_team'],idx,field)
            if not f:continue
            line=math.floor(f['baseline'])+.5
            raw=tail(f['pmf'],line);freq=(1+sum(v>line for v in f['prior_counts']))/(len(f['prior_counts'])+2)
            tuning[r['game_id']].append((raw,freq,int(r[field]>line)))
        weights=(0.,.25,.5,.75,1.)
        def score(weight):
            return statistics.mean(statistics.mean(((1-weight)*p+weight*b-y)**2 for p,b,y in rows) for rows in tuning.values())
        weight=min(weights,key=score) if sum(map(len,tuning.values()))>=50 else .5
        games=defaultdict(list)
        for r in players:
            if r['season']!=year or r.get('position')!='QB' or (r.get('attempts') or 0)<15 or not valid(r,field):continue
            f,_=estimate(r['player_id'],year,r['week'],r['team'],r['opponent_team'],idx,field)
            if not f:continue
            line=math.floor(f['baseline'])+.5
            p=tail(f['pmf'],line);y=int(r[field]>line)
            baseline_p=(1+sum(v>line for v in f['prior_counts']))/(len(f['prior_counts'])+2)
            p=(1-weight)*p+weight*baseline_p
            games[r['game_id']].append((abs(f['expected']-r[field]),abs(f['baseline']-r[field]),(p-y)**2,(baseline_p-y)**2))
        means=[statistics.mean(statistics.mean(v[i] for v in rows) for rows in games.values()) if games else None for i in range(4)]
        n=sum(len(rows) for rows in games.values())
        passed=bool(n>=100 and len(games)>=50 and means[0]<means[1] and means[2]<min(.25,means[3]))
        reports[field]=dict(category=label,season=year,forecasts=n,distinct_games=len(games),mae=means[0],baseline_mae=means[1],benchmark_brier=means[2],frequency_baseline_brier=means[3],passed=passed,frequency_weight=weight,tuning_season=year-1,tuning_examples=sum(map(len,tuning.values())),scope='Prior-week stat forecast and synthetic half-count benchmark; not historical sportsbook returns')
    return reports


def evaluated_row(row, forecast, report, now=None):
    from online_learning import adjust_forecast,adjust_probability
    output=dict(row);line=float(row['Line']);direction=row['Selection']
    weight=report.get('frequency_weight',.5)
    frequency=(1+sum(v>line for v in forecast['prior_counts']))/(len(forecast['prior_counts'])+2)
    def blended(p):return (1-weight)*p+weight*frequency
    base_p=blended(tail(forecast['pmf'],line))
    output['Base model']=VERSION+' / '+row['Category']
    output['Model']=output['Base model']
    output['Base estimated win %']=100*max(.05,min(.95,base_p if direction=='Over' else 1-base_p))
    projected,attempts=adjust_forecast(output,forecast['expected'],forecast['attempts'],now)
    def pmf_for(target,volume):
        ns=[max(1,min(75,round(n+volume-forecast['attempts']))) for n in forecast['attempt_counts']]
        mean_n=statistics.mean(ns)
        rate=max(.001,min(.999,target/mean_n))
        return distribution(ns,rate,forecast['concentration'])
    pmf=pmf_for(projected,attempts)
    p=blended(tail(pmf,line));p=max(.05,min(.95,p if direction=='Over' else 1-p))
    if output.get('Candidate projection') is not None:
        candidate=blended(tail(pmf_for(output['Candidate projection'],forecast['attempts']),line))
        output['Candidate input win %']=100*max(.05,min(.95,candidate if direction=='Over' else 1-candidate))
    p=adjust_probability(output,p,now)
    odds=float(row['Odds']);breakeven=100/(odds+100) if odds>0 else -odds/(100-odds)
    expected=sum(k*p for k,p in enumerate(pmf))
    output.pop('Projection (yards)',None)
    output.update({'Projection (count)':round(expected,2),'Expected opportunities':round(attempts,2),'Opportunity type':'Passing attempts','Conversion rate %':round(100*expected/attempts,2),'QB historical conversion %':round(100*forecast['qb_rate'],2),'Opponent conversion %':round(100*forecast['opponent_rate'],2),'Historical error range low':quantile(pmf,.1),'Historical error range high':quantile(pmf,.9),'Range method':'10th–90th percentiles of attempts/conversion distribution; experimental','Estimated win %':round(100*p,1),'Raw estimated win %':output['Online input win %'],'Break-even %':round(100*breakeven,1),'Model edge (pp)':round(100*(p-breakeven),1),'Probability method':f'Conversion-distribution probability blended with prior threshold frequency; frequency weight {weight:.2f}, selected on older-season data','Validation details':report,'Feedback status':output.get('Online learning status','Collecting prospective results'),'Workload method':'Recent current-team passing attempts with historical attempt variability','Efficiency method':'QB conversion rate shrunk to league prior, bounded opponent adjustment','Current-team games':forecast['current_team_games']})
    if not report.get('passed'):
        output['Decision']='Pass';output['Reason']='Count model has not beaten both the stat and probability benchmarks; research forecast only'
    elif p-breakeven<.05:
        output['Decision']='Pass';output['Reason']='Estimated edge below five percentage points'
    else:
        output['Decision']='Watch — experimental';output['Reason']='Recent passing workload × conversion rate; historical stat and probability benchmark gates passed. Actual-price profitability remains unverified'
    return output


def targets(player,season,week,team,opponent,idx):
    own=[r for r in idx[1].get((season,team),[]) if r['week']<week][-8:]
    allowed=[r for r in idx[2].get((season,opponent),[]) if r['week']<week][-4:]
    player_rows=[r for r in idx[0].get((season,player),[]) if r['week']<week and r['team']==team][-8:]
    by_game={r['game_id']:r for r in own}
    paired=[(r,by_game[r['game_id']]) for r in player_rows if r['game_id'] in by_game]
    if len(paired)<4 or len(allowed)<4:return None
    for p,t in paired:
        if any(p.get(k) is None for k in ('targets','receptions','receiving_yards')) or not (t.get('attempts') or 0)>0 or not 0<=p['receptions']<=p['targets']<=t['attempts']:return None
    if not {r['game_id'] for r in own[-4:]}.issubset({p['game_id'] for p,t in paired}):return None
    if any(r.get('attempts') is None for r in own+allowed):return None
    attempts=.75*(.6*statistics.mean(r['attempts'] for r in own[-2:])+.4*statistics.mean(r['attempts'] for r in own[-4:]))+.25*statistics.mean(r['attempts'] for r in allowed)
    share=sum(p['targets'] for p,t in paired)/sum(t['attempts'] for p,t in paired)
    recent_share=sum(p['targets'] for p,t in paired[-2:])/sum(t['attempts'] for p,t in paired[-2:])
    share=max(0,min(1,.6*recent_share+.4*share))
    n=sum(p['targets'] for p,t in paired);catches=sum(p['receptions'] for p,t in paired)
    if n<=0:return None
    catch=(catches+20*.65)/(n+20)
    expected_targets=attempts*share
    ypc=sum(p['receiving_yards'] for p,t in paired)/catches if catches else None
    return dict(team_attempts=attempts,target_share=share,targets=expected_targets,catch_rate=catch,receptions=expected_targets*catch,yards_per_catch=ypc,receiving_yards=expected_targets*catch*ypc if ypc is not None else None,games=len(paired),scope='Supporting workload forecast, not a quoted target bet or a validated replacement for the selected receiving model')
