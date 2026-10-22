import copy
import unittest
from settlement_sync import merge_grades


class SettlementSyncTests(unittest.TestCase):
    def record(self, **changes):
        return dict(dict(id='one',event_id='game',sport='NBA',player='Player',
                    category='Points',strategy='Original',line=20.5,direction='Over',
                    probability=.6,result='Pending'),**changes)

    def test_stale_board_gets_final_without_changing_prediction(self):
        original=self.record();before=copy.deepcopy(original)
        updated=self.record(result='Win',actual=22,probability=.9,graded_utc='2026-10-22T02:00:00Z')
        row=merge_grades([original],[updated])[0]
        self.assertEqual(row['result'],'Win')
        self.assertEqual(row['actual'],22)
        self.assertEqual(row['probability'],.6)
        self.assertEqual(original,before)

    def test_stale_pending_and_older_final_never_replace_new_grade(self):
        saved=self.record(result='Win',actual=22,graded_utc='2026-10-22T02:00:00Z')
        for old in (self.record(),self.record(result='Loss',graded_utc='2026-10-22T01:00:00Z')):
            self.assertEqual(merge_grades([saved],[old]),[saved])

    def test_mismatched_pick_never_settles(self):
        for change in (dict(event_id='wrong'),dict(line=21.5),dict(category='Assists'),dict(player='Other')):
            row=merge_grades([self.record()],[self.record(result='Win',**change)])[0]
            self.assertEqual(row['result'],'Pending')

    def test_newer_official_correction_is_allowed(self):
        saved=self.record(result='Win',graded_utc='2026-10-22T01:00:00Z')
        update=self.record(result='Loss',graded_utc='2026-10-22T02:00:00Z')
        self.assertEqual(merge_grades([saved],[update])[0]['result'],'Loss')

    def test_dashboard_session_pending_cannot_hide_saved_win(self):
        import json
        import tempfile
        from pathlib import Path
        from dashboard_history import tracked_records
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'ledger.json'
            path.write_text(json.dumps({'records':[self.record(result='Win',actual=22)]}))
            self.assertEqual(tracked_records(path,[],[self.record()])[0]['result'],'Win')
