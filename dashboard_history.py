"""Compact public live board and prospective probability accuracy."""
import json,math
from pathlib import Path

def tracked_records(path,session_records=(),live_grades=(),remote_records=()):
    try:records=json.loads(Path(path).read_text())['records']
    except (OSError,ValueError,KeyError):records=[]
    merged={r['id']:r for r in records}
    for r in remote_records:merged.setdefault(r['id'],r)
    for r in session_records:merged.setdefault(r['id'],r)
    from settlement_sync import merge_grades
    return merge_grades(merge_grades(list(merged.values()),remote_records),live_grades)

def accuracy_summary(records,sport):
    rows=[r for r in records if r.get('sport','NFL')==sport and r.get('evidence') in ('Personal paper record','Published before kickoff') and r.get('strategy')=='Original' and r.get('result') in ('Win','Loss') and r.get('season_type')=='Regular season']
    wins=sum(r['result']=='Win' for r in rows);estimates=[]
    for r in rows:
        try:p=float(r['probability'])
        except (TypeError,ValueError,KeyError):continue
        if math.isfinite(p) and 0<p<1:estimates.append((p-int(r['result']=='Win'))**2)
    return {'settled':len(rows),'wins':wins,'losses':len(rows)-wins,'accuracy':wins/len(rows) if rows else None,'brier':sum(estimates)/len(estimates) if estimates else None,'probability_count':len(estimates)}

def render_public_history(sport,path='published_picks.json'):
    import streamlit as st
    from live_pick_board import render_live_board
    import settlement_sync
    from runtime_health import reload_if_changed
    settlement_sync=reload_if_changed(settlement_sync)
    fetch_published_records=settlement_sync.fetch_published_records
    remote_records=[]
    if st.button('Refresh permanently saved picks — 0 odds credits',key='refresh_published_history_'+sport):
        from runtime_health import invalidate_public
        invalidate_public('settlement ledger')
    try:
        remote_records,meta=fetch_published_records(with_status=True)
        verified_ids={r['id'] for r in remote_records}
        this_sport=[r for r in remote_records if r.get('sport','NFL')==sport]
        st.caption(('Last-good permanent history; checked ' if meta.get('stale') else 'Permanent GitHub history checked ')+meta['retrieved_utc']+' · '+str(len(this_sport))+' saved '+sport+' records, including pending picks.')
        unverified=[r for r in st.session_state.get('personal_paper_records',[]) if r.get('sport','NFL')==sport and r['id'] not in verified_ids]
        if unverified:st.warning(str(len(unverified))+' current-session picks are not yet verified in this permanent-history snapshot. Keep this session open and use Retry saving existing picks below; no odds reload is needed.')
    except Exception:
        st.warning('Permanent-history refresh is unavailable. Showing local and current-session picks; their presence here alone does not verify a permanent save.')
    records=tracked_records(path,st.session_state.get('personal_paper_records',[]),st.session_state.get('ledger_live_grades',[]),remote_records=remote_records)
    from game_day_diagnostics import render as render_day_diagnostic
    render_day_diagnostic(sport)
    st.divider()
    from pick_history import sync_session_records
    sync_session_records(key_prefix='dashboard_storage_'+sport,show_success=False)
    render_live_board(records,sport)
    st.subheader('Saved-pick probability accuracy')
    summary=accuracy_summary(records,sport)
    columns=st.columns(3)
    columns[0].metric('Settled picks',summary['settled'])
    columns[1].metric('Winner accuracy',f"{summary['accuracy']:.1%}" if summary['accuracy'] is not None else 'Not enough results')
    columns[2].metric('Brier score',f"{summary['brier']:.4f}" if summary['brier'] is not None else 'Not available')
    st.caption(f"{summary['wins']} wins · {summary['losses']} losses. Original regular-season picks saved before games; historical imports, cushions and manual entries are kept separate. Lower Brier is better. Historical model accuracy appears with matchup predictions below.")
    from nba_calibration import render as render_probability_calibration
    render_probability_calibration(records,sport=sport)


    from slate_review import render_review
    render_review(sport,records)



def render_admin_panels(records,sport):
    from app_view import is_research
    if not is_research():return
    import streamlit as st
    from automatic_reports import render_storage_status
    render_storage_status(sport)
    with st.expander('Workload candidate results — prospective comparison'):
        try:workload=json.loads(Path('workload_reviews.json').read_text())
        except (OSError,ValueError):workload={}
        rows=[r for r in workload.get('groups',[]) if r['sport']==sport]
        if rows:st.dataframe(rows,hide_index=True,use_container_width=True)
        else:st.info('Candidate comparisons appear after new forecasts are frozen before games and graded. Older picks are not relabeled as prospective evidence.')
        if sport=='NBA'and workload.get('nba_role_groups'):
            st.write('**Starter/bench role forecast comparisons**')
            st.dataframe(workload['nba_role_groups'],hide_index=True,use_container_width=True)
        if sport=='NFL'and workload.get('nfl_role_groups'):
            st.write('**NFL recent-role workload and range comparisons**')
            st.dataframe(workload['nfl_role_groups'],hide_index=True,use_container_width=True)
        models=[r for r in workload.get('prediction_model_groups',[])if r['sport']==sport]
        if models:
            st.write('**Frozen opportunity and matchup candidates versus incumbent**')
            st.dataframe(models,hide_index=True,use_container_width=True)
        st.caption('Same-game/player/category forecasts count once; errors are averaged equally by game. Missing workload is excluded, never assumed zero. Candidates do not automatically become picks.')
    from forecast_confidence_audit import render as render_confidence_audit
    render_confidence_audit(records,sport)
    from pick_learning import render_feedback
    render_feedback(records,sport)
    from learning_audit import render as render_learning_audit
    render_learning_audit(sport,records)
    from validate_prediction_research import render as render_prediction_research
    render_prediction_research(sport)
    from background_research import render as render_background_research
    render_background_research(sport)
    from nfl_scoring_models import render_validation as render_scoring_validation
    render_scoring_validation(sport)
