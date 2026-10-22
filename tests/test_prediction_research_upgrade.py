import copy
import math
import unittest
from datetime import date,timedelta
from selection_policy import annotate,apply,price_probability
from nba_opportunity import estimate
from forecast_benchmark import probability,validate
from matchup_homework import nba_facts,profiles,dossier


class ProbabilityUnitTests(unittest.TestCase):
    def row(self,**changes):
        return dict({'Decision':'Watch — experimental','Estimated win %':65,'Odds':-110},**changes)
    def test_probability_and_price_percentages_are_separate(self):
        row=annotate(self.row())
        self.assertEqual(row['Estimated loss %'],35)
        self.assertAlmostEqual(row['Break-even %'],52.38,places=2)
        self.assertAlmostEqual(row['Model edge (pp)'],12.62,places=2)
        self.assertAlmostEqual(row['Expected return per unit'],.65/(110/210)-1)
        self.assertAlmostEqual(price_probability(200),1/3)
    def test_low_probability_payout_does_not_qualify_main_shortlist(self):
        row=apply([self.row(**{'Estimated win %':40,'Odds':250})])[0]
        self.assertEqual(row['Decision'],'Watch — experimental')
        self.assertFalse(row['Value research eligible'])
        self.assertFalse(row['Main shortlist eligible'])
        self.assertNotIn('high',row['Probability tier'].lower())
    def test_bad_percentages_and_odds_do_not_create_valid_probability(self):
        for value in (None,float('nan'),float('inf'),0,100,True):
            row=annotate(self.row(**{'Estimated win %':value}))
            self.assertIsNone(row['Estimated loss %'])
        # .65 in a percent field is .65%, never silently multiplied to 65%.
        self.assertAlmostEqual(annotate(self.row(**{'Estimated win %':.65}))['Estimated loss %'],99.35)
        for odds in (0,99,-99,True,None):self.assertIsNone(price_probability(odds))
    def test_probability_monotonicity_and_complement(self):
        errors=[(i-50)/10 for i in range(100)]
        ps=[probability(20,line,errors,.75)for line in (10.5,20.5,30.5)]
        self.assertGreater(ps[0],ps[1]);self.assertGreater(ps[1],ps[2])
        self.assertAlmostEqual(ps[0]+(1-ps[0]),1)
        self.assertIsNone(probability(20,20.5,[]))


class OpportunityTests(unittest.TestCase):
    def rows(self,n=30,year=2026,start='2025-11-01',**changes):
        rows=[]
        for i in range(n):
            row=dict(player='p',name='Player',team='A',season=year,date=(date.fromisoformat(start)+timedelta(days=i)).isoformat(),game=str(year)+'-'+str(i),minutes=30,
                     FGM=8,FGA=16,FG3M=2,FG3A=6,FTM=4,FTA=5,PTS=22,REB=6,AST=5)
            row.update(changes);rows.append(row)
        return rows
    def test_attempts_and_conversion_produce_points_and_joint_pra(self):
        row=estimate(self.rows(),2027,'A','2026-10-21')
        shots=row['shots'];points=2*shots['Two-point attempts']['made']+3*shots['Three-point attempts']['made']+shots['Free-throw attempts']['made']
        self.assertAlmostEqual(row['values']['PTS'],points)
        self.assertAlmostEqual(row['values']['PRA'],points+row['values']['REB']+row['values']['AST'])
        self.assertEqual(row['minutes'],30)
        self.assertAlmostEqual(shots['Three-point attempts']['attempts'],6)
    def test_future_stats_cannot_change_forecast_and_records_are_frozen(self):
        rows=self.rows();before=copy.deepcopy(rows)
        first=estimate(rows,2027,'A','2026-10-21')
        future=self.rows(year=2027,start='2026-10-21',PTS=999,minutes=1)
        self.assertEqual(first,estimate(rows+future,2027,'A','2026-10-21'))
        self.assertEqual(rows,before)
    def test_shot_volume_changes_without_relying_only_on_stat_average(self):
        rows=self.rows();current=self.rows(5,2027,'2026-10-21',FG3A=12)
        before=estimate(rows,2027,'A','2026-11-01')
        after=estimate(rows+current,2027,'A','2026-11-01')
        self.assertGreater(after['shots']['Three-point attempts']['attempts'],before['shots']['Three-point attempts']['attempts'])
    def test_missing_shooting_and_changed_team_do_not_invent_volume(self):
        rows=self.rows(FGA=None)
        self.assertIsNone(estimate(rows,2027,'A','2026-10-21')['values']['PTS'])
        self.assertIsNone(estimate(self.rows(),2027,'NEW','2026-10-21'))
        self.assertIsNone(estimate(self.rows(n=7),2027,'A','2026-10-21'))


class ChronologicalBenchmarkTests(unittest.TestCase):
    def samples(self):
        return [dict(date=(date(year-1,10,1)+timedelta(days=i)).isoformat(),season=year,game=f'{year}-{i}',
                     candidate=20.,base=22.,baseline=24.,actual=20.+(i%3-1),workload=30.,base_workload=31.,actual_workload=30.)
                for year in (2025,2026)for i in range(100)]
    def test_separate_residual_temperature_and_later_test_windows(self):
        result=validate(self.samples())
        self.assertLess(result['calibration_through'],result['validation_from'])
        self.assertEqual(result['validation_games'],100)
        self.assertEqual(result['calibration_examples'],70)
        self.assertEqual(result['temperature_games'],30)
        self.assertIn('no historical sportsbook',result['scope'].lower())
    def test_later_outcomes_cannot_change_fitted_temperature_or_errors(self):
        rows=self.samples();a=validate(rows)
        rows=[dict(r,actual=1000)if r['season']==2026 else r for r in rows]
        b=validate(rows)
        self.assertEqual(a['temperature'],b['temperature'])
        self.assertEqual(a['residuals'],b['residuals'])
        self.assertFalse(b['passed'])
    def test_tied_baseline_and_tiny_samples_never_promote(self):
        tied=[dict(r,candidate=r['base'],baseline=r['base'])for r in self.samples()]
        self.assertFalse(validate(tied)['passed'])
        self.assertFalse(validate(self.samples()[:5])['passed'])
    def test_repeating_players_does_not_inflate_game_count(self):
        rows=self.samples();one=validate(rows);many=validate(rows*4)
        self.assertEqual(one['validation_games'],many['validation_games'])
        self.assertAlmostEqual(one['candidate_brier'],many['candidate_brier'],places=2)


class HomeworkTests(unittest.TestCase):
    def test_missing_facts_stay_unknown_and_neutral(self):
        row=nba_facts([],'2026-10-21T23:00:00Z','A','B','PTS')
        self.assertFalse(row['complete_matchup'])
        self.assertEqual(row['candidate_factor'],1)
        self.assertIsNone(row['opponent_stat_allowed_per48'])
    def test_facts_distinguish_applied_inputs_from_research(self):
        d=dossier({'Opportunity model applied':False},'NBA')
        self.assertIn('incumbent retained',d['factors'][1]['Effect'])
        self.assertIn('opponent feature',dossier({},'NFL')['factors'][1]['Effect'])
