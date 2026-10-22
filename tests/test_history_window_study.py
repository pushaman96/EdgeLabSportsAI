import copy,unittest
from datetime import date
from history_window_study import nba_normalize,prior_cohort,calibration_errors,evaluate,deterministic_sample
class HistoryWindowTests(unittest.TestCase):
    def raw(self,**changes):
        return dict(dict(season=2020,season_type=2,game_date=date(2020,8,1),game_id=1,athlete_id=1,team_id=1,minutes=30,points=20,rebounds=5,assists=4,three_point_field_goals_made=2,three_point_field_goals_attempted=5,did_not_play=False),**changes)
    def sample(self,year,i=0,**changes):
        return dict(dict(season=year,date=f'{year}-10-01',game=str(year)+'-'+str(i),player=str(i),projected=20.,baseline=19.,actual=21.,workload=30.,actual_workload=31.,uncertainty=1.2),**changes)
    def test_regular_season_identity_and_bubble_calendar(self):
        rows,n=nba_normalize([self.raw()],2020,'2021-01-01')
        self.assertEqual(len(rows),1);self.assertEqual(rows[0]['season'],2020)
        self.assertEqual(nba_normalize([self.raw(season_type=3)],2020,'2021-01-01')[0],[])
        self.assertEqual(nba_normalize([self.raw(season=2021)],2020,'2021-01-01')[0],[])
    def test_missing_dnp_or_future_not_zero(self):
        for row in (self.raw(minutes=None),self.raw(did_not_play=True),self.raw(points=None),self.raw(game_date=date(2027,1,1))):
            self.assertEqual(nba_normalize([row],2020,'2021-01-01')[0],[])
        self.assertEqual(nba_normalize([self.raw(points=0)],2020,'2021-01-01')[0][0]['PTS'],0)
    def test_duplicate_player_game_rejected(self):
        with self.assertRaises(ValueError):nba_normalize([self.raw(),self.raw()],2020,'2021-01-01')
    def test_historical_population_not_current_survivors_or_best_outcomes(self):
        old=[{'player':'retired'},{'player':'active'}]
        self.assertEqual(prior_cohort(old,'player',64),{'retired','active'})
        self.assertEqual(prior_cohort(old,'player',1),prior_cohort(list(reversed(old)),'player',1))
    def test_residual_windows_exclude_test_and_future_seasons(self):
        rows=[self.sample(y)for y in range(2016,2027)]
        long,n,years=calibration_errors(rows,2025,2016)
        recent,nr,ry=calibration_errors(rows,2025,2016,3)
        self.assertEqual(years,list(range(2016,2025)));self.assertEqual(ry,[2022,2023,2024])
        changed=[dict(r,actual=99999)if r['season']>=2025 else r for r in rows]
        self.assertEqual(calibration_errors(changed,2025,2016),(long,n,years))
    def test_sampling_never_selects_on_test_outcome(self):
        rows=[self.sample(2025,i)for i in range(200)]
        selected=[r['player']for r in deterministic_sample(rows,64)]
        self.assertEqual(selected,[r['player']for r in deterministic_sample([dict(r,actual=9999)for r in rows],64)])
    def test_equal_windows_or_no_data_cannot_claim_benefit(self):
        rows=[self.sample(y,i)for y in (2022,2023,2024,2025)for i in range(100)]
        result=evaluate(rows,2025,2022)
        self.assertFalse(result['benefit_supported']);self.assertEqual(result['longer_brier'],result['recent_brier'])
        self.assertFalse(evaluate([],2025,2016)['benefit_supported'])
    def test_target_outcome_changes_dont_change_calibration_or_input_rows(self):
        rows=[self.sample(y,i)for y in range(2016,2026)for i in range(25)];before=copy.deepcopy(rows)
        a=evaluate(rows,2025,2016);b=evaluate([dict(r,actual=1.)if r['season']==2025 else r for r in rows],2025,2016)
        self.assertEqual(a['longer_calibration_seasons'],b['longer_calibration_seasons'])
        self.assertEqual(a['longer_residual_sample'],b['longer_residual_sample']);self.assertEqual(rows,before)
        self.assertNotEqual(a['forecast_mae'],b['forecast_mae'])
    def test_moneyline_windows_compare_same_later_games(self):
        from history_window_study import team_compare
        from datetime import timedelta
        games=[]
        for year in range(2016,2026):
            for i in range(110):
                games.append(dict(date=date(year,1,1)+timedelta(days=i),season=year,home_team='A',away_team='B',home_score=100+i%2,away_score=99))
        result=team_compare(games,2025,2016)
        self.assertEqual(result['matched_games'],110)
        self.assertIsNotNone(result['longer']['brier']);self.assertIn('No sportsbook',result['scope'])
    def test_missing_team_seasons_cannot_claim_complete_study(self):
        from history_window_study import add_team_results
        from unittest.mock import patch
        import tempfile
        from pathlib import Path
        report={'generated_utc':'2026-10-22T00:00:00Z','sports':{'NBA':{'first_requested_season':2017,'last_completed_season':2026}}}
        with tempfile.TemporaryDirectory()as directory,patch('history_window_study.nba_team_games',side_effect=ValueError('Missing source')):
            result=add_team_results(report,Path(directory)/'report.json')
        self.assertEqual(result['sports']['NBA']['moneyline_history_results'],[])
        self.assertEqual(len(result['sports']['NBA']['team_result_coverage']['issues']),10)
