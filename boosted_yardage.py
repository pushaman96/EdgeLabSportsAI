"""Paper-only bridge from boosted opportunities to stat forecasts."""
import math
from collections import defaultdict
import streamlit as st
from nfl_prop_model import features,indexes,projection,error_scale,over_probability,MARKETS
from opportunity_boost import inputs,load_boosted_research,avg
from role_forecast_lab import snap_lookup
BRIDGE={'player_pass_yds':'Passing attempts','player_reception_yds':'Receiving targets','player_pass_attempts':'Passing attempts'}

def base_feature(row,market,idx):
    f,reason=features(row['player_id'],row['season'],row['week'],row['team'],row['opponent_team'],market,idx)
    if not f and (reason.startswith('Recent player-stat coverage gap:') or reason.startswith('Fewer than')):
        f,reason=features(row['player_id'],row['season'],row['week'],row['team'],row['opponent_team'],market,idx,history_games=3)
    return f,reason

def predict_with_volume(f,volume,efficiency,parameters):
    blend,defense=parameters[:2]
    return projection(dict(f,efficiency_forecast=volume*efficiency),blend,defense)

def live_boost(row,market,idx,model,snaps):
    from threadpoolctl import threadpool_limits
    f,reason=base_feature(row,market,idx)
    if not f:raise ValueError(reason)
    sample=inputs(row,BRIDGE[market],idx,snaps)
    if not sample:raise ValueError('Boosted workload inputs unavailable.')
    fit=model['opportunity_fit']
    with threadpool_limits(limits=1):raw=float(fit['model'].predict([sample['x']])[0])
    volume=max(0,fit['weight']*raw+(1-fit['weight'])*sample['weighted'])
    if market=='player_pass_attempts':return volume,volume
    efficiency=f['efficiency_forecast']/f['volume_forecast']
    if model['coupling'][2]:
        _,stat,workload,positions,_=MARKETS[market]
        history=[r for r in idx[0][(row['season'],row['player_id'])] if r['week']<row['week'] and r['team']==row['team']][-8:]
        n=sum(r[workload] for r in history)
        league=[r for values in idx[0].values() for r in values if r['season']==row['season'] and r['week']<row['week'] and r['position'] in positions and r.get(stat) is not None and r.get(workload) is not None]
        total=sum(r[workload] for r in league)
        if total:efficiency=(n*efficiency+40*sum(r[stat] for r in league)/total)/(n+40)
    return predict_with_volume(f,volume,efficiency,model['coupling']),volume

def fit_bridge(research,opportunities,snaps,reference_models=None):
    from threadpoolctl import threadpool_limits
    idx=indexes(research['players'],research['teams']);reports=[];models={}
    for market,category in BRIDGE.items():
        if category not in opportunities['models']:continue
        fit=opportunities['models'][category];label,stat,workload,positions,_=MARKETS[market]
        totals=defaultdict(lambda:[0,0])
        for r in research['players']:
            if r['position'] in positions and r.get(stat) is not None and r.get(workload) is not None:
                totals[r['season'],r['week']][0]+=r[stat];totals[r['season'],r['week']][1]+=r[workload]
        priors={}
        for season in {r['season'] for r in research['players']}:
            yards=opps=0
            for week in range(1,23):
                priors[season,week]=yards/opps if opps else None
                a,b=totals[season,week];yards+=a;opps+=b
        usable=[]
        for row in research['players']:
            if row['season']<2024 or row['position'] not in positions or row.get(stat) is None:continue
            f,_=base_feature(row,market,idx)
            s=inputs(row,category,idx,snaps) if f else None
            if s:usable.append({'row':row,'f':f,'input':s,'actual':row[stat]})
        if not usable:continue
        with threadpool_limits(limits=1):predicted=fit['model'].predict([s['input']['x'] for s in usable])
        for s,p in zip(usable,predicted):
            s['volume']=max(0,float(fit['weight']*p+(1-fit['weight'])*s['input']['weighted']))
            s['efficiency']=s['f']['efficiency_forecast']/s['f']['volume_forecast']
            row=s['row'];prior=priors.get((row['season'],row['week']))
            history=[r for r in idx[0][(row['season'],row['player_id'])] if r['week']<row['week'] and r['team']==row['team']][-8:]
            n=sum(r[workload] for r in history)
            s['stabilized']=(n*s['efficiency']+40*prior)/(n+40) if prior is not None else s['efficiency']
        tuning=[s for s in usable if s['row']['season']==2024 and 9<=s['row']['week']<=12]
        calibration=[s for s in usable if s['row']['season']==2024 and s['row']['week']>=13]
        if len(tuning)<30 or len(calibration)<50:continue
        def forecast(s,p):return s['volume'] if market=='player_pass_attempts' else predict_with_volume(s['f'],s['volume'],s['stabilized'] if p[2] else s['efficiency'],p)
        params=min(((b,d,e) for b in (.5,1) for d in (0,.25,.5) for e in (False,True)),key=lambda p:avg([abs(forecast(s,p)-s['actual']) for s in tuning]))
        residuals=sorted((s['actual']-forecast(s,params))/error_scale(forecast(s,params)) for s in calibration)
        model={'boosted':True,'opportunity_fit':fit,'coupling':params,'parameters':('Boosted tree and weighted ensemble','Stabilized efficiency' if params[2] else 'Eight-game efficiency',1 if market=='player_pass_attempts' else params[0],params[1]),'blend':params[0],'defense_weight':params[1],'residuals':residuals,'forecast_passed':False,'probability_strength':.8}
        for season in sorted({2025,research['season']}):
            tested=[s for s in usable if s['row']['season']==season]
            if not tested:continue
            mae=avg([abs(forecast(s,params)-s['actual']) for s in tested]);baseline=avg([abs(s['f']['baseline']-s['actual']) for s in tested])
            brier=avg([(over_probability(forecast(s,params),math.floor(s['f']['baseline'])+.5,residuals)-int(s['actual']>math.floor(s['f']['baseline'])+.5))**2 for s in tested])
            comparison={}
            if reference_models and market in reference_models:
                from nfl_workload_lab import live_opportunity_projection
                old_errors=[];new_errors=[]
                for s in tested:
                    try:old_prediction,_=live_opportunity_projection(s['row'],market,idx,reference_models[market]['parameters'])
                    except ValueError:continue
                    old_errors.append(abs(old_prediction-s['actual']));new_errors.append(abs(forecast(s,params)-s['actual']))
                if old_errors:comparison={'Same-game comparison count':len(old_errors),'Current v2 stat error':round(avg(old_errors),3),'Boosted same-game error':round(avg(new_errors),3)}
            reports.append(dict(comparison,**{'Category':label,'Season':season,'Forecasts':len(tested),'Boosted stat error':round(mae,3),'Recent-average error':round(baseline,3),'Improvement':round(baseline-mae,3),'Benchmark Brier':round(brier,4),'Calibration examples':len(calibration),'Status':'Paper only — not a profitability test'}))
            if season==2025:model['forecast_passed']=mae<baseline and brier<.25 and (not comparison or avg(new_errors)<avg(old_errors))
        for report in reports:
            if report['Category']==label:report['Paper routing']='Boosted candidate' if model['forecast_passed'] else 'Retain current v2'
        models[market]=model
    return models,reports

@st.cache_data(ttl=21600)
def load_boosted_pick_research(season):
    from nfl_workload_lab import load_experimental_research
    base=load_experimental_research(season)
    result=load_boosted_research(season);snaps=snap_lookup(result['snaps'])
    models,reports=fit_bridge(result['research'],result,snaps,base['models'])
    if not models:raise ValueError('Insufficient boosted forecast evidence.')
    return dict(base,players=result['research']['players'],teams=result['research']['teams'],models=dict(base['models'],**{k:v for k,v in models.items() if v['forecast_passed']}),reports=reports,boosted_opportunities=True,boosted_snaps=snaps)
