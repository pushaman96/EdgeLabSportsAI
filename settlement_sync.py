"""Refresh settlement fields without changing frozen prediction inputs."""
import json
from datetime import datetime, timezone
from urllib.request import urlopen

FINAL = ('Win', 'Loss', 'Push')
FIELDS = ('result', 'actual', 'profit_per_1', 'graded_utc', 'grading_note',
          'actual_opportunities', 'count_miss', 'yardage_miss', 'opportunity_miss')


def merge_grades(records, updates):
    latest = {r.get('id'): r for r in updates if r.get('id')}
    output = []
    for record in records:
        row = dict(record)
        update = latest.get(record.get('id'), {})
        matches = all(record.get(k) == update.get(k) for k in
                      ('event_id', 'sport', 'player', 'category', 'strategy', 'line', 'direction'))
        if matches and update.get('result') in FINAL:
            saved_time = str(record.get('graded_utc') or '')
            incoming_time = str(update.get('graded_utc') or '')
            if record.get('result') not in FINAL or incoming_time >= saved_time:
                row.update({k: update[k] for k in FIELDS if k in update})
        output.append(row)
    return output


def fetch_grades(with_status=False):
    from runtime_health import public_json
    data,meta=public_json('settlement ledger','https://raw.githubusercontent.com/pushaman96/EdgeLabSportsAI/main/published_picks.json',fresh=60,max_stale=300,validate=lambda d:isinstance(d.get('records'),list))
    rows=[r for r in data['records']if isinstance(r,dict)and r.get('result')in FINAL]
    return (rows,meta)if with_status else rows
