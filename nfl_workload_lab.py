"""Pregame workload experiments. Lab results do not change the betting shortlist."""
import csv
import io
import math
import statistics
from collections import defaultdict
from datetime import datetime, timezone
import requests
import streamlit as st
from nfl_prop_model import MARKETS, indexes, features, projection, error_scale, load_prop_research, load_season_stats

VARIANTS = ['Recent four-game average','Recent eight-game average','Current weighted recent workload','Team volume and player share','Opponent-adjusted workload']
UNITS = {'player_pass_yds':'Pass attempts','player_rush_yds':'Carries','player_reception_yds':'Targets','player_receptions':'Targets','player_pass_attempts':'Pass attempts','player_rush_attempts':'Carries'}

def avg(values):
    return statistics.mean(values) if values else None

def percentile(values, quantile):
    ordered=sorted(values)
    if not ordered:return None
    return ordered[min(len(ordered)-1,max(0,math.ceil(quantile*len(ordered))-1))]

def workload_inputs(row, market, idx):
    feature, reason=features(row['player_id'],row['season'],row['week'],row['team'],row['opponent_team'],market,idx)
    if not feature:return None
    _,stat,workload,_,_=MARKETS[market]
    pi,ti,defense=idx
    history=[r for r in pi[(row['season'],row['player_id'])] if r['week']<row['week'] and r['team']==row['team']][-8:]
    own=[r for r in ti[(row['season'],row['team'])] if r['week']<row['week']][-4:]
    opposing=[r for r in defense[(row['season'],row['opponent_team'])] if r['week']<row['week']][-4:]
    league=[r[workload] for values in ti.values() for r in values if r['season']==row['season'] and max(1,row['week']-4)<=r['week']<row['week'] and r[workload] is not None]
    if any(r[workload] is None for r in own+opposing) or not league:return None
    recent=[r[workload] for r in history[-4:]]
    base=avg(recent)
    own_total=avg([r[workload] for r in own])
    if not own_total or sum(r[workload] for r in history)<=0:return None
    team_expected=.6*avg([r[workload] for r in own[-2:]])+.4*own_total
    opponent_ratio=max(.75,min(1.25,avg([r[workload] for r in opposing])/avg(league)))
    predictions={
      VARIANTS[0]:base,
      VARIANTS[1]:avg([r[workload] for r in history]),
      VARIANTS[2]:feature['volume_forecast'],
      VARIANTS[3]:team_expected*min(1,base/own_total),
      VARIANTS[4]:base*(1+.25*(opponent_ratio-1)),
    }
    efficiency=sum(r[stat] for r in history)/sum(r[workload] for r in history)
    weights=[.8**(len(history)-1-i) for i in range(len(history))]
    weighted_volume=sum(r[workload]*w for r,w in zip(history,weights))/sum(weights)
    own_by_game={r['game_id']:r for r in own}
    shares=[r[workload]/own_by_game[r['game_id']][workload] for r in history[-4:] if r['game_id'] in own_by_game and own_by_game[r['game_id']][workload]>0]
    share=avg(shares)
    development_volumes={'Eight-game workload':avg([r[workload] for r in history]),
        'Weighted eight-game workload':weighted_volume,
        'Team volume × aligned player share':team_expected*min(1,share) if share is not None else base}
    recent_efficiency=sum(r[stat] for r in history[-4:])/sum(r[workload] for r in history[-4:])
    return {'feature':feature,'predictions':predictions,'efficiency':efficiency,'recent_efficiency':recent_efficiency,
        'historical_workload':sum(r[workload] for r in history),'development_volumes':development_volumes,
        'actual_workload':row[workload],'actual_yards':row[stat],'row':row}


def forecast_development(research,samples):
    reports=[];details=[];models={}
    for market,(label,stat,workload,positions,_) in MARKETS.items():
        training=samples[(market,2024)]
        if len(training)<100:continue
        totals=defaultdict(lambda:[0,0])
        for r in research['players']:
            if r['position'] in positions and r[stat] is not None and r[workload] is not None:
                totals[(r['season'],r['week'])][0]+=r[stat];totals[(r['season'],r['week'])][1]+=r[workload]
        priors={}
        for season in {r['season'] for r in research['players']}:
            yards=volume=0
            for week in range(1,23):
                priors[(season,week)]=yards/volume if volume>0 else None
                y,v=totals[(season,week)];yards+=y;volume+=v
        def predict(sample,params):
            variant,efficiency_method,blend,defense=params
            efficiency=sample['recent_efficiency'] if efficiency_method=='Recent four-game efficiency' else sample['efficiency']
            if efficiency_method=='Shrink efficiency toward position average':
                r=sample['row'];prior=priors.get((r['season'],r['week']))
                if prior is not None:
                    n=sample['historical_workload'];efficiency=(n*efficiency+40*prior)/(n+40)
            feature=dict(sample['feature'],efficiency_forecast=sample['development_volumes'][variant]*efficiency)
            return projection(feature,blend,defense)
        candidates=[(v,e,b,d) for v in training[0]['development_volumes'] for e in ('Eight-game efficiency','Recent four-game efficiency','Shrink efficiency toward position average') for b in (.5,1) for d in (0,.25,.5)]
        chosen=min(candidates,key=lambda p:avg([abs(predict(s,p)-s['actual_yards']) for s in training]))
        residuals=sorted((s['actual_yards']-predict(s,chosen))/error_scale(predict(s,chosen)) for s in training)
        models[market]={'parameters':chosen,'residuals':residuals}
        # Paired error differences quantify uncertainty, with season outcomes never used for selection.
        for year in sorted({2025,research['season']}):
            tested=samples[(market,year)]
            if not tested:continue
            errors=[abs(predict(s,chosen)-s['actual_yards']) for s in tested]
            differences=[abs(s['feature']['baseline']-s['actual_yards'])-error for s,error in zip(tested,errors)]
            # Weekly clusters avoid treating many same-week observations as independent.
            weekly=defaultdict(list)
            for s,difference in zip(tested,differences):weekly[s['row']['week']].append(difference)
            week_means=[avg(v) for v in weekly.values()]
            uncertainty=1.96*statistics.stdev(week_means)/math.sqrt(len(week_means)) if len(week_means)>1 else None
            improvement=avg(differences)
            reports.append({'Category':label,'Season':year,'Forecasts':len(tested),'Workload model':chosen[0],
                'Efficiency model':chosen[1],'Opportunity blend':chosen[2],'Opponent weight':chosen[3],
                'Forecast error (category units)':round(avg(errors),2),'Baseline error (category units)':round(avg([abs(s['feature']['baseline']-s['actual_yards']) for s in tested]),2),
                'Mean improvement (category units)':round(improvement,2),'Weeks observed':len(weekly),
                'Weekly mean improvement low':round(avg(week_means)-uncertainty,2) if uncertainty is not None else None,
                'Weekly mean improvement high':round(avg(week_means)+uncertainty,2) if uncertainty is not None else None,
                'Status':'Historical development — not independent validation' if year==2025 else 'Forward season — more evidence required'})
            for sample in tested:
                r=sample['row'];prediction=predict(sample,chosen)
                details.append({'Category':label,'Season':year,'Week':r['week'],'Player':r['player_display_name'],'Game ID':r['game_id'],
                    'Predicted opportunities':round(sample['development_volumes'][chosen[0]],2),'Predicted yards':round(prediction,2),
                    'Baseline yards':round(sample['feature']['baseline'],2),'Actual yards':sample['actual_yards'],
                    'Absolute error':round(abs(prediction-sample['actual_yards']),2)})
    return {'reports':reports,'rows':details,'models':models}


def live_opportunity_projection(row,market,idx,parameters):
    sample=workload_inputs(row,market,idx)
    if not sample:raise ValueError('Opportunity inputs unavailable.')
    variant,method,blend,defense=parameters
    efficiency=sample['recent_efficiency'] if method=='Recent four-game efficiency' else sample['efficiency']
    if method=='Shrink efficiency toward position average':
        _,stat,workload,positions,_=MARKETS[market]
        history=[r for values in idx[0].values() for r in values if r['season']==row['season'] and r['week']<row['week'] and r['position'] in positions and r[stat] is not None and r[workload] is not None]
        total=sum(r[workload] for r in history)
        if total>0:
            prior=sum(r[stat] for r in history)/total;n=sample['historical_workload']
            efficiency=(n*efficiency+40*prior)/(n+40)
    volume=sample['development_volumes'][variant]
    feature=dict(sample['feature'],efficiency_forecast=volume*efficiency)
    return projection(feature,blend,defense),volume


@st.cache_data(ttl=21600)
def load_experimental_research(season):
    research=load_prop_research(season)
    experiment=run_workload_test(research)['forecast_development']
    models={}
    for market,model in experiment['models'].items():
        label=MARKETS[market][0]
        report=next(r for r in experiment['reports'] if r['Category']==label and r['Season']==2025)
        models[market]=dict(model,forecast_passed=report['Mean improvement (category units)']>0,blend=1,defense_weight=0)
    return dict(research,schema_version=2,models=models,reports=experiment['reports'],experiment=True)

def yardage_with_workload(sample,model,volume):
    feature=dict(sample['feature'],efficiency_forecast=volume*sample['efficiency'])
    return projection(feature,model['blend'],model['defense_weight'])

def run_workload_test(research):
    players=research['players'];idx=indexes(players,research['teams'])
    samples=defaultdict(list)
    for row in players:
        for market,(_,stat,workload,positions,_) in MARKETS.items():
            if row['position'] not in positions or row[stat] is None or row[workload] is None:continue
            sample=workload_inputs(row,market,idx)
            if sample:samples[(market,row['season'])].append(sample)
    reports=[];rows=[];chosen={};training_errors={};opportunity_reports=[];opportunity_models={}
    for market,(label,*_) in MARKETS.items():
        training=samples[(market,2024)]
        if len(training)<100:continue
        chosen[market]=min(VARIANTS,key=lambda variant:avg([abs(s['predictions'][variant]-s['actual_workload']) for s in training]))
        variant=chosen[market]
        model=research['models'][market]
        # Fit workload choice AND yardage conversion on 2024 only. Never select using later results.
        candidates=[(v,b,w) for v in VARIANTS for b in (.5,1) for w in (0,.25,.5)]
        def opportunity_prediction(sample, parameters):
            v,b,w=parameters
            feature=dict(sample['feature'],efficiency_forecast=sample['predictions'][v]*sample['efficiency'])
            return projection(feature,b,w)
        parameters=min(candidates,key=lambda p:avg([abs(opportunity_prediction(s,p)-s['actual_yards']) for s in training]))
        opportunity_models[market]=parameters
        # Intervals are built entirely from 2024 errors, before testing 2025/current season.
        errors=[s['actual_workload']-s['predictions'][variant] for s in training]
        training_errors[market]=(percentile(errors,.1),percentile(errors,.9))
        for year in sorted({2025,research['season']}):
            tested=samples[(market,year)]
            if not tested:continue
            opportunity_mae=avg([abs(opportunity_prediction(s,parameters)-s['actual_yards']) for s in tested])
            yardage_baseline=avg([abs(s['feature']['baseline']-s['actual_yards']) for s in tested])
            opportunity_reports.append({'Category':label,'Season':year,'Forecasts':len(tested),
                'Opportunity variant (fit on 2024)':parameters[0], 'Opportunity blend':parameters[1],
                'Opponent adjustment weight':parameters[2], 'Opportunity yardage error':round(opportunity_mae,2),
                'Four-game yardage baseline error':round(yardage_baseline,2),
                'Improvement vs yardage baseline':round(yardage_baseline-opportunity_mae,2),
                'Evaluation':'Historical development comparison — previously inspected season' if year==2025 else 'Forward season — limited sample' if len(tested)<100 else 'Forward season',
                'Status':'Lab only — no change to picks'})
            baseline=avg([abs(s['predictions'][VARIANTS[0]]-s['actual_workload']) for s in tested])
            current=avg([abs(s['predictions'][VARIANTS[2]]-s['actual_workload']) for s in tested])
            experimental=avg([abs(s['predictions'][variant]-s['actual_workload']) for s in tested])
            current_yards=avg([abs(projection(s['feature'],model['blend'],model['defense_weight'])-s['actual_yards']) for s in tested])
            experiment_yards=avg([abs(yardage_with_workload(s,model,s['predictions'][variant])-s['actual_yards']) for s in tested])
            low,high=training_errors[market]
            coverage=avg([max(0,s['predictions'][variant]+low)<=s['actual_workload']<=s['predictions'][variant]+high for s in tested])
            reports.append({'Category':label,'Units':UNITS[market],'Test season':year,'Player-game forecasts':len(tested),'Variant selected using 2024':variant,'Four-game workload error':round(baseline,2),'Current workload error':round(current,2),'Experimental workload error':round(experimental,2),'Improvement vs current':round(current-experimental,2),'Current yardage error':round(current_yards,2),'Experimental yardage error':round(experiment_yards,2),'Workload interval coverage %':round(coverage*100,1),'Status':'Paper only — insufficient current-season sample' if year==research['season'] and len(tested)<100 else 'Lab only — not promoted'})
            for s in tested:
                r=s['row'];v=s['predictions'][variant]
                rows.append({'Category':label,'Season':year,'Week':r['week'],'Player':r['player_display_name'],'Team':r['team'],'Opponent':r['opponent_team'],'Units':UNITS[market],'Predicted workload':round(v,1),'Actual workload':s['actual_workload'],'Workload miss':round(s['actual_workload']-v,1),'Plausible workload low':round(max(0,v+low),1),'Plausible workload high':round(max(0,v+high),1),'Current yardage prediction':round(projection(s['feature'],model['blend'],model['defense_weight']),1),'Experimental yardage prediction':round(yardage_with_workload(s,model,v),1),'Actual yards':s['actual_yards'],'Variant':variant})
    development=forecast_development(research,samples)
    return {'reports':reports,'rows':rows,'chosen':chosen,'opportunity_reports':opportunity_reports,'opportunity_models':opportunity_models,'forecast_development':development,'retrieved':research['retrieved'],'season':research['season']}

def render_workload_lab():
    st.divider();st.header('NFL Workload Forecast Lab')
    from player_usage import render_nfl_usage
    render_nfl_usage()
    render_returning_player_lab()
    st.write('Test how well the program forecasts pass attempts, carries and receiving targets before trying changes on the prop Watch list.')
    st.caption('Uses free nflverse statistics. This button spends no sportsbook credits. Models use earlier weeks only. Five workload variants are selected using 2024; 2025 is the held-out test. Current-season results are reported separately and may be too sparse to support conclusions.')
    if st.button('Run / refresh workload tests',key='nfl_run_workload_lab'):
        try:
            with st.spinner('Loading completed NFL games and comparing workload forecasts...'):
                season=datetime.now(timezone.utc).year
                if datetime.now(timezone.utc).month<3:season-=1
                load_prop_research.clear()
                load_season_stats.clear()
                load_experimental_research.clear()
                result=run_workload_test(load_prop_research(season))
                st.session_state['nfl_workload_lab']=result
        except (requests.exceptions.RequestException,ValueError,TypeError,KeyError,AttributeError,OSError):
            st.warning('Workload tests could not be loaded. Existing sportsbook and prop sections remain available.');return
    saved=st.session_state.get('nfl_workload_lab')
    if not saved:return
    development=saved.get('forecast_development')
    if development and development['reports']:
        st.subheader('Forecast improvement tests — workload and efficiency')
        st.caption('Compares weighted usage, team volume × same-game player share, recent efficiency and efficiency stabilized toward a position average. All choices use 2024 only; 2025 is development evidence, not a new independent test. Approximate weekly ranges describe uncertainty in improvement, not player yardage ranges. Injuries, snap counts and game script are not modeled yet. No changes to live picks.')
        st.dataframe(development['reports'],hide_index=True,use_container_width=True)
        if development['rows']:
            output=io.StringIO();writer=csv.DictWriter(output,fieldnames=list(development['rows'][0]));writer.writeheader();writer.writerows(development['rows'])
            st.download_button('Download forecast development results',output.getvalue(),file_name='kamikaze_picks_forecast_development.csv',mime='text/csv',key='forecast_development_download')
    if saved.get('opportunity_reports'):
        st.subheader('Opportunity-based yardage experiment')
        st.caption('Tests carries/targets/attempts × historical yards per opportunity, optionally blended with recent yardage. Workload variant and yardage parameters are selected on 2024 only. The 2025 season has already informed development, so it is not a fresh independent test. Current-season results are separate. Injury impacts and game-script features are not included yet.')
        st.dataframe(saved['opportunity_reports'],hide_index=True,use_container_width=True)
        buffer=io.StringIO();writer=csv.DictWriter(buffer,fieldnames=list(saved['opportunity_reports'][0]));writer.writeheader();writer.writerows(saved['opportunity_reports'])
        st.download_button('Download opportunity yardage comparison',buffer.getvalue(),file_name='kamikaze_picks_opportunity_yardage.csv',mime='text/csv',key='opportunity_yardage_download')
    if saved['reports']:st.dataframe(saved['reports'],hide_index=True,use_container_width=True)
    else:st.info('Not enough eligible completed games for this test.')
    st.info('These results do not change Watch/Pass picks. Better workload accuracy alone does not establish a profitable prop model. Actual-price paper records, probability calibration, and more games are still required.')
    if not any(r['Test season']==saved['season'] for r in saved['reports']):st.info('Current-season test results are not available yet. Four earlier qualifying games are required for each player, and newly finished games may not appear until nflverse updates.')
    if saved['rows']:
        categories=sorted({r['Category'] for r in saved['rows']})
        category=st.selectbox('Workload test category',categories,key='workload_lab_category')
        selected=[r for r in saved['rows'] if r['Category']==category]
        years=sorted({r['Season'] for r in selected},reverse=True)
        year=st.selectbox('Workload test season',years,key='workload_lab_season')
        selected=[r for r in selected if r['Season']==year]
        names=sorted({r['Player'] for r in selected})
        name=st.selectbox('Player to inspect',['All players']+names,key='workload_lab_player')
        if name!='All players':selected=[r for r in selected if r['Player']==name]
        st.dataframe(selected,hide_index=True,use_container_width=True)
        buffer=io.StringIO();writer=csv.DictWriter(buffer,fieldnames=list(saved['rows'][0]));writer.writeheader();writer.writerows(saved['rows'])
        st.download_button('Download workload test results',buffer.getvalue(),file_name='kamikaze_picks_workload_tests.csv',mime='text/csv',key='workload_lab_download')
    st.caption(f"Statistics retrieved: {saved['retrieved']}. Interval limits use the 10th/90th percentiles of 2024 errors; the measured coverage may differ from 80%. They are not guarantees. Evaluation covers players with observed game rows and stable recent usage; missing/DNP rows are not assigned zero. Injuries, weather and sportsbook spread/total expectations are not modeled in this lab yet.")


def returning_player_test(players):
    pi=defaultdict(list)
    for r in players:pi[(r['season'],r['player_id'])].append(r)
    for rows in pi.values():rows.sort(key=lambda r:r['week'])
    samples=defaultdict(list)
    for row in players:
        for market,(label,stat,workload,positions,minimum) in MARKETS.items():
            if row['position'] not in positions or row[stat] is None or row[workload] is None:continue
            current=[r for r in pi[(row['season'],row['player_id'])] if r['week']<row['week'] and r['team']==row['team'] and r[stat] is not None and r[workload] is not None]
            if not 1<=len(current)<=3:continue
            prior=[r for r in pi.get((row['season']-1,row['player_id']),[]) if r['team']==row['team'] and r['position'] in positions and r[stat] is not None and r[workload] is not None][-8:]
            if len(prior)<8 or avg([r[workload] for r in current])<minimum:continue
            current_volume=avg([r[workload] for r in current]);prior_volume=avg([r[workload] for r in prior])
            current_total=sum(r[workload] for r in current);prior_total=sum(r[workload] for r in prior)
            if not current_total or not prior_total:continue
            samples[(market,row['season'])].append({'row':row,'current_games':len(current),'current_volume':current_volume,'prior_volume':prior_volume,
                'current_efficiency':sum(r[stat] for r in current)/current_total,'prior_efficiency':sum(r[stat] for r in prior)/prior_total,
                'baseline':avg([r[stat] for r in current]),'actual':row[stat]})
    reports=[];details=[];choices={}
    def predict(s,w):return (w*s['current_volume']+(1-w)*s['prior_volume'])*(w*s['current_efficiency']+(1-w)*s['prior_efficiency'])
    for market,(label,*_) in MARKETS.items():
        training=samples[(market,2024)]
        if len(training)<30:continue
        w=min((.25,.5,.75,1),key=lambda weight:avg([abs(predict(s,weight)-s['actual']) for s in training]))
        choices[market]=w
        for year in sorted({r['season'] for r in players if r['season']>=2025}):
            tested=samples[(market,year)]
            if not tested:continue
            baseline=avg([abs(s['baseline']-s['actual']) for s in tested]);error=avg([abs(predict(s,w)-s['actual']) for s in tested])
            reports.append({'Category':label,'Season':year,'Forecasts':len(tested),'Current-season weight (fit 2024)':w,'Forecast error':round(error,2),'Current-games baseline error':round(baseline,2),'Improvement':round(baseline-error,2),'Status':'Lab only — no picks enabled'})
            for s in tested:
                r=s['row'];details.append({'Category':label,'Season':year,'Week':r['week'],'Player':r['player_display_name'],'Current games':s['current_games'],'Projected yards':round(predict(s,w),2),'Current-games baseline':round(s['baseline'],2),'Actual yards':s['actual']})
    return {'reports':reports,'rows':details,'choices':choices}


def render_returning_player_lab():
    st.subheader('Returning and limited-history player experiment')
    st.caption('Tests players with 1–3 earlier current-season appearances and at least eight prior-season games for the same team. Parameters fit 2024 using 2023 history. This population includes early-season players, not only injury returns. Snap/route limits and injury impact still require separate data and validation.')
    if st.button('Test prior-season support for limited-history players',key='returning_player_test'):
        try:
            season=datetime.now(timezone.utc).year
            research=load_prop_research(season)
            with st.spinner('Testing prior-season workload support...'):
                prior=load_season_stats('player',2023)
                result=returning_player_test(prior+research['players'])
                st.session_state['returning_player_experiment']=result
        except (requests.exceptions.RequestException,ValueError,KeyError,TypeError,OSError):st.warning('Returning-player test could not load. Existing forecasts remain available.');return
    result=st.session_state.get('returning_player_experiment')
    if not result:return
    if result['reports']:st.dataframe(result['reports'],hide_index=True,use_container_width=True)
    else:st.info('Not enough eligible historical examples for this test.')
    st.info('No automatic promotion: test forecast accuracy, availability and actual-price probability calibration before enabling this fallback. Missing/DNP rows are not graded as zero.')
    if result['rows']:
        output=io.StringIO();writer=csv.DictWriter(output,fieldnames=list(result['rows'][0]));writer.writeheader();writer.writerows(result['rows'])
        st.download_button('Download limited-history forecast results',output.getvalue(),file_name='kamikaze_limited_history_tests.csv',mime='text/csv',key='returning_player_download')
