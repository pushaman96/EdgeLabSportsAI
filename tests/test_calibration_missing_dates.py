import copy
import unittest
from datetime import datetime, timezone

from nba_calibration import reliability
from nba_forecast_quality import settled_quality


class MissingPublicationDates(unittest.TestCase):
    def record(self, sport):
        return dict(id='valid', event_id='game', player='Player', category='Points',
                    sport=sport, strategy='Original', evidence='Published before kickoff',
                    season_type='Regular season', published_utc='2026-10-18T12:00:00Z',
                    starts_utc='2026-10-18T20:00:00Z', graded_utc='2026-10-19T01:00:00Z',
                    result='Win', probability=.65, actual=12, projected_count=10,
                    forecast_context={'Minutes risk': 'Steadier observed minutes'})

    def mixed(self, valid):
        rows=[dict(valid, id=str(i), event_id=str(i), published_utc=value)
              for i,value in enumerate((None, '', 123, 'invalid'))]
        missing=dict(valid, id='missing', event_id='missing')
        missing.pop('published_utc')
        rows += [missing, dict(valid, id='import', evidence='Historical import', published_utc=None), valid]
        return rows

    def test_nfl_and_nba_reliability_preserves_valid_records(self):
        for sport in ('NFL', 'NBA'):
            with self.subTest(sport=sport):
                valid=self.record(sport)
                rows=self.mixed(valid)
                before=copy.deepcopy(rows)
                asof=datetime(2026,10,21,tzinfo=timezone.utc)
                expected=reliability([valid], asof, sport)
                self.assertTrue(expected)
                self.assertEqual(reliability(rows, asof, sport), expected)
                self.assertEqual(rows,before)

    def test_quality_skips_missing_and_malformed_dates_without_mutation(self):
        valid=self.record('NBA')
        rows=self.mixed(valid)
        before=copy.deepcopy(rows)
        expected=settled_quality([valid])
        self.assertEqual(expected[0]['Stat comparisons'],1)
        self.assertEqual(settled_quality(rows),expected)
        self.assertEqual(rows,before)
