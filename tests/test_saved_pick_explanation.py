import copy
import unittest
from saved_pick_explanation import explanation, short_reason
class ExplanationTests(unittest.TestCase):
    def test_frozen_evidence_and_price(self):
        r=dict(player='QB',direction='Over',category='Passing attempts',line=35.5,odds=115,probability=.715,expected_opportunities=41.96,forecast_context={'Opportunity type':'Passing attempts'},reason='Five recent games')
        before=copy.deepcopy(r);e=explanation(r)
        self.assertIn('41.96 attempts',e['forecast'])
        self.assertIn('46.5%',e['price']);self.assertIn('+25.0',e['price'])
        self.assertEqual(r,before);self.assertIn('71.5%',short_reason(r))
    def test_missing_inputs_are_not_invented(self):
        e=explanation(dict(player='Manual',strategy='Manual'))
        self.assertIn('Not saved',e['forecast']);self.assertIn('No model probability',e['price'])
        self.assertIn('manual selection',e['risks'])
    def test_moneyline_not_given_yardage_forecast(self):
        self.assertIn('does not apply',explanation(dict(category='Moneyline'))['forecast'])
