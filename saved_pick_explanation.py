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
        projection=number(record.get('projected_count'));units={'Passing completions':'completions','Passing touchdowns':'passing touchdowns','Receptions':'receptions','Points':'points','Rebounds':'rebounds','Assists':'assists','Three-pointers made':'made threes'}.get(record.get('category'),'count')
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
    line=number(record.get('line'))
    margin=None if line is None or projection is None else (line-projection if record.get('direction')=='Under' else projection-line)
    comparison='No central forecast/line comparison was saved.'
    if margin is not None:
        comparison=f'Central forecast is {abs(margin):g} {units} '+('on the selected side of the line.' if margin>0 else 'against the selected direction.' if margin<0 else 'at the line.')
        comparison+=' This distance is a forecast gap, not a guaranteed cushion or a win probability.'
    low,high=number(context.get('Historical error range low')),number(context.get('Historical error range high'))
    uncertainty='A forecast range was not saved.'
    if low is not None and high is not None:
        uncertainty=f'Saved range: {low:g}–{high:g} {units}. '+str(context.get('Range method','Historical model error range; not a guaranteed limit'))+'.'
        if line is not None and low<=line<=high:uncertainty+=' The quoted line lies inside this range.'
    volume=number(record.get('expected_opportunities'));conversion=number(context.get('Conversion rate %'))
    calculation='The detailed calculation inputs were not saved.'
    if record.get('category') in ('Passing completions','Passing touchdowns') and volume is not None and conversion is not None:
        calculation=f'{volume:g} expected passing attempts × {conversion:.2f}% conversion ≈ {display(projection)} {units}. Attempt variability and conversion uncertainty determine the probability distribution.'
    elif projection is not None and volume is not None and volume>0 and record.get('category')!='Moneyline':
        calculation=f'{volume:g} expected {context.get("Opportunity type","opportunities").lower()} × {projection/volume:.2f} implied {units} per opportunity = {projection:g} {units}. This implied rate describes the saved model output, not a new observed statistic.'
    conversions=context.get('Passing conversion breakdown')
    if isinstance(conversions,dict):
        for label,inputs in conversions.items():
            calculation+=f' Supporting {label.lower()} forecast: {display(inputs.get("Expected attempts"))} attempts × {display(inputs.get("Conversion rate %"),"% conversion")} ≈ {display(inputs.get("Forecast"))}; range {display(inputs.get("Range low"))}–{display(inputs.get("Range high"))}.'
        calculation+=' These supporting counts are not additional bets without a verified quote and a passed recommendation gate.'
    target=context.get('Target breakdown')
    if isinstance(target,dict):
        calculation+=f' Supporting receiving calculation: {display(target.get("team_attempts"))} team attempts × {display(number(target.get("target_share"))*100 if number(target.get("target_share")) is not None else None,"% target share")} = {display(target.get("targets"))} targets; × {display(number(target.get("catch_rate"))*100 if number(target.get("catch_rate")) is not None else None,"% catch rate")} = {display(target.get("receptions"))} receptions.'
        calculation+=' This supporting calculation does not replace the selected receiving model.'
    if context.get('Probability method'):uncertainty+=' Probability method: '+str(context['Probability method'])+'.'
    if context.get('Minutes risk'):
        uncertainty+=' Minutes evidence: '+str(context['Minutes risk'])+'. '+str(context.get('Minutes sensitivity',''))+'.'
        uncertainty+=' Observed minutes sample: '+display(context.get('Minutes sample games'))+' games; '+str(context.get('Minutes sample basis','basis not saved'))+'.'
    adjustments=[]
    for field,label in (('Injury adjustment %','Confirmed-absence adjustment'),('Situation adjustment %','Game-situation workload adjustment')):
        value=number(context.get(field))
        if value is not None:adjustments.append(f'{label}: {value:+.2f}%')
    if record.get('online_status'):adjustments.append(str(record['online_status']))
    if context.get('Absence scenario status'):
        adjustments.append('Absence scenario: '+display(context.get('Absence scenario minutes'))+' minutes, '+display(context.get('Absence scenario projection'))+' '+units+'. '+str(context['Absence scenario status']))
    adjustment='; '.join(adjustments) or 'Numerical adjustment details were not saved.'
    validation=context.get('Validation details')
    validation_text='Validation details were not saved with this record; a displayed probability is not independently verified accuracy.'
    if isinstance(validation,dict):
        validation_text=f'Historical stat error: {display(validation.get("mae"))}; recent-average error: {display(validation.get("baseline_mae"))}; benchmark Brier: {display(validation.get("benchmark_brier"))}. '+str(validation.get('scope',''))+'.'
        validation_text+=' Recommendation gate '+('passed.' if validation.get('passed') else 'did not pass; this remains a research forecast.')
        coverage=number(validation.get('empirical_band_validation_coverage'))
        if coverage is not None:validation_text+=f' Measured later-game empirical range coverage: {coverage:.1%}; this is not guaranteed future coverage.'
        if validation.get('validation_games') is not None:validation_text+=' Later validation sample: '+display(validation['validation_games'])+' distinct games.'
    risks='Game flow, unexpected player usage, efficiency changes and availability can change the outcome. Injury status checks do not quantify the effects of every absence. Weather and teammate-injury effects are not fully quantified. These are the inputs saved when the pick was made, not a fresh news or lineup check.'
    if context.get('Game-script risk'):risks=str(context['Game-script risk'])+' '+risks
    if record.get('strategy')=='Manual':risks='This is a manual selection, not a researched model recommendation. '+risks
    return {'selection':selection,'forecast':forecast,'workload':workload,'price':price,'reason':record.get('reason') or 'A supporting reason was not saved for this record.','details':context.get('Evidence explanation'),'risks':risks,'calculation':calculation,'comparison':comparison,'uncertainty':uncertainty,'adjustments':adjustment,'validation':validation_text}

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
        for title,key in [('Forecast versus line','forecast'),('Forecast gap','comparison'),('Workload and supporting inputs','workload'),('Calculation','calculation'),('Uncertainty','uncertainty'),('Saved adjustments','adjustments'),('Validation','validation'),('Probability and price','price'),('Recorded selection reason','reason'),('Risks and missing information','risks')]:
            st.write('**'+title+'**');st.write(e[key])
        if e['details']:
            st.write('**Full explanation saved with this pick**');st.write(e['details'])
        st.caption('Frozen at '+record.get('published_utc','unknown time')+' · Model: '+record.get('model','Not saved')+'. No paid AI service is used, and opening this explanation does not change the pick.')


def from_row(row):
    """Explain a current analysis row without requiring an API or saving it."""
    fields=('Opportunity type','Workload method','Efficiency method','Current-team games','Game-script risk','Evidence explanation','Conversion rate %','Historical error range low','Historical error range high','Range method','Validation details','Probability method','Target breakdown','Passing conversion breakdown','Injury adjustment %','Situation adjustment %','Minutes risk','Minutes sensitivity','Minutes sample games','Minutes sample basis','Absence scenario minutes','Absence scenario projection','Absence scenario status')
    context={key:row[key] for key in fields if key in row}
    return explanation(dict(player=row.get('Player'),category=row.get('Category'),direction=row.get('Selection'),line=row.get('Line'),odds=row.get('Odds'),probability=number(row.get('Estimated win %'))/100 if number(row.get('Estimated win %')) is not None else None,projected_yards=row.get('Projection (yards)'),projected_count=row.get('Projection (count)'),expected_opportunities=row.get('Expected opportunities'),reason=row.get('Reason'),forecast_context=context,online_status=row.get('Online learning status')))


def render_current_explanations(rows,prefix):
    import streamlit as st
    if not rows:return
    with st.expander('Forecast explanations — calculations, uncertainty and Pass reasons'):
        selected=st.selectbox('Choose an analyzed forecast',range(len(rows)),format_func=lambda i:' · '.join(str(rows[i].get(k,'')) for k in ('Player','Category','Selection','Line','Decision')),key=prefix+'_calculation_explanation')
        e=from_row(rows[selected])
        for label,key in [('Forecast','forecast'),('Calculation','calculation'),('Forecast gap','comparison'),('Uncertainty','uncertainty'),('Adjustments','adjustments'),('Validation','validation'),('Probability and price','price'),('Take/Pass reason','reason'),('Risks','risks')]:
            st.write('**'+label+'**');st.write(e[key])
        st.caption('Explains the current saved analysis. No paid AI API call or fresh odds request is made. Reanalyze if prices or availability changed.')

