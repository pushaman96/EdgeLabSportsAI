"""Chronological paper candidate: team attempts -> target share -> catch rate."""
import math
import statistics
import streamlit as st
from nfl_prop_model import indexes,features,error_scale,over_probability

VERSION='NFL team-target-reception chain v1 / early-2024 tuning / late-2024 calibration'
def avg(xs):return statistics.mean(xs)

def chain_inputs(row,idx):
    season,week,team,opponent=row['season'],row['week'],row['team'],row['opponent_team']
    f,_=features(row['player_id'],season,week,team,opponent,'player_receptions',idx)
    if not f:return None
    player=[r for r in idx[0][season,row['player_id']] if r['week']<week and r['team']==team][-8:]
    own=[r for r in idx[1].get((season,team),[]) if r['week']<week][-8:]
    defense=[r for r in idx[2].get((season,opponent),[]) if r['week']<week][-4:]
    if len(own)<4 or len(defense)<4 or any(r.get('attempts') is None for r in own+defense):return None
    by_game={r['game_id']:r for r in own}
    paired=[(p,by_game[p['game_id']]) for p in player if p['game_id'] in by_game]
    if len(paired)<4 or any(p.get('targets') is None or p.get('receptions') is None or t['attempts']<=0 or not 0<=p['receptions']<=p['targets']<=t['attempts'] for p,t in paired):return None
    n=sum(p['targets'] for p,t in paired)
    if n<=0:return None
    share=sum(p['targets'] for p,t in paired)/sum(t['attempts'] for p,t in paired)
    recent=paired[-2:];recent_share=sum(p['targets'] for p,t in recent)/sum(t['attempts'] for p,t in recent)
    return {'feature':f,'team_attempts':.6*avg([r['attempts'] for r in own[-2:]])+.4*avg([r['attempts'] for r in own[-4:]]),'opponent_attempts':avg([r['attempts'] for r in defense]),'share':share,'recent_share':recent_share,'targets':n,'catches':sum(p['receptions'] for p,t in paired)}

def predict(sample,parameters):
    opponent_weight,recent_weight,prior_strength=parameters
    attempts=(1-opponent_weight)*sample['team_attempts']+opponent_weight*sample['opponent_attempts']
    share=(1-recent_weight)*sample['share']+recent_weight*sample['recent_share']
    catch=(sample['catches']+.65*prior_strength)/(sample['targets']+prior_strength)
    targets=attempts*min(1,max(0,share))
    return targets*catch,targets,attempts,catch

def fit_chain(research):
    from nfl_workload_lab import live_opportunity_projection
    idx=indexes(research['players'],research['teams']);samples=[]
    for r in research['players']:
        if r['season']<2024 or r['position'] not in ('WR','TE','RB','HB','FB') or r.get('receptions') is None:continue
        s=chain_inputs(r,idx)
        if s:samples.append(dict(s,row=r,y=r['receptions']))
    tuning=[s for s in samples if s['row']['season']==2024 and s['row']['week']<=12]
    calibration=[s for s in samples if s['row']['season']==2024 and s['row']['week']>12]
    if len(tuning)<100 or len(calibration)<50:raise ValueError('Insufficient chronological reception-chain evidence.')
    params=min(((o,w,n) for o in (0,.25,.5) for w in (0,.5) for n in (10,40)),key=lambda p:avg([abs(predict(s,p)[0]-s['y']) for s in tuning]))
    residuals=sorted((s['y']-predict(s,params)[0])/error_scale(predict(s,params)[0]) for s in calibration)
    model={'reception_chain':True,'chain_parameters':params,'blend':1,'defense_weight':0,'parameters':('Team passing volume × target share','Catch rate shrunk toward 65% prior',1,0),'residuals':residuals,'forecast_passed':False,'probability_strength':.8}
    reports=[];details=[]
    for year in sorted({2025,research['season']}):
        rows=[s for s in samples if s['row']['season']==year];paired=[]
        for s in rows:
            try:old,_=live_opportunity_projection(s['row'],'player_receptions',idx,research['models']['player_receptions']['parameters'])
            except (KeyError,ValueError):continue
            pred,targets,attempts,catch=predict(s,params);line=math.floor(s['feature']['baseline'])+.5
            p=over_probability(pred,line,residuals);actual=int(s['y']>line)
            paired.append((abs(pred-s['y']),abs(old-s['y']),abs(s['feature']['baseline']-s['y']),(p-actual)**2))
            details.append({'Season':year,'Week':s['row']['week'],'Player':s['row']['player_display_name'],'Game ID':s['row']['game_id'],'Team attempts forecast':round(attempts,2),'Player targets forecast':round(targets,2),'Catch probability %':round(100*catch,1),'Receptions forecast':round(pred,2),'Current model forecast':round(old,2),'Actual receptions':s['y']})
        if not paired:continue
        mae,oldmae,baseline,brier=[avg([p[i] for p in paired]) for i in range(4)]
        passed=len(paired)>=100 and mae<oldmae and mae<baseline and brier<.25
        if year==2025:model['forecast_passed']=passed
        target_error=avg([abs(predict(s,params)[1]-s['row']['targets']) for s in rows]) if rows else None
        team_cases={}
        for s in rows:
            own=next((t for t in idx[1].get((year,s['row']['team']),[]) if t['game_id']==s['row']['game_id']),None)
            if own and own.get('attempts') is not None:team_cases[s['row']['game_id'],s['row']['team']]=abs(predict(s,params)[2]-own['attempts'])
        reports.append({'Targets MAE':round(target_error,3) if target_error is not None else None,'Team passing attempts MAE':round(avg(list(team_cases.values())),3) if team_cases else None,'Unique team-games':len(team_cases),'Season':year,'Same-game forecasts':len(paired),'Chain receptions MAE':round(mae,3),'Current model MAE':round(oldmae,3),'Recent-average MAE':round(baseline,3),'Benchmark Brier':round(brier,4),'Tuning examples':len(tuning),'Calibration examples':len(calibration),'Status':'2025 development comparison' if year==2025 else 'Current season — limited evidence'})
    for r in reports:r['Pick routing']='Chain paper candidate' if model['forecast_passed'] else 'Retain current model'
    return {'model':model,'reports':reports,'details':details}

@st.cache_data(ttl=21600)
def load_chain_research(season):
    from nfl_workload_lab import load_experimental_research
    base=load_experimental_research(season);result=fit_chain(base)
    models=dict(base['models'])
    if result['model']['forecast_passed']:models['player_receptions']=result['model']
    return dict(base,models=models,chain_reports=result['reports'],chain_details=result['details'])

def render_reception_chain():
    from datetime import datetime,timezone
    with st.expander('Team passing → targets → receptions forecast'):
        st.caption('Team recent attempts and opponent attempts feed player target share and catch rate. Catch rate shrinks toward a fixed 65% prior. Parameters: early 2024; error calibration: late 2024. The 2025 comparison is development evidence, not a profit test. Does not numerically model injuries, weather or future score states.')
        if st.button('Compare reception chain with current model',key='reception_chain_test'):
            try:st.session_state['reception_chain_result']=load_chain_research(datetime.now(timezone.utc).year)
            except (OSError,ValueError,KeyError) as e:st.warning('Reception chain unavailable: '+str(e))
        result=st.session_state.get('reception_chain_result')
        if result:
            st.dataframe(result['chain_reports'],hide_index=True,use_container_width=True)
            st.dataframe(result['chain_details'],hide_index=True,use_container_width=True)
