import copy
import unittest
from nfl_season_prior import estimate,indexes,validate,evaluated_row,over_probability

class NflSeasonPriorTests(unittest.TestCase):
    def fixture(self):
        players=[];teams=[]
        for year in (2023,2024,2025):
            for week in range(1,18):
                for code,opponent in (('A','B'),('B','A')):
                    g=f'{year}-{week}'
                    r=dict(season=year,week=week,game_id=g,team=code,opponent_team=opponent,player_id=code,player_display_name=code,position='QB',passing_yards=240,attempts=30,rushing_yards=40,carries=10,receiving_yards=50,targets=6,receptions=4,completions=20,passing_tds=2,passing_interceptions=1)
                    players.append(r);teams.append(dict(r))
        return players,teams
    def test_week_one_uses_last_season(self):
        p,t=self.fixture();f=estimate('A',2026,1,'A','B','player_pass_yds',indexes(p,t))
        self.assertEqual(f['projected'],240);self.assertEqual(f['current_games'],0)
        self.assertEqual(f['current_weight'],0);self.assertFalse(f['coverage_gap']);self.assertGreater(f['uncertainty'],1)
    def test_new_season_gradual_weight_and_no_future_leak(self):
        p,t=self.fixture();now=dict(p[-2],season=2026,week=1,game_id='new',passing_yards=300)
        p.append(now);t.append(dict(now));f=estimate('A',2026,2,'A','B','player_pass_yds',indexes(p,t))
        self.assertEqual(f['current_weight'],.2)
        future=dict(now,week=2,game_id='future',passing_yards=99999)
        self.assertEqual(f,estimate('A',2026,2,'A','B','player_pass_yds',indexes(p+[future],t+[future])))
        self.assertGreater(f['projected'],240);self.assertLess(f['projected'],300)
    def test_gap_never_turns_missing_game_into_zero(self):
        p,t=self.fixture();r=dict(t[-2],season=2026,week=1,game_id='missing');t.append(r)
        f=estimate('A',2026,2,'A','B','player_pass_yds',indexes(p,t))
        self.assertTrue(f['coverage_gap']);self.assertEqual(f['projected'],240)
        row=evaluated_row(self.row(),f,dict(passed=True,residuals=[0]*60))
        self.assertEqual(row['Decision'],'Pass');self.assertIn('coverage gap',row['Reason'])
    def test_trade_retains_prior_but_does_not_assert_new_role(self):
        p,t=self.fixture();f=estimate('A',2026,1,'NEW','B','player_pass_yds',indexes(p,t))
        self.assertTrue(f['role_uncertain'])
        row=evaluated_row(self.row(),f,dict(passed=True,residuals=[0]*60))
        self.assertEqual(row['Decision'],'Pass');self.assertIn('New-team role',row['Reason'])
    def test_rookie_has_no_fabricated_prior(self):
        p,t=self.fixture();self.assertIsNone(estimate('rookie',2026,1,'A','B','player_pass_yds',indexes(p,t)))
    def row(self):return {'Decision':'Pass','Category':'Passing yards','Selection':'Over','Line':100.5,'Odds':-110}
    def test_failed_validation_shows_estimate_not_pick(self):
        p,t=self.fixture();f=estimate('A',2026,1,'A','B','player_pass_yds',indexes(p,t))
        row=evaluated_row(self.row(),f,dict(passed=False,residuals=[0]*60))
        self.assertEqual(row['Decision'],'Pass');self.assertEqual(row['Projection (yards)'],240)
        self.assertIn('research projection',row['Reason'])
    def test_direction_probabilities_complement_and_cushion_recalculates(self):
        p,t=self.fixture();f=estimate('A',2026,1,'A','B','player_pass_yds',indexes(p,t));report=dict(passed=True,residuals=list(range(-30,30)))
        a=evaluated_row(self.row(),f,report);b=evaluated_row(dict(self.row(),Selection='Under'),f,report)
        self.assertAlmostEqual(a['Estimated win %']+b['Estimated win %'],100)
        self.assertGreaterEqual(over_probability(240,150.5,report),over_probability(240,250.5,report))
    def test_validation_uses_only_2024_then_2025_and_baseline_ties_fail(self):
        p,t=self.fixture();before=copy.deepcopy(p);r=validate(p,t)
        self.assertEqual(p,before)
        report=r['player_pass_yds','Early season (0–3 appearances)']
        self.assertEqual(report['training_season'],2024);self.assertEqual(report['validation_season'],2025)
        self.assertFalse(report['passed']);self.assertAlmostEqual(report['forecast_mae'],report['baseline_mae'])
        future=dict(p[-2],season=2026,passing_yards=99999)
        self.assertEqual(r,validate(p+[future],t+[future]))

if __name__=='__main__':unittest.main()
