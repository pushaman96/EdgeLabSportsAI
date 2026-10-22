import unittest
from unittest.mock import patch
from nfl_season_prior import evaluated_row

class RemainingProbabilityRoutes(unittest.TestCase):
    def forecast(self):
        return dict(projected=60,opportunities=8,prior_games=17,current_games=6,current_weight=.6,cohort='established',role_uncertain=False,uncertainty=1,defense_status='Verified prior stats',coverage_gap=False)
    def test_season_prior_prediction_does_not_depend_on_payout(self):
        report=dict(residuals=[0]*25,passed=True)
        row=dict(Category='Receiving yards',Line=50.5,Selection='Over',Decision='Pass',Odds=-1000)
        with patch('nfl_season_prior.over_probability',return_value=.65):
            expensive=evaluated_row(row,self.forecast(),report)
            generous=evaluated_row(dict(row,Odds=300),self.forecast(),report)
        self.assertEqual(expensive['Decision'],'Watch — experimental')
        self.assertEqual(expensive['Decision'],generous['Decision'])
    def test_season_prior_failed_coverage_still_passes(self):
        row=dict(Category='Receiving yards',Line=50.5,Selection='Over',Decision='Pass',Odds=300)
        with patch('nfl_season_prior.over_probability',return_value=.85):
            result=evaluated_row(row,dict(self.forecast(),coverage_gap=True),dict(residuals=[0]*25,passed=True))
        self.assertEqual(result['Decision'],'Pass')
