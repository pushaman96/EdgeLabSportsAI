"""Visible audit of experimental learning versus measured improvement."""
import json
import math
from pathlib import Path

def audit_rows(state, sport):
    rows=[]
    for encoded, group in state.get('groups',{}).items():
        try:
            league,model,category,season=json.loads(encoded)
        except (ValueError,TypeError):
            continue
        if league!=sport:continue
        count=group.get('issued_comparisons',0)
        base=group.get('base_brier_sum')
        issued=group.get('issued_brier_sum')
        comparable=(isinstance(count,int) and count>0 and
                    all(isinstance(v,(int,float)) and math.isfinite(v) for v in (base,issued)))
        delta=(issued-base)/count if comparable else None
        rows.append({
            'Model version':model,'Category':category,
            'Completed training games':group.get('games',0),
            'Projection adjustment %':round(100*group.get('bias',0),2),
            'Workload adjustment %':round(100*group.get('workload_bias',0),2),
            'Probability temperature':group.get('temperature'),
            'Application weight':group.get('application_weight',1),
            'Frozen probability comparisons':count,
            'Adjusted minus base Brier':delta,
            'Evidence status':('Lower Brier observed; not proof of improvement' if delta<0 else 'No Brier improvement observed') if comparable else 'No completed frozen probability comparison',
            'Guard':group.get('guard_status','Unknown'),
            'Trained through UTC':group.get('trained_through')
        })
    return rows

def render(sport,records):
    import streamlit as st
    with st.expander('Learning audit — what changed and did it help?'):
        try:state=json.loads(Path('online_learning_state.json').read_text())
        except (OSError,ValueError):state={}
        rows=audit_rows(state,sport)
        st.caption('Experimental updates are different from proven improvements. Each row applies only to its exact model version; changing versions does not silently inherit old corrections. Percentages describe fitted candidate adjustments before the application weight.')
        if rows:st.dataframe(rows,hide_index=True,use_container_width=True)
        else:st.info('No eligible completed-game learning updates are saved for this sport.')
        frozen=[r for r in records if r.get('sport','NFL')==sport and r.get('online_version') and r.get('strategy')=='Original' and r.get('evidence')in ('Personal paper record','Published before kickoff')]
        st.write('Original picks carrying a saved learning version: '+str(len(frozen)))
        st.caption('A trained state alone does not prove that a subsequent pick used it. Saved learning versions and frozen base/candidate forecasts establish application; completed later games establish comparison. Missing statistics remain unresolved. Smaller Brier is better; correlated props are not independent games. No automatic claim of improved accuracy or profit.')

    from paired_forecasts import render as render_paired_comparison
    render_paired_comparison(records,sport)
