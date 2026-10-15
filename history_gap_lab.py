"""Three-game fallback research. Does not modify live picks or impute missing stats."""
from collections import defaultdict
import streamlit as st
from nfl_prop_model import MARKETS,features,indexes,projection,mean,load_prop_research

def test_history_fallback(research):
    players=research['players'];idx=indexes(players,research['teams']);samples=defaultdict(list)
    for row in players:
        if row['week']<5:continue
        for market,(label,stat,_,positions,_) in MARKETS.items():
            if row['position'] not in positions or row.get(stat) is None:continue
            args=(row['player_id'],row['season'],row['week'],row['team'],row['opponent_team'],market,idx)
            strict,reason=features(*args)
            if strict is not None:continue
            relaxed,_=features(*args,history_games=3)
            if relaxed is not None:samples[market,row['season']].append((relaxed,row[stat]))
    reports=[]
    for market,(label,*_) in MARKETS.items():
        training=samples[market,2024]
        params=min(((b,d) for b in (0,.5,1) for d in (0,.25,.5)),key=lambda p:mean([abs(projection(f,*p)-y) for f,y in training])) if training else None
        for year in sorted({2025,research['season']}):
            tested=samples[market,year]
            if not tested:continue
            mae=mean([abs(projection(f,*params)-y) for f,y in tested]) if params else None
            baseline=mean([abs(f['baseline']-y) for f,y in tested])
            reports.append({'Category':label,'Season':year,'2024 fitting examples':len(training),'Fallback forecasts':len(tested),'Fallback error':round(mae,3) if mae is not None else None,'Three-game average error':round(baseline,3),'Improvement':round(baseline-mae,3) if mae is not None else None,'Status':'Research only — insufficient evidence' if len(training)<100 or len(tested)<100 else 'Research only — prospective testing required'})
    return reports

def render_history_gap_lab():
    with st.expander('Missing-history fallback test — research only'):
        st.caption('Tests only otherwise excluded examples with three consecutive recent team games. Four opponent games, position support and workload checks remain required. No missing rows are filled with zero. Fits on 2024; reports later years separately. Does not change picks.')
        if st.button('Test three-game history fallback',key='history_fallback_test'):
            try:
                from datetime import datetime,timezone
                with st.spinner('Testing historical gap examples…'):
                    st.session_state['history_fallback_reports']=test_history_fallback(load_prop_research(datetime.now(timezone.utc).year))
            except Exception:
                st.warning('Fallback research unavailable. Existing forecasts are unchanged.')
        if 'history_fallback_reports' in st.session_state:
            rows=st.session_state['history_fallback_reports']
            if rows:st.dataframe(rows,hide_index=True,use_container_width=True)
            else:st.info('No eligible fallback examples in the loaded data.')
