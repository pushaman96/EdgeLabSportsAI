"""Read-only confidence/error audit of frozen original regular-season picks."""
import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

def numeric(value):
    if isinstance(value,bool):return None
    try:
        value=float(value)
        return value if math.isfinite(value) else None
    except (TypeError,ValueError):return None

def eligible(records):
    seen=set();output=[]
    for r in records:
        if r.get('id') in seen:continue
        seen.add(r.get('id'))
        if r.get('strategy')!='Original' or r.get('evidence') not in ('Published before kickoff','Personal paper record') or r.get('season_type')!='Regular season':continue
        if r.get('result') not in ('Win','Loss'):continue
        p=numeric(r.get('probability'))
        if p is None or not 0<p<1:continue
        output.append(r)
    return output

def summarize(rows):
    if not rows:return {'picks':0,'distinct_games':0}
    games={(r.get('sport','NFL'),str(r.get('event_id'))) for r in rows}
    by_game=defaultdict(list)
    for r in rows:by_game[(r.get('sport','NFL'),str(r.get('event_id')))].append(r)
    return {'picks':len(rows),'distinct_games':len(games),'wins':sum(r['result']=='Win' for r in rows),
        'observed_hit_pct':100*sum(r['result']=='Win' for r in rows)/len(rows),
        'mean_estimate_pct':100*sum(r['probability'] for r in rows)/len(rows),
        'brier':sum((r['probability']-int(r['result']=='Win'))**2 for r in rows)/len(rows),
        'game_weighted_brier':sum(sum((r['probability']-int(r['result']=='Win'))**2 for r in values)/len(values) for values in by_game.values())/len(by_game)}

def errors(row):
    projection=numeric(row.get('projected_yards'))
    if projection is None:projection=numeric(row.get('projected_count'))
    actual=numeric(row.get('actual'));expected=numeric(row.get('expected_opportunities'));observed=numeric(row.get('actual_opportunities'))
    data={'pick_id':row.get('id'),'sport':row.get('sport','NFL'),'game':row.get('game'),'player':row.get('player'),'category':row.get('category'),'model':row.get('model'),'estimate_pct':100*row['probability'],'result':row['result'],'projected_stat':projection,'actual_stat':actual,'projected_workload':expected,'actual_workload':observed,
          'stat_error_actual_minus_forecast':actual-projection if actual is not None and projection is not None else None,
          'workload_error_actual_minus_forecast':observed-expected if observed is not None and expected is not None else None}
    # Arithmetic decomposition, not a causal attribution or corrected forecast.
    if all(v is not None for v in (projection,actual,expected,observed)) and expected>0:
        workload_component=(observed-expected)*projection/expected
        data.update(workload_component_at_forecast_rate=workload_component,remaining_production_error=actual-projection-workload_component)
    return data

def build(records):
    rows=eligible(records);bands=[];categories=[]
    for sport in ('NFL','NBA'):
        chosen=[r for r in rows if r.get('sport','NFL')==sport]
        for lo,hi in ((0,.6),(.6,.7),(.7,.8),(.8,.9),(.9,1)):
            sample=[r for r in chosen if lo<=r['probability']<hi]
            if sample:bands.append({'sport':sport,'band':f'{lo*100:.0f}–<{hi*100:.0f}%',**summarize(sample)})
        for category in sorted({r['category'] for r in chosen}):
            categories.append({'sport':sport,'category':category,**summarize([r for r in chosen if r['category']==category])})
    return {'schema':1,'generated_utc':datetime.now(timezone.utc).isoformat(),'bands':bands,'categories':categories,'high_probability_errors':[errors(r) for r in rows if r['probability']>=.8],
            'scope':'Frozen original regular-season Win/Loss records, unique pick IDs. Pushes, unresolved, manual, cushions and imports excluded. Repeated versions remain separate frozen forecasts, not independent bets. Props within games are correlated. Error decomposition is arithmetic, not proof of cause. No model changes or recalibration deployed.'}

def run():
    records=json.loads(Path('published_picks.json').read_text())['records']
    report=build(records)
    path=Path('forecast_confidence_audit.json');temp=path.with_suffix('.tmp')
    temp.write_text(json.dumps(report,indent=2,allow_nan=False)+'\n');temp.replace(path)

def render(records,sport):
    import streamlit as st
    report=build(records)
    with st.expander('Confidence audit — do high probability picks earn their estimates?'):
        st.caption(report['scope'])
        st.dataframe([r for r in report['bands'] if r['sport']==sport],hide_index=True,use_container_width=True)
        st.dataframe([r for r in report['categories'] if r['sport']==sport],hide_index=True,use_container_width=True)
        st.write('High probability forecasts: measured workload and production errors')
        st.dataframe([r for r in report['high_probability_errors'] if r['sport']==sport],hide_index=True,use_container_width=True)
        st.caption('Priority experiments: forecast workload distributions and role uncertainty; model production variance separately from minutes/attempts; fit calibration on earlier games and test on untouched later dates. More software tests alone do not establish prediction accuracy.')

if __name__=='__main__':run()
