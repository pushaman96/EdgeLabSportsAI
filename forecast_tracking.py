"""Freeze all usable analyzed quotes, separately from recommended picks."""
import json
from datetime import datetime, timezone
from pathlib import Path
from pick_history import make_record, persist_records, grade_all

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
            record = make_record(dict(row, Sport=sport), matches[0]['id'], event['commence_time'], now=now, strategy='Analysis')
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
    if not pending:
        return
    try:
        token = st.secrets.get('PICK_HISTORY_GITHUB_TOKEN', '')
        if not isinstance(token, str) or not token.strip():
            st.warning('Forecast learning log is session-only until permanent saving is configured.')
            return
        persist_records(list(pending.values()), token.strip(), requests, ledger=LEDGER)
        confirmed.update(pending)
        pending.clear()
        st.caption('Analyzed forecasts saved for learning, including usable Pass forecasts. Official picks stay separate.')
    except (requests.exceptions.RequestException, OSError, ValueError, KeyError, TypeError):
        st.warning('Forecast learning log has not saved permanently yet; it will retry on the next analysis.')


def grade(path=LEDGER):
    target = Path(path)
    original = records(path)
    graded = grade_all(original)
    target.write_text(json.dumps({'schema':1,'purpose':'Analyzed forecasts, not recommended picks','records':graded}, indent=2)+'\n')
    return graded
