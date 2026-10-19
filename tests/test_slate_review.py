import copy,json,tempfile,unittest
from pathlib import Path
from slate_review import build_reviews,write_reviews
class SlateReviewTests(unittest.TestCase):
    def record(self,**updates):
        r=dict(id='p',event_id='g',sport='NFL',strategy='Original',season_type='Regular season',evidence='Published before kickoff',published_utc='2026-10-18T15:00:00Z',starts_utc='2026-10-19T00:20:00Z',category='Passing yards',result='Win',probability=.6,actual=250,projected_yards=220,expected_opportunities=30,actual_opportunities=40,profit_per_1=.9)
        r.update(updates);return r
    def test_regular_originals_only_and_pacific_day(self):
        r=self.record();before=copy.deepcopy(r)
        result=build_reviews([r,r,self.record(id='c',strategy='Cushion'),self.record(id='h',evidence='Historical import'),self.record(id='late',published_utc='2026-10-19T01:00:00Z')])['reports']['NFL:2026-10-18']
        self.assertEqual(result['metrics']['picks'],1);self.assertEqual(result['metrics']['wins'],1)
        self.assertEqual(r,before)
    def test_unfinished_and_final_unresolved_are_distinct(self):
        records=[self.record(result='Pending')]
        result=build_reviews(records)['reports']['NFL:2026-10-18'];self.assertFalse(result['all_games_final'])
        result=build_reviews(records,{'games':{'g':{'completed':True}}})['reports']['NFL:2026-10-18']
        self.assertTrue(result['all_games_final']);self.assertIn('unresolved',result['stage'])
        self.assertIsNone(result['metrics']['accuracy'])
    def test_aggregate_persistence_contains_no_pick_identity_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'report.json'
            write_reviews([self.record()],path=path,usage_path=Path(d)/'usage',feedback_path=Path(d)/'feedback')
            first=path.read_text();write_reviews([self.record()],path=path,usage_path=Path(d)/'usage',feedback_path=Path(d)/'feedback')
            self.assertEqual(path.read_text(),first)
            self.assertNotIn('published_utc',first);self.assertNotIn('event_id',first)
    def test_missing_forecast_inputs_not_called_learned_cause(self):
        r=self.record(projected_yards=None,actual_opportunities=None)
        report=build_reviews([r])['reports']['NFL:2026-10-18']
        self.assertTrue(any('missing cause is not inferred' in note for note in report['observations']))
