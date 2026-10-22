import copy
import unittest
from pick_error_review import build_diagnostics, review_pick


class ErrorReviewTests(unittest.TestCase):
    def record(self, **changes):
        r=dict(id='one',event_id='game',sport='NBA',player='Player',category='Points',
               model='v1',strategy='Original',evidence='Published before kickoff',
               season_type='Regular season',published_utc='2026-10-20T12:00:00Z',
               starts_utc='2026-10-20T20:00:00Z',result='Loss',direction='Over',
               line=20.5,projected_count=24,expected_opportunities=30,
               actual_opportunities=20,actual=12,probability=.7)
        return dict(r,**changes)

    def test_exact_decomposition_and_frozen_record(self):
        record=self.record();before=copy.deepcopy(record)
        row=review_pick(record)
        self.assertAlmostEqual(row['Workload component'],-8)
        self.assertAlmostEqual(row['Production component'],-4)
        self.assertAlmostEqual(row['Actual minus forecast'],row['Workload component']+row['Production component'])
        self.assertAlmostEqual(row['Brier error'],.49)
        self.assertEqual(record,before)

    def test_zero_is_observed_but_missing_is_not_zero(self):
        self.assertEqual(review_pick(self.record(actual=0))['Actual'],0)
        for value in (None,float('nan'),'missing'):
            row=review_pick(self.record(actual=value))
            self.assertIsNone(row['Actual minus forecast'])
            self.assertNotIn('Workload component',row)
        self.assertNotIn('Workload component',review_pick(self.record(expected_opportunities=0)))

    def test_wins_and_pending_and_pushes(self):
        self.assertIn('Production component',review_pick(self.record(result='Win')))
        self.assertNotIn('Brier error',review_pick(self.record(result='Push')))
        self.assertNotIn('Actual minus forecast',review_pick(self.record(result='Pending')))

    def test_scope_deduplication_and_dates(self):
        r=self.record()
        rows=[r,self.record(id='duplicate'),self.record(id='manual',strategy='Manual'),
              self.record(id='import',evidence='Historical import',published_utc=None),
              self.record(id='cushion',strategy='Cushion')]
        self.assertEqual(len(build_diagnostics(rows)),1)

    def test_nfl_yards_and_moneyline(self):
        row=review_pick(self.record(sport='NFL',projected_count=None,projected_yards=200,
                                    expected_opportunities=25,actual_opportunities=30,actual=220))
        self.assertEqual(row['Workload component'],40)
        self.assertEqual(row['Production component'],-20)
        ml=review_pick(self.record(category='Moneyline',actual={'A':20,'B':10},projected_count=None))
        self.assertIsNone(ml['Actual'])
        self.assertIn('team-score causes',ml['Interpretation'])

    def test_scheduled_slate_report_includes_saved_reason_and_components(self):
        from slate_review import build_reviews
        reports=build_reviews([self.record(reason='Earlier minutes and production estimates')])
        row=reports['reports']['NBA:2026-10-20']['pick_error_diagnostics'][0]
        self.assertEqual(row['Saved reasoning'],'Earlier minutes and production estimates')
        self.assertEqual(row['Actual minus forecast'],-12)
