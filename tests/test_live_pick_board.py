import copy
import unittest
from datetime import datetime,timedelta,timezone
from live_pick_board import build_board,collect_summaries

class LiveBoardTests(unittest.TestCase):
    def setUp(self):
        self.now=datetime(2026,10,18,20,tzinfo=timezone.utc)
        self.record={'id':'pick','event_id':'game','sport':'NFL','player':'Fixture QB','category':'Passing yards','direction':'Under','line':200.5,'odds':-110,'probability':.6,'model':'Fixture','strategy':'Original','starts_utc':(self.now-timedelta(hours=2)).isoformat(),'result':'Pending','game':'Away at Home'}
        self.data={'header':{'id':'game','competitions':[{'status':{'type':{'state':'in','completed':False},'period':3,'displayClock':'08:15'},'competitors':[{'team':{'displayName':'Home','abbreviation':'HOM'},'score':'14'},{'team':{'displayName':'Away','abbreviation':'AWY'},'score':'7'}]}]},'boxscore':{'players':[{'statistics':[{'name':'passing','labels':['C/ATT','YDS'],'athletes':[{'athlete':{'displayName':'Fixture QB'},'stats':['10/20','150']}]}]}]}}

    def row(self,data=None,record=None):
        return build_board([record or self.record],{('NFL','game'):{'data':data or self.data}},self.now)[0]

    def test_live_under_is_not_a_win(self):
        row=self.row()
        self.assertEqual(row['Live stat'],150)
        self.assertEqual(row['Final result'],'Pending')
        self.assertEqual(row['Period / clock'],'Q3 08:15')

    def test_final_uses_existing_grader(self):
        data=copy.deepcopy(self.data)
        data['header']['competitions'][0]['status']['type'].update(state='post',completed=True)
        self.assertEqual(self.row(data)['Final result'],'Win')

    def test_missing_stats_never_become_zero(self):
        row=self.row(record=dict(self.record,player='Missing'))
        self.assertIsNone(row['Live stat'])
        self.assertEqual(row['Final result'],'Pending')

    def test_wrong_game_is_rejected(self):
        data=copy.deepcopy(self.data);data['header']['id']='other'
        self.assertIn('identity mismatch',self.row(data)['Live position'])

    def test_incomplete_final_feed_retains_verified_saved_grade(self):
        data=copy.deepcopy(self.data)
        data['header']['competitions'][0]['status']['type'].update(state='post',completed=True)
        data['boxscore']={}
        for result in ('Win','Loss','Push'):
            row=self.row(data,dict(self.record,result=result,actual=150))
            self.assertEqual(row['Final result'],result)
            self.assertEqual(row['Live stat'],150)
            self.assertIn('saved grade',row['Live position'])
        self.assertEqual(self.row(data)['Final result'],'Pending')

    def test_complete_final_feed_can_correct_saved_grade(self):
        data=copy.deepcopy(self.data)
        data['header']['competitions'][0]['status']['type'].update(state='post',completed=True)
        self.assertEqual(self.row(data,dict(self.record,result='Loss',actual=220))['Final result'],'Win')

    def test_fetch_once_per_game_and_no_pregame_fetch(self):
        calls=[]
        def fetch(sport,eid):calls.append((sport,eid));return {'data':self.data}
        future=dict(self.record,id='future',event_id='next',starts_utc=(self.now+timedelta(days=1)).isoformat())
        collect_summaries([self.record,dict(self.record,id='second'),future],fetch,self.now)
        self.assertEqual(calls,[('NFL','game')])

    def test_deduplication_and_frozen_inputs(self):
        before=copy.deepcopy(self.record)
        rows=build_board([self.record,self.record],{},self.now)
        self.assertEqual(len(rows),1)
        self.assertEqual(self.record,before)

if __name__=='__main__':unittest.main()

