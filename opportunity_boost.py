"""Chronological boosted-tree opportunity forecasts. No automatic pick promotion."""
import math
import statistics
from collections import defaultdict
from datetime import datetime,timezone
import streamlit as st
from nfl_prop_model import indexes,load_prop_research,load_season_stats,features as strict_features
from player_usage import load_snap_usage
from role_forecast_lab import snap_lookup
from nfl_prop_model import name_key,num
VERSION='NFL boosted opportunities v1'
CATEGORIES={'Passing attempts':('attempts',('QB',),15,'player_pass_yds'),'Receiving targets':('targets',('WR','TE','RB','HB','FB'),2,'player_reception_yds')}
FEATURES=('opps_2','opps_4','opps_8','opps_sd','opps_trend','history_games','weeks_since_last','missing_team_games','team_2','team_4','opponent_4','share_2','share_4','snap_2','snap_change','opps_per_snap','prior_opps','prior_games','is_qb','is_rb','is_te')

def avg(v):return statistics.mean(float(x) for x in v) if v else math.nan

def inputs(row,category,idx,snaps):
    field,positions,minimum,proxy=CATEGORIES[category]
    history=[r for r in idx[0].get((row['season'],row['player_id']),[]) if r['week']<row['week'] and r['team']==row['team'] and r.get(field) is not None][-8:]
    if len(history)<2 or history[-1]['position'] not in positions:return None
    own=[r for r in idx[1].get((row['season'],row['team']),[]) if r['week']<row['week'] and r.get(field) is not None][-4:]
    opp=[r for r in idx[2].get((row['season'],row['opponent_team']),[]) if r['week']<row['week'] and r.get(field) is not None][-4:]
    if len(own)<4 or len(opp)<4 or history[-1]['game_id']!=own[-1]['game_id']:return None
    recent=[r[field] for r in history[-4:]]
    if avg(recent[-2:])<minimum:return None
    own_by_game={r['game_id']:r for r in own}
    paired=[(r,own_by_game[r['game_id']]) for r in history[-4:] if r['game_id'] in own_by_game and own_by_game[r['game_id']][field]>0]
    shares=[r[field]/t[field] for r,t in paired]
    snap_data=[]
    for r in history[-4:]:
        found=snaps.get((r['season'],r['team'],r['game_id'],name_key(r['player_display_name'])),[])
        if len(found)!=1:continue
        share=num(found[0].get('offense_pct'));count=num(found[0].get('offense_snaps'))
        if share is not None and 0<=share<=1:snap_data.append((r,share,count))
    fractions=[s for _,s,_ in snap_data]
    ratios=[r[field]/count for r,_,count in snap_data if count is not None and count>0]
    prior=[r[field] for r in idx[0].get((row['season']-1,row['player_id']),[]) if r['team']==row['team'] and r['position'] in positions and r.get(field) is not None][-8:]
    pos=history[-1]['position']
    values=[avg(recent[-2:]),avg(recent),avg([r[field] for r in history]),statistics.pstdev(recent),avg(recent[-2:])-avg(recent),len(history),row['week']-history[-1]['week'],len({t['game_id'] for t in own}-{r['game_id'] for r in history}),avg([r[field] for r in own[-2:]]),avg([r[field] for r in own]),avg([r[field] for r in opp]),avg(shares[-2:]),avg(shares),avg(fractions[-2:]),avg(fractions[-2:])-avg(fractions[:-2]) if len(fractions)>2 else math.nan,avg(ratios),avg(prior),len(prior),float(pos=='QB'),float(pos in ('RB','HB','FB')),float(pos=='TE')]
    strict,_=strict_features(row['player_id'],row['season'],row['week'],row['team'],row['opponent_team'],proxy,idx)
    return {'x':values,'baseline':avg(recent),'weighted':.6*avg(recent[-2:])+.4*avg(recent),'strict_eligible':strict is not None,'row':row}

def dataset(research,snap_rows):
    idx=indexes(research['players'],research['teams']);snaps=snap_lookup(snap_rows);out=defaultdict(list)
    for r in research['players']:
        if r['season']<2023:continue
        for category,(field,positions,*_) in CATEGORIES.items():
            if r['position'] not in positions or r.get(field) is None:continue
            sample=inputs(r,category,idx,snaps)
            if sample:out[category].append(dict(sample,y=r[field]))
    return out

def train_compare(samples,current_season):
    from sklearn.ensemble import HistGradientBoostingRegressor
    from threadpoolctl import threadpool_limits
    reports=[];models={};details=[]
    with threadpool_limits(limits=1):
        for category,rows in samples.items():
            train=[r for r in rows if r['row']['season']==2023 or (r['row']['season']==2024 and r['row']['week']<=8)]
            validation=[r for r in rows if r['row']['season']==2024 and 9<=r['row']['week']<=12]
            calibration=[r for r in rows if r['row']['season']==2024 and r['row']['week']>=13]
            if len(train)<200 or len(validation)<50 or len(calibration)<50:continue
            candidates=[]
            # A small fixed candidate set; neither 2025 nor current outcomes choose settings.
            for leaf in (30,60):
                for weight in (.5,1):
                    model=HistGradientBoostingRegressor(loss='absolute_error',max_iter=120,max_leaf_nodes=7,min_samples_leaf=leaf,l2_regularization=5,learning_rate=.05,early_stopping=False,random_state=17)
                    model.fit([r['x'] for r in train],[r['y'] for r in train])
                    predicted=model.predict([r['x'] for r in validation])
                    error=avg([abs(max(0,weight*p+(1-weight)*r['weighted'])-r['y']) for r,p in zip(validation,predicted)])
                    candidates.append((error,leaf,weight,model))
            _,leaf,weight,model=min(candidates,key=lambda r:r[0])
            raw=model.predict([r['x'] for r in calibration]);cal_pred=[max(0,weight*p+(1-weight)*r['weighted']) for r,p in zip(calibration,raw)]
            errors=sorted(r['y']-p for r,p in zip(calibration,cal_pred))
            models[category]={'model':model,'weight':weight,'residuals':errors,'leaf':leaf,'fit_count':len(train),'calibration_count':len(calibration)}
            for season in sorted({2025,current_season}):
                tested=[r for r in rows if r['row']['season']==season]
                if not tested:continue
                raw=model.predict([r['x'] for r in tested]);pred=[max(0,weight*p+(1-weight)*r['weighted']) for r,p in zip(tested,raw)]
                for cohort in ('All forecastable','Current model coverage','Previously excluded history/role'):
                    pairs=[(r,p) for r,p in zip(tested,pred) if cohort=='All forecastable' or (r['strict_eligible'] if cohort=='Current model coverage' else not r['strict_eligible'])]
                    if not pairs:continue
                    mae=avg([abs(p-r['y']) for r,p in pairs]);weighted=avg([abs(r['weighted']-r['y']) for r,p in pairs]);recent=avg([abs(r['baseline']-r['y']) for r,p in pairs])
                    coverage=avg([max(0,p+errors[int(.1*(len(errors)-1))])<=r['y']<=p+errors[math.ceil(.9*(len(errors)-1))] for r,p in pairs])
                    reports.append({'Category':category,'Season':season,'Cohort':cohort,'Forecasts':len(pairs),'Boosted opportunity error':round(mae,3),'Recent-weighted baseline error':round(weighted,3),'Recent-average error':round(recent,3),'Improvement vs weighted baseline':round(weighted-mae,3),'80% interval coverage %':round(100*coverage,1),'2024-selected tree weight':weight,'Status':'Development comparison — paper only'})
                for r,p in zip(tested,pred):details.append({'Category':category,'Season':season,'Week':r['row']['week'],'Player':r['row']['player_display_name'],'Game ID':r['row']['game_id'],'Prediction':round(p,2),'Actual':r['y'],'Current weighted':round(r['weighted'],2),'Strict model coverage':r['strict_eligible']})
    return {'reports':reports,'models':models,'details':details}

@st.cache_data(ttl=21600)
def load_boosted_research(season):
    research=load_prop_research(season)
    research=dict(research,players=load_season_stats('player',2023)+research['players'],teams=load_season_stats('team',2023)+research['teams'])
    snaps=[r for year in sorted({2023,2024,2025,season}) for r in load_snap_usage(year)]
    result=train_compare(dataset(research,snaps),season)
    result['research']=research;result['snaps']=snaps
    return result

def render_boosted_opportunities():
    with st.expander('Boosted opportunity model — passing attempts and receiving targets'):
        st.caption('Learns interactions between recent workload, team volume, opponent opportunities, player share, snap participation, role trend and same-team prior history. Missing snap inputs remain missing; absent stat rows are not filled with zero. Train: 2023/early 2024. Settings: mid-2024. Uncertainty: late 2024. The 2025 comparison is development evidence. Injury effects, historical lineups, weather and betting prices are not inputs yet.')
        if st.button('Build and compare boosted opportunities',key='boosted_opportunity_test'):
            try:
                with st.spinner('Building chronological features and comparing forecasts…'):
                    now=datetime.now(timezone.utc)
                    season=now.year-1 if now.month<3 else now.year
                    st.session_state['boosted_opportunity_result']=load_boosted_research(season)
            except ImportError:st.warning('Model dependency not ready. Wait for the deployment to finish installing scikit-learn, then retry.')
            except Exception:st.warning('Opportunity model could not load. Existing picks are unchanged.')
        result=st.session_state.get('boosted_opportunity_result')
        if not result:return
        st.dataframe(result['reports'],hide_index=True,use_container_width=True)
        st.info('Research-only forecasts conditional on observed player-stat rows. No DNP probabilities, live-pick replacement, or profit claims. Errors compare identical games within each cohort; more coverage alone is not better accuracy.')
        import csv,io
        if result['details']:
            output=io.StringIO();writer=csv.DictWriter(output,fieldnames=list(result['details'][0]));writer.writeheader();writer.writerows(result['details'])
            st.download_button('Download boosted opportunity forecasts',output.getvalue(),file_name='boosted_opportunity_forecasts.csv',mime='text/csv',key='boosted_opportunity_download')
