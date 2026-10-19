import copy
import unittest
from datetime import datetime, timedelta, timezone
from online_learning import build_state, adjust_forecast, adjust_probability
from pick_learning import diagnostics


class OnlineLearningTests(unittest.TestCase):
    now = datetime(2026, 10, 19, tzinfo=timezone.utc)

    def record(self, **updates):
        row = dict(id='p', event_id='g', sport='NFL', model='fixture', player='QB', category='Passing yards', direction='Under', line=220.5, strategy='Original', season_type='Regular season', evidence='Personal paper record', published_utc='2026-10-18T15:00:00Z', starts_utc='2026-10-18T17:00:00Z', graded_utc='2026-10-18T21:00:00Z', probability=.8, result='Loss', projected_yards=200, expected_opportunities=30, actual_opportunities=40, actual=300)
        row.update(updates)
        return row

    def forecast(self):
        return dict(Model='fixture', Category='Passing yards', Selection='Under')

    def test_first_game_changes_next_forecast_and_probability(self):
        records=[self.record()];before=copy.deepcopy(records)
        state=build_state(records,self.now);row=self.forecast()
        projected,workload=adjust_forecast(row,200,30,self.now,state)
        self.assertGreater(projected,200);self.assertGreater(workload,30)
        self.assertLess(adjust_probability(row,.8,self.now,state),.8)
        self.assertEqual(records,before)
        self.assertEqual(row['Base projection'],200)

    def test_duplicate_quotes_directions_and_reruns_do_not_multiply_updates(self):
        original=[self.record()]
        duplicates=original+[self.record(id='q',line=250.5),self.record(id='other',direction='Over')]
        a=build_state(original,self.now);b=build_state(duplicates,self.now)
        self.assertEqual(a,b)
        self.assertEqual(a,build_state(original,self.now))

    def test_late_missing_import_manual_and_unsettled_do_not_train(self):
        changes=[dict(evidence='Historical import'),dict(strategy='Manual'),dict(strategy='Cushion'),dict(result='Pending'),dict(published_utc=None),dict(published_utc='2026-10-18T18:00:00Z'),dict(graded_utc='2026-10-20T00:00:00Z')]
        for change in changes:
            self.assertFalse(build_state([self.record(**change)],self.now)['groups'],change)

    def test_future_and_stale_state_cannot_influence_forecast(self):
        state=build_state([self.record()],self.now)
        for moment in (self.now-timedelta(days=1),self.now+timedelta(days=31)):
            self.assertEqual(adjust_forecast(self.forecast(),200,30,moment,state),(200,30))

    def test_updates_are_bounded_and_sports_models_categories_separate(self):
        records=[]
        for n in range(100):
            start=self.now-timedelta(days=101-n)
            records.append(self.record(event_id=str(n),published_utc=(start-timedelta(hours=1)).isoformat(),starts_utc=start.isoformat(),graded_utc=(start+timedelta(hours=4)).isoformat(),actual=100000))
        state=build_state(records,self.now)
        predicted,_=adjust_forecast(self.forecast(),200,30,self.now,state)
        self.assertLessEqual(predicted,230)
        self.assertEqual(adjust_forecast(self.forecast(),200,30,self.now,state,sport='NBA'),(200,30))
        self.assertEqual(adjust_forecast(dict(Model='new-model',Category='Passing yards'),200,30,self.now,state),(200,30))
        self.assertEqual(adjust_forecast(dict(Model='fixture',Category='Rushing yards'),200,30,self.now,state),(200,30))

    def test_moneyline_opposing_probabilities_remain_complementary(self):
        state=build_state([self.record(category='Moneyline')],self.now)
        row=dict(Model='fixture',Category='Moneyline')
        a=adjust_probability(dict(row),.8,self.now,state)
        b=adjust_probability(dict(row),.2,self.now,state)
        self.assertAlmostEqual(a+b,1)

    def test_baseline_not_previous_adjusted_projection_is_learning_target(self):
        state=build_state([self.record(base_projection=200,projected_yards=250)],self.now)
        comparison=build_state([self.record(projected_yards=200)],self.now)
        self.assertEqual(state,comparison)

    def test_workload_efficiency_contributions_sum_to_forecast_miss(self):
        d=diagnostics([self.record()])[0]
        self.assertAlmostEqual(d['Workload contribution']+d['Efficiency contribution'],d['Forecast miss'])
        missing=diagnostics([self.record(actual_opportunities=None)])[0]
        self.assertIsNone(missing['Efficiency contribution'])

    def test_only_actually_issued_updates_count_as_comparison(self):
        state=build_state([self.record(online_version='v',base_probability=.8,probability=.7)],self.now)
        group=next(iter(state['groups'].values()))
        self.assertEqual(group['issued_comparisons'],1)
        self.assertAlmostEqual(group['base_brier_sum'],.64)
        self.assertAlmostEqual(group['issued_brier_sum'],.49)
        original=next(iter(build_state([self.record()],self.now)['groups'].values()))
        self.assertEqual(original['issued_comparisons'],0)


if __name__=='__main__':
    unittest.main()
