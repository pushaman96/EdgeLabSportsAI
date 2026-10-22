import unittest
from datetime import datetime,timezone
from candidate_tracking import summary

class CandidateTrackingTests(unittest.TestCase):
    def record(self,**changes):
        r=dict(id='one',sport='NBA',event_id='game',player='Player',category='Points',direction='Over',line=20.5,
               strategy='Original',evidence='Published before kickoff',season_type='Regular season',
               published_utc='2026-10-20T12:00:00Z',starts_utc='2026-10-20T20:00:00Z',graded_utc='2026-10-21T01:00:00Z',
               result='Win',actual=22,forecast_context={'Research model comparison':[{'version':'v1','line':20.5,'selection':'Over',
               'incumbent_projection':18,'candidate_projection':21,'incumbent_probability':.4,'candidate_probability':.6}]})
        return dict(r,**changes)
    def test_frozen_comparisons_deduplicate_and_measure_later_outcome(self):
        rows=summary([self.record(),self.record(id='duplicate')],datetime(2026,10,22,tzinfo=timezone.utc))
        self.assertEqual(rows[0]['Distinct games'],1)
        self.assertAlmostEqual(rows[0]['Candidate minus incumbent MAE'],-3)
        self.assertAlmostEqual(rows[0]['Candidate minus incumbent Brier'],-.2)
    def test_missing_stats_pushes_and_manual_records_do_not_invent_losses(self):
        now=datetime(2026,10,22,tzinfo=timezone.utc)
        rows=summary([self.record(actual=None,result='Push')],now)
        self.assertIsNone(rows[0]['Candidate minus incumbent MAE'])
        self.assertIsNone(rows[0]['Candidate minus incumbent Brier'])
        for change in (dict(strategy='Manual'),dict(evidence='Historical import'),dict(published_utc=None),dict(result='Pending')):
            self.assertEqual(summary([self.record(**change)],now),[])
