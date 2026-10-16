"""Run: python -m unittest discover -s tests -p test_pick_learning.py"""
import copy
import unittest
from datetime import datetime,timedelta,timezone
from pick_learning import build_feedback,adjust_row

class FeedbackTests(unittest.TestCase):
    def setUp(self):
        self.asof=datetime(2026,10,16,tzinfo=timezone.utc)
        start=datetime(2025,1,1,tzinfo=timezone.utc)
        self.rows=[]
        for event in range(100):
            kickoff=start+timedelta(days=event)
            for player in range(5):
                self.rows.append({'id':f'{event}-{player}','event_id':str(event),'player':str(player),'sport':'NFL','model':'fixture','category':'Passing yards','direction':'Over','line':200.5,'strategy':'Original','season_type':'Regular season','evidence':'Personal paper record','published_utc':(kickoff-timedelta(hours=1)).isoformat(),'starts_utc':kickoff.isoformat(),'graded_utc':(kickoff+timedelta(hours=4)).isoformat(),'probability':.85,'result':'Win' if player<3 else 'Loss'})

    def test_validated_correction_preserves_original_records(self):
        original=copy.deepcopy(self.rows)
        state=build_feedback(self.rows,self.asof)
        self.assertEqual(state['active_corrections'],1)
        row={'Model':'fixture','Category':'Passing yards','Selection':'Over'}
        self.assertLess(adjust_row(row,.85,self.asof,state),.85)
        self.assertTrue(row['Feedback version'])
        self.assertEqual(self.rows,original)

    def test_holdout_results_do_not_choose_parameters(self):
        base=next(iter(build_feedback(self.rows,self.asof)['groups'].values()))
        changed=[dict(r,result='Win') if int(r['event_id'])>=70 else r for r in self.rows]
        candidate=next(iter(build_feedback(changed,self.asof)['groups'].values()))
        self.assertEqual(base['parameters'],candidate['parameters'])
        self.assertFalse(candidate['active'])

    def test_imports_missing_times_and_future_grades_cannot_train(self):
        for change in ({'evidence':'Historical import'},{'published_utc':None},{'graded_utc':(self.asof+timedelta(days=1)).isoformat()}):
            state=build_feedback([dict(r,**change) for r in self.rows],self.asof)
            self.assertEqual(state['eligible_picks'],0)

    def test_correlated_picks_do_not_replace_distinct_games(self):
        state=build_feedback([dict(r,event_id='one-game') for r in self.rows],self.asof)
        self.assertEqual(state['active_corrections'],0)

    def test_cannot_extrapolate_or_use_future_feedback(self):
        state=build_feedback(self.rows,self.asof)
        row={'Model':'fixture','Category':'Passing yards','Selection':'Over'}
        self.assertEqual(adjust_row(dict(row),.6,self.asof,state),.6)
        self.assertEqual(adjust_row(dict(row),.85,self.asof-timedelta(days=1),state),.85)
        self.assertEqual(adjust_row(dict(row),.85,self.asof+timedelta(days=8),state),.85)

    def test_opposite_direction_is_separate(self):
        state=build_feedback(self.rows,self.asof)
        self.assertEqual(adjust_row({'Model':'fixture','Category':'Passing yards','Selection':'Under'},.85,self.asof,state),.85)

if __name__=='__main__':unittest.main()
