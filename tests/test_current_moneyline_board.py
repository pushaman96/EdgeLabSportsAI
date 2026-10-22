import copy
import unittest
from datetime import datetime,timezone,timedelta
from live_pick_board import current_moneyline_board
class CurrentMoneylineBoardTests(unittest.TestCase):
    def setUp(self):
        self.now=datetime(2026,10,22,16,tzinfo=timezone.utc);self.day=self.now.date()
        self.record=dict(id='original',game='Patriots at Bears',player='Patriots',category='Moneyline',sport='NFL',starts_utc=(self.now+timedelta(hours=8)).isoformat(),probability=.487,result='Pending')
        self.row={'Game':'Patriots at Bears','Team to research':'Bears','Model win %':51.3,'Decision':'Watch — experimental','Moneyline selection policy':'most-likely-winner-v1','Quote updated UTC':self.now.isoformat()}
        self.saved=(str(self.day),('Book',),[self.row],self.now.isoformat(),'NFL')
    def test_new_forecast_visible_without_rewriting_original(self):
        before=copy.deepcopy(self.record)
        rows=current_moneyline_board(self.saved,[self.record],'NFL',self.day,self.now)
        self.assertEqual(rows[0]['Current predicted winner'],'Bears')
        self.assertEqual(rows[0]['Earlier frozen selection'],'Patriots')
        self.assertEqual(self.record,before)
    def test_no_cross_sport_or_date_leak(self):
        self.assertEqual(current_moneyline_board(self.saved,[self.record],'NBA',self.day,self.now),[])
        self.assertEqual(current_moneyline_board(self.saved,[self.record],'NFL',self.day+timedelta(days=1),self.now),[])
    def test_expired_analysis_and_started_games_are_not_current(self):
        self.assertEqual(current_moneyline_board(self.saved,[self.record],'NFL',self.day,self.now+timedelta(minutes=16)),[])
        self.assertEqual(current_moneyline_board(self.saved,[dict(self.record,starts_utc=self.now.isoformat())],'NFL',self.day,self.now),[])
    def test_old_value_selection_is_not_current(self):
        self.row.pop('Moneyline selection policy')
        self.assertEqual(current_moneyline_board(self.saved,[self.record],'NFL',self.day,self.now),[])
