import copy
import unittest
from game_situations import situation_snapshot, forecast_situation_reviews
class SituationTests(unittest.TestCase):
    def data(self):
        teams=[{'homeAway':'home','team':{'id':'h','displayName':'Home'}},{'homeAway':'away','team':{'id':'a','displayName':'Away'}}]
        p1={'id':'one','sequenceNumber':'1','type':{'text':'Touchdown'},'homeScore':14,'awayScore':0,'period':{'number':2},'text':'Home scores'}
        p2={'id':'two','sequenceNumber':'2','type':{'text':'Pass'},'homeScore':14,'awayScore':0,'period':{'number':2},'clock':{'displayValue':'08:00'},'start':{'team':{'id':'a'},'down':1,'distance':10,'yardLine':25},'text':'Away pass for 8 yards'}
        return {'header':{'id':'game','competitions':[{'competitors':teams,'status':{'type':{'completed':True}}}]},'drives':{'previous':[{'team':{'id':'h'},'plays':[p1]},{'team':{'id':'a'},'plays':[p2]}],'current':{'team':{'id':'a'},'plays':[p2]}}}
    def test_preplay_score_and_dedup(self):
        d=self.data();before=copy.deepcopy(d);s=situation_snapshot(d)
        self.assertEqual(len(s['plays']),2)
        self.assertIsNone(s['plays'][0]['Score margin before play'])
        self.assertEqual(s['plays'][1]['Score margin before play'],-14)
        self.assertEqual(s['situation_splits'][0]['Pass-call %'],100)
        self.assertEqual(d,before)
    def test_no_play_never_becomes_rushing_attempt(self):
        d=self.data();d['drives']['previous'][1]['plays'][0]['text']='No play: rush, penalty'
        self.assertEqual(situation_snapshot(d)['situation_splits'],[])
    def test_missing_feed_has_no_invented_plays(self):
        s=situation_snapshot({'header':{'id':'game'}},'NBA')
        self.assertEqual(s['plays'],[]);self.assertIsNone(s['last_play'])
    def test_nba_periods_and_text_remain_available(self):
        d=self.data();d['plays']=[{'id':'basket','period':{'number':5},'clock':{'displayValue':'02:00'},'text':'Player makes three-pointer','type':{'text':'Three Point Jumper'}}]
        self.assertEqual(situation_snapshot(d,'NBA')['last_play']['Period'],5)
    def test_review_is_original_only_and_does_not_modify_forecast(self):
        r=dict(id='pick',event_id='game',sport='NFL',strategy='Original',evidence='Published before kickoff',projected_yards=200,actual=240)
        before=dict(r);s=situation_snapshot(self.data())
        self.assertEqual(len(forecast_situation_reviews([r,dict(r,strategy='Cushion')],s)),1)
        self.assertEqual(r,before)
