import json,tempfile,unittest
from pathlib import Path
from dashboard_history import tracked_records

def record(**kw):
    return dict(dict(id='p',event_id='123',sport='NBA',player='Player',category='Points',strategy='Original',line=10.5,direction='Over',result='Pending',probability=.65),**kw)
class PendingHistoryTests(unittest.TestCase):
    def test_saved_pending_records_appear_after_session_is_gone(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'ledger.json';p.write_text('{"records":[]}')
            self.assertEqual(tracked_records(p,remote_records=[record()]),[record()])
    def test_remote_grades_merge_without_rewriting_prediction(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'ledger.json';p.write_text(json.dumps({'records':[record()]}))
            result=tracked_records(p,remote_records=[record(result='Win',probability=.99,graded_utc='2026-10-24T01:00:00Z')])
            self.assertEqual(result[0]['result'],'Win')
            self.assertEqual(result[0]['probability'],.65)
    def test_session_queue_kept_when_remote_does_not_contain_it(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'missing.json'
            rows=tracked_records(p,session_records=[record(id='queued')],remote_records=[record(id='saved')])
            self.assertEqual({r['id'] for r in rows},{'queued','saved'})
