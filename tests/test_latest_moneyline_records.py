import unittest,copy
from live_pick_board import latest_moneyline_records
class LatestMoneylineTests(unittest.TestCase):
    def row(self,player,when,id='old',sport='NFL',event='1'):
        return dict(id=id,category='Moneyline',sport=sport,event_id=event,strategy='Original',player=player,published_utc=when,result='Pending')
    def test_new_bears_selection_replaces_old_patriots_in_main_view_only(self):
        rows=[self.row('Patriots','2026-10-22T13:43:00Z'),self.row('Bears','2026-10-22T15:19:00Z','new')];before=copy.deepcopy(rows)
        main,history=latest_moneyline_records(rows)
        self.assertEqual([r['player'] for r in main],['Bears'])
        self.assertEqual([r['player'] for r in history],['Patriots'])
        self.assertEqual(rows,before)
    def test_props_and_other_games_are_not_removed(self):
        prop=dict(id='prop',category='Receiving yards')
        main,old=latest_moneyline_records([prop,self.row('Bears','2026-10-22T15:00:00Z'),self.row('Team','2026-10-22T15:00:00Z',event='2')])
        self.assertEqual(len(main),3);self.assertEqual(old,[])
    def test_ambiguous_same_time_is_history_not_an_arbitrary_winner(self):
        rows=[self.row('Bears','2026-10-22T15:00:00Z'),self.row('Patriots','2026-10-22T15:00:00Z','other')]
        main,old=latest_moneyline_records(rows);self.assertEqual(main,[]);self.assertEqual(len(old),2)
    def test_history_grades_are_preserved(self):
        old=dict(self.row('Patriots','2026-10-22T13:00:00Z'),result='Loss',actual=0)
        main,history=latest_moneyline_records([old,self.row('Bears','2026-10-22T15:00:00Z','new')])
        self.assertEqual(history[0]['result'],'Loss');self.assertEqual(history[0]['actual'],0)
