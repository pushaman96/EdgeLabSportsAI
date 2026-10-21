import copy
import unittest
from nba_role_usage import role_usage,attach_role_usage,saved_role_reviews
from pick_learning import diagnostics
from test_nba_game_context import game


class RoleTests(unittest.TestCase):
    def history(self,starter=True,minutes='32',n=4):
        rows=[]
        for i in range(n):
            data=game(str(i),day=f'2026-10-{i+1:02}T02:00:00Z')
            athlete=data['boxscore']['players'][0]['statistics'][0]['athletes'][0]
            athlete['starter']=starter;athlete['stats'][0]=minutes
            rows.append(data)
        return rows
    def test_starter_minutes_scenario_and_shots_do_not_change_original_forecast(self):
        context={'history':self.history()};before=copy.deepcopy(context)
        row={'Starting lineup check':{'Starter':True},'Selection':'Under','Line':15.5,'Estimated win %':74.7,'Projection (count)':11.91}
        attach_role_usage(row,context,'2026-10-20T02:00:00Z','1','Target',22.67,11.91,'PTS')
        self.assertEqual(row['NBA role usage']['Candidate minutes'],32)
        self.assertAlmostEqual(row['NBA role usage']['Candidate FGA'],16)
        self.assertTrue(row['NBA role review required'])
        self.assertEqual(row['Projection (count)'],11.91);self.assertEqual(row['Estimated win %'],74.7)
        self.assertEqual(context,before)
    def test_new_starter_with_only_bench_history_requires_review_not_invented_32_minutes(self):
        row={'Starting lineup check':{'Starter':True},'Selection':'Under','Line':15.5}
        attach_role_usage(row,{'history':self.history(False,'20')},'2026-10-20T02:00:00Z','1','Target',20,10,'PTS')
        self.assertTrue(row['NBA role review required'])
        self.assertIsNone(row['NBA role usage']['Candidate minutes'])
    def test_unconfirmed_lineup_or_missing_target_row_does_not_infer_role(self):
        row={};attach_role_usage(row,{'history':self.history()},'2026-10-20T02:00:00Z','1','Target',20,10,'PTS')
        self.assertFalse(row['NBA role review required']);self.assertIsNone(row['NBA role usage']['Candidate minutes'])
        result=role_usage(self.history(),'2026-10-20T02:00:00Z','1','Unknown',True,20,10,'PTS')
        self.assertEqual(result['Role sample games'],0)
    def test_future_wrong_team_duplicate_and_dnp_do_not_enter_role_sample(self):
        rows=self.history();future=copy.deepcopy(rows[0]);future['header']['id']='future';future['header']['competitions'][0]['date']='2026-10-21T02:00:00Z'
        r=role_usage(rows+[rows[0],future],'2026-10-20T02:00:00Z','1','Target',True,20,10,'PTS')
        self.assertEqual(r['Role sample games'],4)
        self.assertEqual(role_usage(rows,'2026-10-20T02:00:00Z','new-team','Target',True,20,10,'PTS')['Role sample games'],0)
        for data in rows:data['boxscore']['players'][0]['statistics'][0]['athletes'][0]['didNotPlay']=True
        self.assertEqual(role_usage(rows,'2026-10-20T02:00:00Z','1','Target',True,20,10,'PTS')['Role sample games'],0)
    def test_nba_decomposition_separates_minutes_and_production_per_minute(self):
        row={'player':'Harper','category':'Points','result':'Loss','projected_count':12,'expected_opportunities':24,'actual':18,'actual_opportunities':32}
        result=diagnostics([row])[0]
        self.assertEqual(result['Workload contribution'],4)
        self.assertEqual(result['Efficiency contribution'],2)
        self.assertEqual(result['Forecast miss'],6)
    def test_frozen_role_comparisons_exclude_missing_manual_and_duplicates(self):
        report=role_usage(self.history(),'2026-10-20T02:00:00Z','1','Target',True,24,12,'PTS')
        row={'sport':'NBA','event_id':'g','player':'Target','category':'Points','strategy':'Original','evidence':'Published before kickoff','season_type':'Regular season','published_utc':'2026-10-20T00:00:00Z','starts_utc':'2026-10-20T02:00:00Z','result':'Loss','actual':18,'actual_opportunities':32,'forecast_context':{'NBA role usage':report}}
        result=saved_role_reviews([row,dict(row,strategy='Analysis'),dict(row,event_id='missing',actual_opportunities=None),dict(row,event_id='manual',strategy='Manual')])
        self.assertEqual(len(result),1);self.assertEqual(result[0]['forecasts'],1)
        self.assertEqual(result[0]['role_minutes_mae'],0)
        self.assertEqual(result[0]['base_minutes_mae'],8)
        self.assertNotIn('Target',str(result))


if __name__=='__main__':unittest.main()
