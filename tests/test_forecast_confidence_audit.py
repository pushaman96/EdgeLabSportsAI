import unittest
from forecast_confidence_audit import build, errors

def record(**kwargs):
    return dict(dict(id='a',strategy='Original',evidence='Published before kickoff',season_type='Regular season',result='Loss',probability=.89,sport='NBA',event_id='e',category='Points',projected_count=13,actual=5,expected_opportunities=27,actual_opportunities=24),**kwargs)

class ConfidenceAuditTests(unittest.TestCase):
    def test_exclusions_and_duplicates(self):
        report=build([record(),record(),record(id='b',strategy='Cushion'),record(id='c',result='Pending'),record(id='d',evidence='Historical import')])
        self.assertEqual(report['bands'][0]['picks'],1)
        self.assertEqual(report['bands'][0]['wins'],0)
        self.assertAlmostEqual(report['bands'][0]['brier'],.89**2)
    def test_missing_stats_not_zero(self):
        result=errors(record(actual=None,actual_opportunities=None))
        self.assertIsNone(result['stat_error_actual_minus_forecast'])
        self.assertIsNone(result['workload_error_actual_minus_forecast'])
        self.assertNotIn('remaining_production_error',result)
    def test_error_decomposition(self):
        result=errors(record())
        self.assertAlmostEqual(result['workload_component_at_forecast_rate']+result['remaining_production_error'],-8)
    def test_correlated_picks_count_one_game(self):
        report=build([record(),record(id='b')])
        self.assertEqual(report['bands'][0]['picks'],2)
        self.assertEqual(report['bands'][0]['distinct_games'],1)
