import copy
import unittest
from datetime import datetime,timezone,date
from pick_readiness import age_label,audit_records,records_for_day,risk_notes
class ReadinessTests(unittest.TestCase):
    def record(self):return dict(id='p',sport='NFL',player='QB',event_id='g',category='Passing yards',direction='Under',line=200.5,probability=.6,strategy='Original',published_utc='2026-10-16T20:00:00Z',starts_utc='2026-10-19T00:20:00Z')
    def test_pacific_sunday_and_immutable_audit(self):
        r=self.record();before=copy.deepcopy(r)
        self.assertEqual(len(records_for_day([r],'NFL',date(2026,10,18))),1)
        self.assertEqual(audit_records([r])[0]['Audit'],'Frozen-record checks passed')
        self.assertEqual(r,before)
    def test_duplicates_late_and_conflicting_directions(self):
        r=self.record()
        self.assertIn('Duplicate',audit_records([r,r])[1]['Notes'])
        self.assertEqual(audit_records([r,dict(r,id='different',direction='Over')])[0]['Audit'],'Review needed')
        self.assertEqual(audit_records([dict(r,published_utc='2026-10-19T01:00:00Z')])[0]['Audit'],'Review needed')
    def test_freshness_never_invents_unknown_timestamps(self):
        now=datetime(2026,10,17,19,tzinfo=timezone.utc)
        self.assertEqual(age_label(None,900,now),'Unknown')
        self.assertTrue(age_label('2026-10-17T18:55:00Z',900,now).startswith('Fresh'))
        self.assertTrue(age_label('2026-10-17T18:00:00Z',900,now).startswith('Stale'))
    def test_game_script_notes_are_not_probabilities(self):
        self.assertIn('does not assign probabilities',risk_notes(self.record()))
