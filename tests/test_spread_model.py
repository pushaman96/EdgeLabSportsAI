import unittest
from datetime import date,timedelta
from spread_model import prepare,forecast,cover_result,rows

class SpreadTests(unittest.TestCase):
    def test_signed_lines_and_pushes(self):
        self.assertEqual(cover_result(3,-3),'Push')
        self.assertEqual(cover_result(4,-3),'Win')
        self.assertEqual(cover_result(-2,3),'Win')
        self.assertEqual(cover_result(-3,3),'Push')
        self.assertEqual(cover_result(3,-3.5),'Loss')
        self.assertIsNone(cover_result(None,3))
    def test_missing_scores_and_future_guard(self):
        games=[dict(date=date(2020,1,1)+timedelta(days=i),season=2020,home_team='A',away_team='B',home_score=20,away_score=10) for i in range(110)]
        prepared=prepare(games)
        self.assertIsNone(forecast(prepared,'A','B',games[-1]['date']))
        self.assertIsNotNone(forecast(prepared,'A','B',date(2021,1,1)))
        self.assertEqual(prepare(games+[dict(games[-1],home_score=None)]),prepared)
    def test_quotes_do_not_create_recommendations(self):
        events=[dict(home_team='A',away_team='B',bookmakers=[dict(title='Book',markets=[dict(key='spreads',outcomes=[dict(name='A',point=-3),dict(name='B',point=3)])])])]
        result=rows(events,{('A','B'):{'spread_margin':4}})
        self.assertEqual([r['Projection vs line'] for r in result],['Cover','Does not cover'])
        self.assertTrue(all(r['Decision'].startswith('Pass') for r in result))
