"""Winner selection must not flip to an underdog because of its payout."""
import ast,sys,types,unittest,math
from pathlib import Path
from datetime import datetime,timezone,timedelta
from unittest.mock import patch

class WinnerPolicyTests(unittest.TestCase):
    def reviews(self,p,home_odds=-150,away_odds=141,include=False):
        source=ast.parse(Path('sportsbook_tools.py').read_text())
        nodes=[n for n in source.body if isinstance(n,ast.FunctionDef)and n.name in ('moneyline_reviews','numeric','implied','odds_text')]
        ns={'datetime':datetime,'timezone':timezone,'math':math}
        exec(compile(ast.Module(body=nodes,type_ignores=[]),'moneyline','exec'),ns)
        learning=types.ModuleType('pick_learning');learning.adjust_row=lambda row,p,*a,**k:p
        online=types.ModuleType('online_learning');online.adjust_probability=lambda row,p,*a,**k:p
        now=datetime(2026,10,22,tzinfo=timezone.utc)
        e={'home_team':'Bears','away_team':'Patriots','commence_time':(now+timedelta(hours=10)).isoformat(),'bookmakers':[{'title':'Fixture','markets':[{'key':'h2h','last_update':now.isoformat(),'outcomes':[{'name':'Bears','price':home_odds},{'name':'Patriots','price':away_odds}]}]}]}
        models={('Bears','Patriots'):{'eligible':True,'probability':p,'cutoff':'2026-10-18'}}
        with patch.dict(sys.modules,{'pick_learning':learning,'online_learning':online}):
            return ns['moneyline_reviews']([e],models,now,include_passes=include)
    def test_bears_selected_even_when_patriots_have_price_edge(self):
        rows=self.reviews(.51442139066812)
        self.assertEqual([r['Player'] for r in rows],['Bears'])
        self.assertLess(rows[0]['Estimated return per $1'],0)
    def test_changing_prices_cannot_change_predicted_winner(self):
        self.assertEqual([r['Player'] for r in self.reviews(.55,-1000,900)],['Bears'])
        self.assertEqual([r['Player'] for r in self.reviews(.45,900,-1000)],['Patriots'])
    def test_equal_probabilities_have_no_selected_winner(self):
        self.assertEqual(self.reviews(.5),[])
    def test_analysis_keeps_opposing_side_as_pass(self):
        rows=self.reviews(.52,include=True)
        self.assertEqual({r['Player']:r['Decision'] for r in rows},{'Bears':'Watch — experimental','Patriots':'Pass'})
