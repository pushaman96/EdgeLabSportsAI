"""Compact public live board and prospective probability accuracy."""
import json,math
from pathlib import Path

def tracked_records(path,session_records=(),live_grades=()):
    try:records=json.loads(Path(path).read_text())['records']
    except (OSError,ValueError,KeyError):records=[]
    merged={r['id']:r for r in records}
    for r in session_records:merged.setdefault(r['id'],r)
    graded={r['id']:r for r in live_grades}
    return [graded.get(k,r) for k,r in merged.items()]

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
    records=tracked_records(path,st.session_state.get('personal_paper_records',[]),st.session_state.get('ledger_live_grades',[]))
    st.divider()
    render_live_board(records,sport)
    st.subheader('Saved-pick probability accuracy')
    summary=accuracy_summary(records,sport)
    columns=st.columns(3)
    columns[0].metric('Settled picks',summary['settled'])
    columns[1].metric('Winner accuracy',f"{summary['accuracy']:.1%}" if summary['accuracy'] is not None else 'Not enough results')
    columns[2].metric('Brier score',f"{summary['brier']:.4f}" if summary['brier'] is not None else 'Not available')
    st.caption(f"{summary['wins']} wins · {summary['losses']} losses. Original regular-season picks saved before games; historical imports, cushions and manual entries are kept separate. Lower Brier is better. Historical model accuracy appears with matchup predictions below.")


    from slate_review import render_review
    render_review(sport,records)

    from pick_learning import render_feedback
    render_feedback(records,sport)
