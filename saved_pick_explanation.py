"""Readable explanations from frozen pick evidence. No API or new predictions."""
import math

def number(value):
    try:
        value=float(value)
        return value if math.isfinite(value) else None
    except (TypeError,ValueError):return None

def display(value,suffix=''):
    value=number(value)
    return f'{value:g}{suffix}' if value is not None else 'Not saved'

def explanation(record):
    context=record.get('forecast_context') or {}
    probability=number(record.get('probability'));odds=number(record.get('odds'))
    breakeven=(100/(odds+100) if odds>0 else -odds/(-odds+100)) if odds is not None and abs(odds)>=100 else None
    projection=number(record.get('projected_yards'))
    units='yards'
    if projection is None:
        projection=number(record.get('projected_count'));units='count'
    if projection is None and record.get('category') in ('Passing attempts','Rushing attempts'):
        projection=number(record.get('expected_opportunities'));units='attempts'
    selection=f"{record.get('player','Unknown')} — {record.get('direction','')}"
    if record.get('line') is not None:selection+=' '+display(record['line'])
    selection+=f" · {record.get('category','')}"
    forecast=f"Saved central forecast: {display(projection,' '+units)}. Recorded line: {display(record.get('line'))}."
    if record.get('category')=='Moneyline':forecast='This is a team win-probability forecast; a yardage projection does not apply.'
    forecast+=' The central forecast and the chance of beating a line describe different parts of the forecast distribution.'
    workload=f"Expected workload: {display(record.get('expected_opportunities'))} {context.get('Opportunity type','opportunities (type not saved)')}."
    if context.get('Workload method'):workload+=' Workload method: '+str(context['Workload method'])+'.'
    if context.get('Efficiency method'):workload+=' Efficiency method: '+str(context['Efficiency method'])+'.'
    if context.get('Current-team games') is not None:workload+=f" Saved current-team sample: {context['Current-team games']} games."
    price='No model probability was saved; this record cannot establish a model price edge.'
    if probability is not None and 0<probability<1:
        price=f'Estimated selection win chance: {probability:.1%}.'
        if breakeven is not None:price+=f' Break-even chance at the recorded odds: {breakeven:.1%}. Estimated difference: {(probability-breakeven)*100:+.1f} percentage points.'
        price+=' These are experimental model estimates, not verified hit rates.'
    risks='Game flow, unexpected player usage, efficiency changes and availability can change the outcome. Injury status checks do not quantify the effects of every absence. Weather and teammate-injury effects are not fully quantified. These are the inputs saved when the pick was made, not a fresh news or lineup check.'
    if context.get('Game-script risk'):risks=str(context['Game-script risk'])+' '+risks
    if record.get('strategy')=='Manual':risks='This is a manual selection, not a researched model recommendation. '+risks
    return {'selection':selection,'forecast':forecast,'workload':workload,'price':price,'reason':record.get('reason') or 'A supporting reason was not saved for this record.','details':context.get('Evidence explanation'),'risks':risks}

def short_reason(record):
    e=explanation(record)
    return e['forecast'].split('. Recorded line:')[0]+'. '+e['price'].split('. Break-even')[0]

def render_saved_explanations(records,sport):
    import streamlit as st
    choices={r['id']:r for r in records}
    if not choices:return
    with st.expander('Why this pick? — detailed saved explanations',expanded=False):
        selected=st.selectbox('Choose a saved pick',list(choices),format_func=lambda key:explanation(choices[key])['selection']+' · '+choices[key].get('game',''),key='saved_explanation_'+sport)
        record=choices[selected];e=explanation(record)
        st.write('**'+e['selection']+'**')
        st.caption(record.get('game','')+' · '+record.get('sportsbook','Unknown sportsbook')+' · Recorded odds '+display(record.get('odds'))+' · '+record.get('strategy','Original'))
        for title,key in [('Forecast versus line','forecast'),('Workload and supporting inputs','workload'),('Probability and price','price'),('Recorded selection reason','reason'),('Risks and missing information','risks')]:
            st.write('**'+title+'**');st.write(e[key])
        if e['details']:
            st.write('**Full explanation saved with this pick**');st.write(e['details'])
        st.caption('Frozen at '+record.get('published_utc','unknown time')+' · Model: '+record.get('model','Not saved')+'. No paid AI service is used, and opening this explanation does not change the pick.')
