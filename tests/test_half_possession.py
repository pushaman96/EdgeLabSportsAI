import copy,unittest
from half_possession import half_possession
class HalfPossessionTests(unittest.TestCase):
    def data(self):return {'header':{'competitions':[{'competitors':[{'team':{'id':'a','displayName':'Away'}},{'team':{'id':'h','displayName':'Home'}}]}]},'drives':{'previous':[]}}
    def kickoff(self,period=1,kicker='a',possessor='h',ident='one',text='Kickoff return'):
        return {'id':ident,'sequenceNumber':'1' if period==1 else '100','type':{'text':'Kickoff'},'period':{'number':period},'clock':{'displayValue':'15:00'},'start':{'team':{'id':kicker}},'end':{'team':{'id':possessor}},'text':text}
    def test_opening_and_unconfirmed_half_expectation(self):
        d=self.data();d['drives']['previous']=[{'plays':[self.kickoff()]}];before=copy.deepcopy(d)
        result=half_possession(d)
        self.assertEqual(result['Opening possession'],'Home')
        self.assertEqual(result['Second-half start'],'Expected: Away — unconfirmed')
        self.assertFalse(result['Second-half confirmed']);self.assertEqual(d,before)
    def test_actual_second_half_overrides_expectation(self):
        d=self.data();d['drives']['previous']=[{'plays':[self.kickoff(),self.kickoff(3,'a','h','two')]}]
        result=half_possession(d)
        self.assertEqual(result['Second-half start'],'Confirmed: Home')
        self.assertTrue(result['Second-half confirmed'])
    def test_onside_and_missing_feed_are_not_guessed(self):
        d=self.data();self.assertEqual(half_possession(d)['Opening possession'],'Not reported')
        d['drives']['previous']=[{'plays':[self.kickoff(text='Onside kick recovered by Home')]}]
        self.assertEqual(half_possession(d)['Second-half start'],'Not confirmed')
    def test_later_kickoff_is_not_the_opener(self):
        d=self.data();p=self.kickoff();p['clock']['displayValue']='09:00'
        d['drives']['previous']=[{'plays':[p]}]
        self.assertEqual(half_possession(d)['Opening possession'],'Not reported')
    def test_current_drive_and_duplicate_plays(self):
        d=self.data();p=self.kickoff();d['drives']={'previous':[{'plays':[p]}],'current':{'plays':[p]}}
        self.assertEqual(half_possession(d)['Opening possession'],'Home')
