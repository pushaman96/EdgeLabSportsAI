import copy,unittest
from probability_order import highest_probability
class ProbabilityOrderTests(unittest.TestCase):
    def test_probability_not_price_edge_controls_order(self):
        rows=[{'id':'value','Estimated win %':55,'edge':20},{'id':'likely','Estimated win %':75,'edge':6},{'id':'middle','Estimated win %':65,'edge':9}]
        before=copy.deepcopy(rows)
        self.assertEqual([r['id'] for r in highest_probability(rows,'Estimated win %')],['likely','middle','value'])
        self.assertEqual(rows,before)
    def test_unknown_and_invalid_probabilities_last(self):
        rows=[{'id':'none','probability':None},{'id':'valid','probability':.6},{'id':'bad','probability':float('nan')},{'id':'bool','probability':True}]
        self.assertEqual(highest_probability(rows,'probability')[0]['id'],'valid')
    def test_pass_cannot_outrank_a_qualifying_pick(self):
        rows=[{'id':'pass','Decision':'Pass','Estimated win %':90},{'id':'pick','Decision':'Watch','Estimated win %':60}]
        self.assertEqual(highest_probability(rows,'Estimated win %','Decision')[0]['id'],'pick')
    def test_ties_are_stable(self):
        rows=[{'id':'a','probability':.6},{'id':'b','probability':.6}]
        self.assertEqual(highest_probability(rows,'probability'),rows)
