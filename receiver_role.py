"""Optional receiving forecasts using observed snap-share changes, not routes."""
import math
import statistics
import streamlit as st
from nfl_prop_model import indexes,features,error_scale,over_probability,name_key,num
from reception_chain import chain_inputs,predict as chain_predict,fit_chain
from role_forecast_lab import snap_lookup
VERSION='NFL receiver participation v1 / early-2024 fit / late-2024 calibration'
MARKETS=('player_receptions','player_reception_yds')
def avg(v):return statistics.mean(v)

def role_inputs(row,market,idx,snaps):
    chain=chain_inputs(row,idx)
    f,_=features(row['player_id'],row['season'],row['week'],row['team'],row['opponent_team'],market,idx)
    if not chain or not f:return None
    history=[r for r in idx[0][row['season'],row['player_id']] if r['week']<row['week'] and r['team']==row['team']][-8:]
    shares=[]
    for r in history:
        matched=snaps.get((r['season'],r['team'],r['game_id'],name_key(r['player_display_name'])),[])
        s=matched[0] if len(matched)==1 else None
        share=num(s.get('offense_pct')) if s else None
        shares.append(share if share is not None and 0<=share<=1 else None)
    # Require aligned coverage; never substitute zero, another player, or a future row.
    covered=len(shares)>=4 and all(v is not None for v in shares)
    recent=avg(shares[-2:]) if covered else None
    usual=avg(shares) if covered else None
    factor=max(.7,min(1.3,recent/usual)) if covered and usual>0 else 1
    targets=sum(r['targets'] for r in history)
    yards=sum(r['receiving_yards'] for r in history) if all(r.get('receiving_yards') is not None for r in history) else None
    if market=='player_reception_yds' and (yards is None or targets<=0):return None
    return {'chain':chain,'feature':f,'snap_factor':factor,'recent_snap':recent,'usual_snap':usual,'snap_covered':covered,'yards_per_target':yards/targets if yards is not None and targets else None}

def predict(s,parameters,chain_parameters,market):
    snap_weight,blend,defense=parameters
    catches,targets,attempts,catch=chain_predict(s['chain'],chain_parameters)
    targets*=1+snap_weight*(s['snap_factor']-1)
    targets=min(attempts,max(0,targets))
    stat=targets*catch if market=='player_receptions' else targets*s['yards_per_target']
    projected=((1-blend)*s['feature']['baseline']+blend*stat)*(1+defense*(s['feature']['ratio']-1))
    return max(0,projected),targets,attempts,catch

def fit_role(research,snaps):
    from nfl_workload_lab import live_opportunity_projection
    idx=indexes(research['players'],research['teams']);chain=fit_chain(research);chain_parameters=chain['model']['chain_parameters']
    output={};reports=[];details=[]
    for market in MARKETS:
        field='receptions' if market=='player_receptions' else 'receiving_yards'
        samples=[]
        for r in research['players']:
            if r['season']<2024 or r.get(field) is None or r['position'] not in ('WR','TE','RB','HB','FB'):continue
            s=role_inputs(r,market,idx,snaps)
            if s:samples.append(dict(s,row=r,y=r[field]))
        tune=[s for s in samples if s['row']['season']==2024 and s['row']['week']<=12]
        cal=[s for s in samples if s['row']['season']==2024 and s['row']['week']>12]
        if len(tune)<100 or len(cal)<50:continue
        choices=[(w,b,d) for w in (0,.5,1) for b in (.5,1) for d in (0,.25)]
        params=min(choices,key=lambda p:avg([abs(predict(s,p,chain_parameters,market)[0]-s['y']) for s in tune]))
        residuals=sorted((s['y']-predict(s,params,chain_parameters,market)[0])/error_scale(predict(s,params,chain_parameters,market)[0]) for s in cal)
        model={'receiver_role':True,'role_parameters':params,'chain_parameters':chain_parameters,'blend':1,'defense_weight':0,'parameters':('Team volume × target share × snap trend','Catch rate' if market=='player_receptions' else 'Historical yards per target',params[1],params[2]),'residuals':residuals,'probability_strength':.8,'forecast_passed':False}
        for year in sorted({2025,research['season']}):
            pairs=[];yearrows=[s for s in samples if s['row']['season']==year]
            for s in yearrows:
                try:old,_=live_opportunity_projection(s['row'],market,idx,research['models'][market]['parameters'])
                except (ValueError,KeyError):continue
                pred,targets,attempts,catch=predict(s,params,chain_parameters,market)
                # Compare with the already-added reception chain as well as v2.
                incumbent=chain_predict(s['chain'],chain_parameters)[0] if market=='player_receptions' and chain['model']['forecast_passed'] else old
                line=math.floor(s['feature']['baseline'])+.5
                brier=(over_probability(pred,line,residuals)-int(s['y']>line))**2
                pairs.append((abs(pred-s['y']),abs(incumbent-s['y']),abs(s['feature']['baseline']-s['y']),brier))
                details.append({'Season':year,'Category':field,'Player':s['row']['player_display_name'],'Game ID':s['row']['game_id'],'Team attempts':round(attempts,2),'Targets':round(targets,2),'Projection':round(pred,2),'Actual':s['y'],'Recent snap %':round(100*s['recent_snap'],1) if s['recent_snap'] is not None else None,'Usual snap %':round(100*s['usual_snap'],1) if s['usual_snap'] is not None else None,'Snap coverage':'Available' if s['snap_covered'] else 'Missing — neutral effect','Route coverage':'Unavailable'})
            if not pairs:continue
            mae,old,baseline,brier=[avg([p[i] for p in pairs]) for i in range(4)]
            passed=len(pairs)>=100 and mae<old and mae<baseline and brier<.25
            if year==2025:model['forecast_passed']=passed
            reports.append({'Category':field,'Season':year,'Same-game forecasts':len(pairs),'Candidate MAE':round(mae,3),'Incumbent MAE':round(old,3),'Recent-average MAE':round(baseline,3),'Benchmark Brier':round(brier,4),'Snap weight':params[0],'Snap coverage %':round(100*avg([s['snap_covered'] for s in yearrows]),1),'Status':'Development comparison; profitability unverified'})
        output[market]=model
    for r in reports:r['Pick routing']='Participation paper candidate' if output['player_receptions' if r['Category']=='receptions' else 'player_reception_yds']['forecast_passed'] else 'Retain incumbent'
    return {'models':output,'reports':reports,'details':details,'chain':chain}

@st.cache_data(ttl=21600)
def load_role_research(season):
    from nfl_workload_lab import load_experimental_research
    from player_usage import load_snap_usage
    base=load_experimental_research(season);snap_rows=[];issues=[]
    for year in sorted({2024,2025,season}):
        try:snap_rows+=load_snap_usage(year)
        except Exception:issues.append(f'{year} snap feed unavailable; missing inputs use a neutral effect.')
    snaps=snap_lookup(snap_rows);result=fit_role(base,snaps);models=dict(base['models'])
    if result['chain']['model']['forecast_passed']:models['player_receptions']=result['chain']['model']
    models.update({k:v for k,v in result['models'].items() if v['forecast_passed']})
    return dict(base,models=models,receiver_role_snaps=snaps,role_reports=result['reports'],role_details=result['details'],role_feed_issues=issues)

def render_receiver_role():
    from datetime import datetime,timezone
    with st.expander('Receiving participation — snap share and target opportunities'):
        st.caption('Free PFR/nflverse snaps, current-team target share and team passing volume. Routes run and targets per route are unavailable in this connection. Snap share is not route participation. Missing snap data stays missing and has a neutral model effect. No paid service is required.')
        if st.button('Compare participation receiving forecasts',key='receiver_role_compare'):
            try:st.session_state['receiver_role_results']=load_role_research(datetime.now(timezone.utc).year)
            except (OSError,ValueError,KeyError) as e:st.warning('Comparison unavailable: '+str(e))
        result=st.session_state.get('receiver_role_results')
        if result:
            for issue in result['role_feed_issues']:st.warning(issue)
            st.dataframe(result['role_reports'],hide_index=True,use_container_width=True)
            st.dataframe(result['role_details'],hide_index=True,use_container_width=True)
