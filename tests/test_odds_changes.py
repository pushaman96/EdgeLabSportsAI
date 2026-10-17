import copy
import unittest
from odds_changes import changes, estimated_credits
class OddsChangesTests(unittest.TestCase):
    def event(self,line=200.5,price=-110):return {'id':'game','home_team':'Home','away_team':'Away','bookmakers':[{'key':'book','title':'Book','markets':[{'key':'player_pass_yds','outcomes':[{'description':'QB','name':'Over','point':line,'price':price}]}]}]}
    def test_estimate_unique_markets(self):self.assertEqual(estimated_credits(10,'a,b,a'),20)
    def test_detects_movement_from_snapshots_without_requests(self):
        old=[self.event()];frozen=copy.deepcopy(old)
        diff=changes(old,[self.event(210.5,-115)])
        self.assertEqual(len(diff),1);self.assertEqual(diff[0]['Previous line'],200.5)
        self.assertEqual(old,frozen)
    def test_identical_or_missing_quotes_not_invented_movement(self):
        self.assertEqual(changes([self.event()],[self.event()]),[])
        self.assertEqual(changes([self.event()],[]),[])
