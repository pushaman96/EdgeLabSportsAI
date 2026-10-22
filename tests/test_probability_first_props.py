import ast,math,re,unittest
from collections import defaultdict
from pathlib import Path
from selection_policy import annotate

class ProbabilityFirstTests(unittest.TestCase):
    def shortlist(self,rows):
        nodes=[n for n in ast.parse(Path('nfl_prop_model.py').read_text()).body if isinstance(n,ast.FunctionDef)and n.name=='clear_prop_shortlist']
        ns={'defaultdict':defaultdict,'num':lambda x:float(x)if x is not None else None,'name_key':lambda x:x.lower()}
        exec(compile(ast.Module(body=nodes,type_ignores=[]),'shortlist','exec'),ns)
        return ns['clear_prop_shortlist'](rows)
    def row(self,side,p,odds):
        return dict(Game='Game',Player='Player',Category='Receiving yards',Selection=side,Line=50.5,Odds=odds,Sportsbook='Fixture',Decision='Watch — experimental',Reason='Validated',**{'Estimated win %':p,'Model edge (pp)':99,'Projection (yards)':60})
    def test_low_probability_payout_cannot_enter_main_shortlist(self):
        self.assertFalse(annotate(self.row('Over',40,400))['Main shortlist eligible'])
    def test_high_probability_does_not_require_profitable_price(self):
        self.assertTrue(annotate(self.row('Over',70,-1000))['Main shortlist eligible'])
    def test_retain_highest_probability_not_highest_payout(self):
        rows=[self.row('Over',70,-500),self.row('Over',60,300)]
        self.assertEqual(self.shortlist(rows)[0]['Estimated win %'],70)
    def test_choose_more_likely_direction_across_loaded_lines(self):
        rows=[self.row('Over',70,-500),self.row('Under',60,300)]
        self.assertEqual(self.shortlist(rows)[0]['Selection'],'Over')
    def test_exact_tie_opposing_directions_is_pass(self):
        self.assertEqual(self.shortlist([self.row('Over',60,-110),self.row('Under',60,300)])[0]['Decision'],'Pass')
    def test_failed_validation_is_not_promoted(self):
        row=self.row('Over',90,200);row['Decision']='Pass'
        self.assertFalse(annotate(row)['Main shortlist eligible'])
