import copy
import math
import unittest
from collections import defaultdict
from datetime import datetime,timezone
from nfl_passing_forecasts import beta_binomial,distribution,tail,estimate,validate,targets,evaluated_row
from pick_history import make_record,grade_record,restore_records
from live_pick_board import current_stat
from saved_pick_explanation import explanation,from_row
from pick_learning import diagnostics


def fixtures():
    players=[];teams=[]
    for year in (2024,2025):
        for week in range(1,19):
            for team in range(8):
                game=f'{year}-{week}-{team//2}';code='T'+str(team);opp='T'+str(team^1)
                attempts=30+week%4
                values=dict(season=year,week=week,game_id=game,team=code,opponent_team=opp,attempts=attempts,completions=20+week%3,passing_tds=1+week%2)
                teams.append(values)
                players.append(dict(values,player_id='qb'+str(team),player_display_name='QB '+str(team),position='QB'))
                players.append(dict(values,player_id='wr'+str(team),player_display_name='WR '+str(team),position='WR',attempts=0,completions=0,passing_tds=0,targets=6+week%3,receptions=4+week%2,receiving_yards=60+week))
    return players,teams


def indexes(players,teams):
    pi,ti,di=defaultdict(list),defaultdict(list),defaultdict(list)
    for r in players:pi[r['season'],r['player_id']].append(r)
    for r in teams:ti[r['season'],r['team']].append(r);di[r['season'],r['opponent_team']].append(r)
    return pi,ti,di


class CountForecastTests(unittest.TestCase):
    def setUp(self):
        self.players,self.teams=fixtures();self.idx=indexes(self.players,self.teams)
    def forecast(self,field='completions',idx=None):
        return estimate('qb0',2025,10,'T0','T1',idx or self.idx,field)
    def test_distribution_sums_to_one_and_expected_count_has_correct_mean(self):
        p=beta_binomial(30,.65,80)
        self.assertAlmostEqual(sum(p),1)
        self.assertAlmostEqual(sum(k*v for k,v in enumerate(p)),19.5)
        mixture=distribution([25,30,35],.1,40)
        self.assertAlmostEqual(sum(mixture),1)
        self.assertAlmostEqual(sum(k*v for k,v in enumerate(mixture)),3.)
        self.assertGreater(tail(mixture,.5),tail(mixture,2.5))
    def test_invalid_distribution_inputs_are_rejected(self):
        for args in ((-1,.5,20),(30,0,20),(30,1,20),(30,.5,0),(30.5,.5,20)):
            with self.assertRaises(ValueError):beta_binomial(*args)
    def test_completions_and_td_forecasts_have_physical_bounds(self):
        for field in ('completions','passing_tds'):
            f,reason=self.forecast(field)
            self.assertIsNotNone(f,reason)
            self.assertTrue(0<=f['expected']<=f['attempts'])
            self.assertTrue(f['low']<=f['high'])
            self.assertAlmostEqual(tail(f['pmf'],1.5)+(1-tail(f['pmf'],1.5)),1)
    def test_current_week_and_future_outcomes_cannot_change_estimate(self):
        players=[dict(r,completions=0,passing_tds=0,attempts=70) if (r['season'],r['week'])>=(2025,10) else r for r in self.players]
        teams=[dict(r,completions=0,passing_tds=0,attempts=70) if (r['season'],r['week'])>=(2025,10) else r for r in self.teams]
        self.assertEqual(self.forecast(),self.forecast(idx=indexes(players,teams)))
    def test_missing_counts_and_recent_team_coverage_do_not_become_zero(self):
        players=[dict(r,completions=None) if r['player_id']=='qb0' else r for r in self.players]
        self.assertIsNone(self.forecast(idx=indexes(players,self.teams))[0])
        players=[r for r in self.players if not(r['player_id']=='qb0' and r['season']==2025 and r['week']==9)]
        self.assertIsNone(self.forecast(idx=indexes(players,self.teams))[0])
    def test_validation_is_grouped_by_games_and_reports_fixed_benchmarks(self):
        reports=validate(self.players,self.teams)
        r=reports['completions']
        self.assertGreater(r['forecasts'],r['distinct_games'])
        self.assertIn('not historical sportsbook',r['scope'])
        self.assertEqual(r['passed'],r['forecasts']>=100 and r['distinct_games']>=50 and r['mae']<r['baseline_mae'] and r['benchmark_brier']<min(.25,r['frequency_baseline_brier']))
    def test_validation_season_outcomes_cannot_select_blend_weight(self):
        first=validate(self.players,self.teams)
        altered=[dict(r,completions=0,passing_tds=0) if r['season']==2025 and r['position']=='QB' else r for r in self.players]
        changed=validate(altered,self.teams)
        for field in ('completions','passing_tds'):
            self.assertEqual(first[field]['frequency_weight'],changed[field]['frequency_weight'])
            self.assertEqual(first[field]['tuning_season'],2024)

    def test_failed_validation_retains_research_forecast_and_pass(self):
        f,_=self.forecast()
        now=datetime(2026,10,19,tzinfo=timezone.utc)
        row={'Category':'Passing completions','Selection':'Over','Line':20.5,'Odds':-110,'Decision':'Pass'}
        result=evaluated_row(row,f,{'passed':False},now)
        self.assertEqual(result['Decision'],'Pass')
        self.assertIsNotNone(result['Estimated win %'])
        self.assertNotIn('Projection (yards)',result)
        self.assertEqual(row['Decision'],'Pass')
    def test_targets_use_team_attempts_share_and_catch_rate(self):
        f=targets('wr0',2025,10,'T0','T1',self.idx)
        self.assertAlmostEqual(f['targets'],f['team_attempts']*f['target_share'])
        self.assertAlmostEqual(f['receptions'],f['targets']*f['catch_rate'])
        self.assertAlmostEqual(f['receiving_yards'],f['receptions']*f['yards_per_catch'])
        self.assertIn('not a quoted target bet',f['scope'])
        modified=[dict(r,targets=999,receptions=999) if r['season']==2025 and r['week']>=10 and r['player_id']=='wr0' else r for r in self.players]
        self.assertEqual(f,targets('wr0',2025,10,'T0','T1',indexes(modified,self.teams)))
    def test_target_missing_or_impossible_stats_block_breakdown(self):
        players=[dict(r,targets=None) if r['player_id']=='wr0' else r for r in self.players]
        self.assertIsNone(targets('wr0',2025,10,'T0','T1',indexes(players,self.teams)))


class PassingGradingExplanationTests(unittest.TestCase):
    def record(self,category):
        return dict(id='r',event_id='g',player='QB',sport='NFL',category=category,result='Pending',direction='Over',line=20.5 if category=='Passing completions' else 1.5,odds=-110,expected_opportunities=35,projected_count=23 if category=='Passing completions' else 1.8,forecast_context={'Opportunity type':'Passing attempts','Conversion rate %':65.,'Historical error range low':15,'Historical error range high':28,'Range method':'10th–90th percentiles of count distribution'})
    def data(self):
        return {'header':{'id':'g','competitions':[{'status':{'type':{'completed':True}}}]},'boxscore':{'players':[{'statistics':[{'name':'passing','labels':['C/ATT','TD'],'athletes':[{'athlete':{'displayName':'QB'},'stats':['24/36','2']}]}]}]}}
    def test_completions_use_numerator_attempts_use_denominator(self):
        data=self.data()
        for category,expected in [('Passing completions',24),('Passing attempts',36),('Passing touchdowns',2)]:
            record=self.record(category)
            self.assertEqual(current_stat(record,data),expected)
            graded=grade_record(record,data)
            self.assertEqual(graded['actual'],expected)
            self.assertEqual(graded['actual_opportunities'],36)
            self.assertEqual(graded['result'],'Win')
    def test_quote_direction_and_probability_respect_validation_and_price(self):
        players,teams=fixtures()
        f,_=estimate('qb0',2025,10,'T0','T1',indexes(players,teams),'completions')
        now=datetime(2026,10,19,tzinfo=timezone.utc)
        row={'Category':'Passing completions','Selection':'Over','Line':.5,'Odds':-110,'Decision':'Pass'}
        result=evaluated_row(row,f,{'passed':True,'frequency_weight':.75},now)
        self.assertEqual(result['Decision'],'Watch — experimental')
        self.assertTrue(5<=result['Estimated win %']<=95)
        self.assertIn('frequency weight 0.75',result['Probability method'])
        reverse=evaluated_row(dict(row,Selection='Under'),f,{'passed':True,'frequency_weight':.75},now)
        self.assertAlmostEqual(result['Estimated win %']+reverse['Estimated win %'],100)
        self.assertEqual(reverse['Decision'],'Pass')

    def test_missing_player_stat_remains_pending(self):
        data=self.data();data['boxscore']['players'][0]['statistics'][0]['athletes']=[]
        self.assertEqual(grade_record(self.record('Passing touchdowns'),data)['result'],'Pending')
    def test_count_workload_efficiency_misses_sum_to_total(self):
        r=grade_record(self.record('Passing completions'),self.data())
        d=diagnostics([r])[0]
        self.assertAlmostEqual(d['Workload contribution']+d['Efficiency contribution'],d['Forecast miss'])
    def test_saved_explanation_contains_equation_range_and_price(self):
        record=self.record('Passing completions');record.update(probability=.6,reason='Price edge')
        original=copy.deepcopy(record);e=explanation(record)
        self.assertIn('35 expected passing attempts',e['calculation'])
        self.assertIn('65.00%',e['calculation'])
        self.assertIn('15–28 completions',e['uncertainty'])
        self.assertIn('inside this range',e['uncertainty'])
        self.assertIn('not a guaranteed cushion',e['comparison'])
        self.assertIn('52.4%',e['price'])
        self.assertEqual(record,original)
    def test_supporting_target_calculation_not_presented_as_selected_prediction(self):
        r=self.record('Receptions');r['forecast_context']['Target breakdown']=dict(team_attempts=35,target_share=.2,targets=7,catch_rate=.7,receptions=4.9)
        e=explanation(r)
        self.assertIn('7 targets',e['calculation'])
        self.assertIn('does not replace',e['calculation'])
    def test_missing_inputs_do_not_generate_explanations_of_invented_facts(self):
        e=from_row({'Player':'QB','Category':'Passing touchdowns','Decision':'Pass','Reason':'No history'})
        self.assertIn('not saved',e['calculation'])
        self.assertIn('No history',e['reason'])
        self.assertIn('not saved',e['validation'])
    def test_new_categories_can_be_frozen_and_restored(self):
        now=datetime(2026,10,19,tzinfo=timezone.utc)
        for category in ('Passing completions','Passing touchdowns'):
            row={'Player':'QB','Game':'Away at Home','Category':category,'Decision':'Watch — experimental','Selection':'Over','Line':20.5,'Odds':-110,'Estimated win %':60,'Sportsbook':'Book','Model':'fixture','Quote updated UTC':now.isoformat(),'Conversion rate %':65,'Projection (count)':23}
            r=make_record(row,'g','2026-10-20T00:00:00Z',now)
            self.assertEqual(restore_records({'records':[r]})[0]['category'],category)
            self.assertEqual(r['forecast_context']['Conversion rate %'],65)


if __name__=='__main__':unittest.main()


class PassingRouteIntegrationTests(unittest.TestCase):
    def test_count_markets_traverse_real_roster_history_and_grading_path(self):
        try:
            import nfl_prop_model
        except ModuleNotFoundError:
            self.skipTest('Optional Streamlit runtime not installed; pure forecast/grading tests run separately')
        players,teams=fixtures()
        now=datetime(2025,11,5,20,tzinfo=timezone.utc);start='2025-11-06T20:00:00Z'
        event=dict(away_team='Team 1',home_team='Team 0',commence_time=start,bookmakers=[dict(title='Book',markets=[dict(key='player_pass_completions',last_update=now.isoformat(),outcomes=[dict(description='QB 0',name='Over',point=20.5,price=-110)]),dict(key='player_pass_tds',last_update=now.isoformat(),outcomes=[dict(description='QB 0',name='Over',point=1.5,price=-110)])])])
        competitors=[dict(homeAway='home',team=dict(displayName='Team 0',abbreviation='T0',id='0')),dict(homeAway='away',team=dict(displayName='Team 1',abbreviation='T1',id='1'))]
        scoreboard=dict(events=[dict(date=start,season=dict(year=2025,type=2),competitions=[dict(competitors=competitors)])])
        schedule=[]
        for week in range(1,11):
            from datetime import timedelta
            date=(datetime(2025,11,6)-timedelta(days=7*(10-week))).date().isoformat()
            schedule.append(dict(season='2025',week=str(week),game_type='REG',home_team='T0',away_team='T1',gameday=date,game_id=f'2025-{week}-0',home_score='20',away_score='10'))
        research=dict(players=players,teams=teams,schedule=schedule,models={},passing_count_reports={'completions':{'passed':True,'frequency_weight':.75},'passing_tds':{'passed':False,'frequency_weight':.75}})
        injuries=dict(teams={'Team 0','Team 1'},statuses={},retrieved=now.isoformat(),source_updated=now.isoformat(),season=2025)
        rosters={'Team 0':[dict(name='QB 0',position='QB',status='Active')],'Team 1':[]}
        rows=nfl_prop_model.prop_reviews(event,scoreboard,research,injuries,rosters,now)
        self.assertEqual({r['Category'] for r in rows},{'Passing completions','Passing touchdowns'})
        self.assertTrue(all(r.get('Projection (count)') is not None for r in rows),rows)
        self.assertTrue(all(r.get('Evidence explanation') for r in rows))
        self.assertEqual(next(r for r in rows if r['Category']=='Passing touchdowns')['Decision'],'Pass')
