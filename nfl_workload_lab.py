"""Pregame workload experiments. Lab results do not change the betting shortlist."""
import csv
import io
import math
import statistics
from collections import defaultdict
from datetime import datetime, timezone
import requests
import streamlit as st
from nfl_prop_model import MARKETS, indexes, features, projection, load_prop_research, load_season_stats

VARIANTS = ['Recent four-game average','Recent eight-game average','Current weighted recent workload','Team volume and player share','Opponent-adjusted workload']
UNITS = {'player_pass_yds':'Pass attempts','player_rush_yds':'Carries','player_reception_yds':'Targets'}

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
    return {'feature':feature,'predictions':predictions,'efficiency':efficiency,'actual_workload':row[workload],'actual_yards':row[stat],'row':row}

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
    reports=[];rows=[];chosen={};training_errors={}
    for market,(label,*_) in MARKETS.items():
        training=samples[(market,2024)]
        if len(training)<100:continue
        chosen[market]=min(VARIANTS,key=lambda variant:avg([abs(s['predictions'][variant]-s['actual_workload']) for s in training]))
        variant=chosen[market]
        model=research['models'][market]
        # Intervals are built entirely from 2024 errors, before testing 2025/current season.
        errors=[s['actual_workload']-s['predictions'][variant] for s in training]
        training_errors[market]=(percentile(errors,.1),percentile(errors,.9))
        for year in sorted({2025,research['season']}):
            tested=samples[(market,year)]
            if not tested:continue
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
    return {'reports':reports,'rows':rows,'chosen':chosen,'retrieved':research['retrieved'],'season':research['season']}

def render_workload_lab():
    st.divider();st.header('NFL Workload Forecast Lab')
    st.write('Test how well the program forecasts pass attempts, carries and receiving targets before trying changes on the prop Watch list.')
    st.caption('Uses free nflverse statistics. This button spends no sportsbook credits. Models use earlier weeks only. Five workload variants are selected using 2024; 2025 is the held-out test. Current-season results are reported separately and may be too sparse to support conclusions.')
    if st.button('Run / refresh workload tests',key='nfl_run_workload_lab'):
        try:
            with st.spinner('Loading completed NFL games and comparing workload forecasts...'):
                season=datetime.now(timezone.utc).year
                if datetime.now(timezone.utc).month<3:season-=1
                load_prop_research.clear()
                load_season_stats.clear()
                result=run_workload_test(load_prop_research(season))
                st.session_state['nfl_workload_lab']=result
        except (requests.exceptions.RequestException,ValueError,TypeError,KeyError,AttributeError,OSError):
            st.warning('Workload tests could not be loaded. Existing sportsbook and prop sections remain available.');return
    saved=st.session_state.get('nfl_workload_lab')
    if not saved:return
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
