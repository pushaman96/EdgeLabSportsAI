"""Freeze all usable analyzed quotes, separately from recommended picks."""
import json
from datetime import datetime, timezone
from pathlib import Path
from pick_history import make_record, persist_records, grade_all,verified_pregame_start

LEDGER = 'analyzed_forecasts.json'


def records(path=LEDGER):
    try:
        return json.loads(Path(path).read_text())['records']
    except (OSError, ValueError, KeyError):
        return []


def freeze(rows, events, scoreboard, sport='NFL', now=None):
    now = now or datetime.now(timezone.utc)
    output = {}
    for row in rows:
        if row.get('Estimated win %') is None:
            continue
        event = next((e for e in events if e['away_team']+' at '+e['home_team'] == row.get('Game')), None)
        if event is None:
            continue
        start = datetime.fromisoformat(event['commence_time'].replace('Z','+00:00'))
        matches = [e for e in scoreboard.get('events', []) if e.get('name') == row['Game'] and abs((datetime.fromisoformat(e['date'].replace('Z','+00:00'))-start).total_seconds()) < 3600 and e.get('season', scoreboard.get('season', {})).get('type') == 2]
        if len(matches) != 1:
            continue
        try:
            verified_start=verified_pregame_start(matches[0],event['commence_time'],now)
            snapshot=dict(row,Sport=sport,**{'Odds scheduled start UTC':event['commence_time'],'ESPN scheduled start UTC':matches[0]['date']})
            record = make_record(snapshot, matches[0]['id'], verified_start, now=now, strategy='Analysis')
            record.update(season_type='Regular season', evidence='Personal paper record', forecast_decision=row.get('Decision'), record_purpose='Analyzed forecast only; excluded from official pick results')
            # Keep both directions/thresholds for review; learner deduplicates per
            # player/game/category and uses the earliest saved forecast.
            output.setdefault(record['id'], record)
        except (ValueError, KeyError, TypeError):
            continue
    return list(output.values())


def archive(rows, events, scoreboard, sport='NFL'):
    import streamlit as st
    import requests
    new = freeze(rows, events, scoreboard, sport)
    pending = st.session_state.setdefault('analyzed_forecasts_pending', {})
    confirmed = st.session_state.setdefault('analyzed_forecasts_confirmed', set())
    for row in new:
        if row['id'] not in confirmed:
            pending.setdefault(row['id'], row)
    retry_pending(sport)


def retry_pending(sport='NFL'):
    import streamlit as st
    import requests
    pending=st.session_state.setdefault('analyzed_forecasts_pending',{})
    confirmed=st.session_state.setdefault('analyzed_forecasts_confirmed',set())
    if not pending:return
    retry = st.button('Retry saving forecast learning — 0 odds credits', key='forecast_learning_retry_'+sport)
    import time
    last=st.session_state.get('forecast_learning_last_attempt',0)
    if not retry and time.time()-last<60:
        if st.session_state.get('forecast_learning_save_error'):
            st.warning(st.session_state['forecast_learning_save_error'])
        return
    st.session_state['forecast_learning_last_attempt']=time.time()
    try:
        token = st.secrets.get('PICK_HISTORY_GITHUB_TOKEN', '')
        if not isinstance(token,str) or not token.strip():
            st.warning('Forecast learning is queued in this session: missing top-level PICK_HISTORY_GITHUB_TOKEN. Keep this session open.')
            return
        from forecast_archive import flush
        flush(pending,confirmed,token.strip(),requests)
    except Exception as error:
        from automatic_reports import storage_reason
        message='Forecast learning save is pending. '+storage_reason(error)+' '+str(len(pending))+' forecasts remain queued. Retry saving here without loading odds; keep this session open.'
        st.session_state['forecast_learning_save_error']=message
        st.warning(message)
    else:
        st.session_state.pop('forecast_learning_save_error',None)
        st.caption('Analyzed forecasts saved in small archives and verified in GitHub. Official picks stay separate.')


def grade(path=LEDGER):
    target = Path(path)
    original = records(path)
    graded = grade_all(original)
    target.write_text(json.dumps({'schema':1,'purpose':'Analyzed forecasts, not recommended picks','records':graded}, indent=2)+'\n')
    # Read and grade small archives without merging them into the legacy large file.
    combined={r['id']:r for r in graded}
    for shard in sorted(Path('forecast_analysis').glob('*.json')):
        source=records(shard)
        updated=grade_all(source)
        if updated!=source:
            shard.write_text(json.dumps({'schema':1,'purpose':'Analyzed forecasts, not recommended picks','records':updated},indent=2)+'\n')
        for row in updated:combined.setdefault(row['id'],row)
    return list(combined.values())

