"""Outcome feedback with event-separated chronological probability calibration.
No model weights are fit to retrospective imports. Existing picks are immutable.
"""
import hashlib
import json
import math
import statistics
from collections import defaultdict
from datetime import datetime,timezone
from pathlib import Path
STATE='pick_learning_state.json'
VERSION='probability-feedback-v1'
MIN_PICKS=100
MIN_EVENTS=30

def utc(v):return datetime.fromisoformat(str(v).replace('Z','+00:00'))
def finite(v):
    try:
        x=float(v)
        return x if math.isfinite(x) else None
    except (TypeError,ValueError):return None

def group_key(r):
    return json.dumps([r.get('sport','NFL'),r.get('base_model') or r.get('model','Unknown'),r.get('category','Unknown'),r.get('strategy','Original'),r.get('season_type','Unknown'),r.get('direction')],separators=(',',':'))

def eligible(r,asof):
    try:
        return (r.get('evidence') in ('Personal paper record','Published before kickoff') and r.get('strategy') in ('Original','Cushion') and r.get('result') in ('Win','Loss') and r.get('season_type')=='Regular season' and utc(r['published_utc'])<utc(r['starts_utc'])<utc(r['graded_utc'])<=asof and finite(r.get('raw_probability',r.get('probability'))) is not None and 0<float(r.get('raw_probability',r.get('probability')))<1 and bool(r.get('event_id')))
    except (KeyError,TypeError,ValueError):return False

def transform(p,parameters):
    if tuple(parameters)==(1,0):return p
    strength,intercept=parameters;p=max(.001,min(.999,p))
    return max(.05,min(.95,1/(1+math.exp(-(strength*math.log(p/(1-p))+intercept)))))

def loss(r,parameters):
    p=transform(float(r.get('raw_probability',r['probability'])),parameters)
    y=int(r['result']=='Win')
    return (p-y)**2,-(y*math.log(p)+(1-y)*math.log(1-p))

def event_metrics(rows,parameters):
    groups=defaultdict(list)
    for r in rows:groups[r['event_id']].append(loss(r,parameters))
    if not groups:return None,None
    return tuple(statistics.mean(statistics.mean(v[i] for v in values) for values in groups.values()) for i in (0,1))

def diagnostics(records):
    output=[]
    for r in records:
        if r.get('result') not in ('Win','Loss','Push'):continue
        actual=finite(r.get('actual'));projected=finite(r.get('projected_count'))
        if projected is None:projected=finite(r.get('projected_yards'))
        expected=finite(r.get('expected_opportunities'));observed=finite(r.get('actual_opportunities'))
        notes=[]
        if actual is not None and projected is not None:
            notes.append('Stat forecast too low' if actual>projected else 'Stat forecast too high' if actual<projected else 'Stat forecast matched')
        else:notes.append('Original projection not saved; forecast cause cannot be determined')
        if expected is not None and observed is not None:
            if abs(observed-expected)>=max(3,.2*expected):notes.append('Workload underestimated' if observed>expected else 'Workload overestimated')
            else:notes.append('Workload near forecast')
        else:notes.append('Workload comparison unavailable')
        workload_effect=efficiency_effect=None
        if actual is not None and projected is not None and expected is not None and expected>0 and observed is not None and observed>0 and r.get('category') in ('Passing yards','Rushing yards','Receiving yards','Receptions','Passing attempts','Rushing attempts','Passing interceptions','Passing completions','Passing touchdowns','Points','Rebounds','Assists','Three-pointers made','PRA'):
            workload_effect=(observed-expected)*projected/expected
            efficiency_effect=actual-observed*projected/expected
            notes.append(f'Measured decomposition: workload {workload_effect:+.1f}, efficiency {efficiency_effect:+.1f} {r["category"].lower()}; these sum to the forecast miss, not a causal explanation')
        target_forecast=finite((r.get('forecast_context') or {}).get('Player targets forecast'))
        if target_forecast is not None and observed is not None and r.get('category') in ('Receiving yards','Receptions'):
            notes.append(f'Supporting target forecast {target_forecast:.1f} versus {observed:.0f} actual targets; difference {observed-target_forecast:+.1f}')
        if r.get('category')=='Moneyline' and isinstance(r.get('actual'),dict):
            selected=finite(r['actual'].get(r.get('player')))
            opponents=[finite(v) for team,v in r['actual'].items() if team!=r.get('player')]
            if selected is not None and len(opponents)==1 and opponents[0] is not None:
                notes=[f'Selected team score margin {selected-opponents[0]:+.0f}; no saved team scoring/possession forecast to attribute the result']
        output.append({'Pick ID':r.get('id'),'Player':r.get('player'),'Category':r.get('category'),'Model':r.get('model'),'Evidence':r.get('evidence'),'Result':r['result'],'Forecast':projected,'Actual':actual,'Forecast miss':actual-projected if actual is not None and projected is not None else None,'Workload contribution':workload_effect,'Efficiency contribution':efficiency_effect,'Expected opportunities':expected,'Actual opportunities':observed,'Review':'; '.join(notes)})
    return output

def build_feedback(records,asof=None):
    asof=asof or datetime.now(timezone.utc);groups=defaultdict(list);seen=set()
    for r in sorted(records,key=lambda r:str(r.get('published_utc') or '')):
        if not eligible(r,asof):continue
        identity=(group_key(r),str(r['event_id']),r.get('player'),r.get('direction'),r.get('line'))
        if identity in seen:continue
        seen.add(identity);groups[group_key(r)].append(r)
    states={};summaries=[]
    for key,rows in groups.items():
        # A single game's correlated picks cannot appear on both sides of the split.
        event_times={r['event_id']:utc(r['starts_utc']) for r in rows}
        events=sorted(event_times,key=lambda e:event_times[e]);split=int(.7*len(events))
        train_ids=set(events[:split]);validation_ids=set(events[split:])
        validation=[r for r in rows if r['event_id'] in validation_ids]
        first_validation=min((utc(r['published_utc']) for r in validation),default=asof)
        train=[r for r in rows if r['event_id'] in train_ids and utc(r['graded_utc'])<first_validation]
        train_ids={r['event_id'] for r in train}
        raw_brier,raw_logloss=event_metrics(rows,(1,0));n=len(rows)
        entry={'eligible_picks':n,'distinct_games':len(events),'minimum_picks':MIN_PICKS,'minimum_games':MIN_EVENTS,'status':'Collecting evidence — original probabilities retained','active':False,'raw_brier':raw_brier,'training_games':len(train_ids),'validation_games':len(validation_ids)}
        if n>=MIN_PICKS and len(events)>=MIN_EVENTS and len(train)>=60 and len(validation)>=30 and len(train_ids)>=20 and len(validation_ids)>=10:
            options=[(s,b) for s in (.5,.75,1) for b in ((0,) if json.loads(key)[2]=='Moneyline' else (-.4,-.2,0,.2,.4))]
            chosen=min(options,key=lambda p:event_metrics(train,p)[0])
            raw,rawll=event_metrics(validation,(1,0));candidate,ll=event_metrics(validation,chosen)
            differences=[]
            for event in validation_ids:
                subset=[r for r in validation if r['event_id']==event]
                differences.append(event_metrics(subset,(1,0))[0]-event_metrics(subset,chosen)[0])
            improvement=statistics.mean(differences)
            low=improvement-1.96*statistics.stdev(differences)/math.sqrt(len(differences)) if len(differences)>1 else -1
            active=chosen!=(1,0) and improvement>=.005 and low>0 and ll<=rawll
            version=hashlib.sha256(json.dumps([key,chosen,sorted(r['id'] for r in rows)],sort_keys=True).encode()).hexdigest()[:12]
            entry.update(active=active,parameters=list(chosen),validation_raw_brier=raw,validation_candidate_brier=candidate,validation_improvement=improvement,event_mean_improvement_low=low,validation_raw_logloss=rawll,validation_candidate_logloss=ll,version=version,trained_through=max(utc(r['graded_utc']) for r in rows).isoformat(),probability_min=min(float(r.get('raw_probability',r['probability'])) for r in train),probability_max=max(float(r.get('raw_probability',r['probability'])) for r in train),status='Validated probability correction active — paper testing' if active else 'Candidate failed later-game checks — original probabilities retained')
        states[key]=entry
        descriptor=json.loads(key)
        summaries.append({'Sport':descriptor[0],'Model':descriptor[1],'Category':descriptor[2],'Direction':descriptor[5],'Strategy':descriptor[3],'Eligible picks':n,'Distinct games':len(events),'Observed wins %':round(100*sum(r['result']=='Win' for r in rows)/n,1),'Mean published probability %':round(100*statistics.mean(float(r['probability']) for r in rows),1),'Brier':round(raw_brier,4),'Status':entry['status']})
    return {'schema':1,'method':VERSION,'generated_utc':asof.isoformat(),'groups':states,'summary':summaries,'diagnostics':diagnostics(records),'historical_imports_excluded':sum(r.get('evidence')=='Historical import' for r in records),'eligible_picks':sum(v['eligible_picks'] for v in states.values()),'active_corrections':sum(v['active'] for v in states.values())}

def write_feedback(records,path=STATE,asof=None):
    state=build_feedback(records,asof);target=Path(path);temporary=target.with_suffix('.tmp')
    # Persist model settings only; player-level reviews are computed inside the app.
    persisted={k:state[k] for k in ('schema','method','generated_utc','active_corrections')}
    persisted['groups']={k:v for k,v in state['groups'].items() if v.get('active')}
    temporary.write_text(json.dumps(persisted,indent=2)+'\n');temporary.replace(target)
    return state

def adjust_row(row,probability,now=None,state=None,strategy='Original',sport='NFL'):
    """Call before edge/eligibility checks. No data or validated correction => identity."""
    now=now or datetime.now(timezone.utc)
    row['Raw estimated win %']=round(100*probability,3);row['Base model']=row.get('Model','Unknown')
    row['Feedback status']='Collecting evidence — original probability retained'
    try:
        if state is None:state=json.loads(Path(STATE).read_text())
        if state.get('schema')!=1 or state.get('method')!=VERSION or not 0<=(now-utc(state['generated_utc'])).total_seconds()<=7*86400:return probability
        lookup={'sport':sport,'model':row['Base model'],'category':row['Category'],'strategy':strategy,'season_type':'Regular season','direction':row.get('Selection')}
        fitted=state.get('groups',{}).get(group_key(lookup),{})
        if not fitted.get('active'):return probability
        if fitted['eligible_picks']<MIN_PICKS or fitted['distinct_games']<MIN_EVENTS or fitted['validation_games']<10 or fitted['training_games']<20:return probability
        if utc(fitted['trained_through'])>utc(state['generated_utc']) or fitted['validation_improvement']<.005 or fitted['event_mean_improvement_low']<=0:return probability
        if fitted['validation_candidate_logloss']>fitted['validation_raw_logloss']:return probability
        if not fitted['probability_min']-.02<=probability<=fitted['probability_max']+.02:return probability
        parameters=fitted['parameters']
        if parameters[0] not in (.5,.75,1) or parameters[1] not in (-.4,-.2,0,.2,.4):return probability
        adjusted=transform(probability,parameters)
        row['Feedback version']=fitted['version'];row['Feedback status']='Validated earlier-game probability correction applied'
        row['Model']=row['Base model']+' / feedback '+fitted['version']
        return adjusted
    except (OSError,ValueError,KeyError,TypeError,IndexError,OverflowError):return probability

def render_feedback(records,sport):
    import streamlit as st
    with st.expander('Learning from saved predictions and mistakes'):
        from runtime_health import snapshot
        online=snapshot('online_learning_state.json','saved-online-state-v1',lambda data:data,{'groups':{}})
        st.caption('Saved background learning state, updated UTC: '+str(online.get('generated_utc','Awaiting grading job'))+'. Opening this panel does not retrain the model.')
        st.write('**Learning after each completed game — experimental**')
        st.caption('Every eligible graded game updates a small forecast bias, workload bias and probability adjustment. Updates start after game one, with neutral prior weight, clipped errors and a 15% forecast adjustment limit. Original forecasts stay frozen. Usable analyzed Pass forecasts train in a separate log and never enter the official pick results. NFL props and NFL/NBA moneylines use this layer; NBA manual prop quotes have no model to train.')
        summaries=[]
        for group, fitted in online['groups'].items():
            descriptor=json.loads(group)
            if descriptor[0]!=sport:continue
            n=fitted['issued_comparisons']
            summaries.append({'Sport':descriptor[0],'Model':descriptor[1],'Category':descriptor[2],'Games learned':fitted['games'],'Learning status':fitted.get('guard_status'),'Comparison games':fitted.get('comparison_games',0),'Applied learning weight':fitted.get('application_weight',1),'Forecast adjustment %':round(100*fitted['bias'],2),'Workload adjustment %':round(100*fitted['workload_bias'],2),'Probability strength':round(fitted['temperature'],3),'Frozen candidate comparisons':n,'Original Brier':round(fitted['base_brier_sum']/n,4) if n else None,'Candidate Brier':round(fitted['issued_brier_sum']/n,4) if n else None})
        if summaries:st.dataframe(summaries,hide_index=True,use_container_width=True)
        st.caption('Lower Brier is better. Comparisons use candidate and original forecasts frozen before the result, including shadow forecasts during rollback. Positive candidate loss differences are worse. Learning weight is reduced after 5 recent harmful comparison games and rolled back after at least 10 with a positive lower bound. Shadow comparisons can restore it after recovery. Updated files become available to forecasts after the grading job saves and the app reloads. Improvements are not established yet.')
        state=build_feedback([r for r in records if r.get('sport','NFL')==sport])
        st.write(f"{state['eligible_picks']} eligible settled predictions; {state['active_corrections']} validated probability corrections.")
        st.caption('The separate validation report still tests larger probability corrections. Each sport/model/category/direction/strategy is evaluated separately. This validation report requires at least 100 settled prospective picks and 30 distinct games in a group, then older-game fitting and later-game validation. Historical imports, manual picks, pending results and missing publication/grading times cannot train corrections. A statistical pass does not establish profit.')
        if state['summary']:st.dataframe(state['summary'],hide_index=True,use_container_width=True)
        if state['diagnostics']:st.dataframe(state['diagnostics'],hide_index=True,use_container_width=True)
        st.caption('Per-game adjustments above take priority when available. The larger-sample validation report is retained for research and fallback corrections.')
        st.caption('Review labels and workload/efficiency contributions describe measured errors, not proven causes. Per-game feedback adjusts forecasts and probabilities; it does not retrain the underlying trees or quantify injury, coaching or weather effects. Cushions and manual picks do not train this layer.')

