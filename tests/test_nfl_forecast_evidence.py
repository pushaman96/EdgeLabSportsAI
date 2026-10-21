import copy
import unittest
from datetime import datetime,timezone
from nfl_forecast_evidence import average_profile,schedule_context,depth_listing,restriction,attach,teammate_involvement,saved_role_reviews
from nba_calibration import reliability
from contextual_forecasts import nfl_availability
from pick_history import make_record


NOW=datetime(2026,10,20,12,tzinfo=timezone.utc)


def row(week=1,season=2026,team='A',pid='p',name='Player',**changes):
    result={'season':season,'week':week,'team':team,'opponent_team':'B','game_id':f'{season}-{week}','player_id':pid,'player_display_name':name,'position':'QB','passing_yards':240,'attempts':30,'completions':20,'passing_tds':2,'passing_interceptions':1,'rushing_yards':40,'carries':10,'targets':6,'receptions':4,'receiving_yards':50}
    result.update(changes);return result


class EvidenceTests(unittest.TestCase):
    def test_conversion_rates_use_totals_and_preserve_negative_yardage(self):
        history=[row(attempts=2,completions=2,targets=2,receptions=1,rushing_yards=-2),row(2,attempts=8,completions=1,targets=8,receptions=3,rushing_yards=4)]
        result=average_profile(history,[],{},2026,3,'A','Rushing yards')[1]
        self.assertEqual(result['Completion %'],30);self.assertEqual(result['Catch %'],40)
        self.assertEqual(result['Average'],1);self.assertEqual(result['Yards/carry'],.1)
    def test_missing_data_no_zero_and_share_denominators_join_actual_games(self):
        history=[row(targets=4),row(2,targets=6)]
        teams=[row(pid=None,targets=10),row(2,pid=None,targets=10)]
        result=average_profile(history,teams,{},2026,3,'A','Receiving yards')[1]
        self.assertEqual(result['Target share %'],50)
        self.assertIsNone(result['Mean game offensive snap %'])
        result=average_profile([row(passing_yards=None,attempts=None,completions=None)],[],{},2026,3,'A','Passing yards')[1]
        self.assertIsNone(result['Average']);self.assertIsNone(result['Completion %']);self.assertIsNone(result['Pass-attempt share %'])
    def test_future_season_week_and_trade_stint_do_not_contaminate_role(self):
        history=[row(17,2025),row(1),row(2,team='B'),row(3,attempts=10),row(4,passing_yards=99999)]
        before=copy.deepcopy(history)
        result={r['Sample']:r for r in average_profile(history,[],{},2026,4,'A','Passing yards')}
        self.assertEqual(result['Current-team current stint']['Observed games'],1)
        self.assertEqual(result['This season — all teams']['Observed games'],3)
        self.assertEqual(result['Last season — all teams']['Observed games'],1)
        self.assertEqual(history,before)
    def test_rest_short_week_uses_completed_schedule_and_ignores_future_or_missing_scores(self):
        schedule=[{'game_id':'old','home_team':'A','away_team':'B','gameday':'2026-10-18','home_score':'20','away_score':'10'},{'game_id':'future','home_team':'A','away_team':'B','gameday':'2026-10-25','home_score':'','away_score':''}]
        result=schedule_context(schedule,'A','B','2026-10-22')
        self.assertTrue(result['Team']['Short week']);self.assertEqual(result['Team']['Scheduled off days'],3)
        self.assertIsNone(schedule_context([],'A','B','2026-10-22')['Team']['Short week'])
    def test_depth_listing_is_not_confirmed_starter(self):
        data={'depthchart':[{'positions':{'qb':{'position':{'abbreviation':'QB'},'athletes':[{'id':'a','displayName':'First'},{'id':'b','displayName':'Backup'}]}}}]}
        result=depth_listing(data,'b','Backup')
        self.assertEqual(result['Listings'][0]['Listed rank'],2)
        self.assertIsNone(result['Confirmed game-day starter'])
        self.assertEqual(depth_listing(data,'unknown','Backup')['Listings'],[])
    def test_workload_limit_is_fresh_game_specific_not_practice_or_negation(self):
        r={'Team':'Home','Player':'Player','Report updated UTC':NOW.isoformat(),'Short comment':'Player will be on a snap count Sunday.'}
        self.assertTrue(restriction({'rows':[r]},'Home','Player',NOW)['Review required'])
        r['Short comment']='Player will not be on a snap count Sunday.'
        self.assertFalse(restriction({'rows':[r]},'Home','Player',NOW)['Review required'])
        r['Short comment']='Player had a limited workload in practice.'
        self.assertFalse(restriction({'rows':[r]},'Home','Player',NOW)['Review required'])
    def test_teammate_missing_snap_rows_not_converted_to_absences(self):
        history=[row(i)for i in range(1,7)];research={'players':history+[row(1,pid='mate',name='Mate',position='RB')]}
        injuries={'statuses':{('Home','mate'):'Out'}}
        result=teammate_involvement(history,research,{},2026,7,'A','Home',injuries,'passing_yards','attempts')[0]
        self.assertEqual(result['Recorded zero offensive snaps']['Games'],0)
        self.assertIsNone(result['Observed stat difference'])
        snaps={(2026,'A',r['game_id'],'mate'):[{'offense_snaps':0 if r['week']<=3 else 20}]for r in history}
        result=teammate_involvement(history,research,snaps,2026,7,'A','Home',injuries,'passing_yards','attempts')[0]
        self.assertEqual(result['Recorded zero offensive snaps']['Games'],3)
        self.assertEqual(result['Recorded positive offensive snaps']['Games'],3)
        self.assertEqual(result['Observed stat difference'],0)
    def test_evidence_saves_with_pick_and_role_candidate_does_not_change_probability(self):
        history=[row(i)for i in range(1,5)];research={'players':history,'teams':[dict(r)for r in history],'schedule':[]}
        quote={'Game':'Home at Away','Player':'Player','Category':'Passing yards','Selection':'Over','Line':200.5,'Odds':-110,'Sportsbook':'Book','Decision':'Watch — experimental','Model':'fixture','Estimated win %':60,'Quote updated UTC':NOW.isoformat(),'Expected opportunities':30,'Projection (yards)':240}
        attach(quote,history,research,2026,5,'A','B','Home','1','a',{'rows':[],'statuses':{}},NOW,'2026-10-25')
        self.assertEqual(quote['Estimated win %'],60);self.assertEqual(quote['Projection (yards)'],240)
        self.assertEqual(quote['NFL recent-role candidate']['Opportunities'],30)
        record=make_record(quote,'g','2026-10-25T17:00:00Z',NOW)
        self.assertIn('NFL player averages',record['forecast_context'])
        self.assertIn('NFL snap trend',record['forecast_context'])
        self.assertIsNone(record['forecast_context']['NFL depth check']['Confirmed game-day starter'])
        graded=dict(record,result='Win',actual=250,actual_opportunities=32,season_type='Regular season')
        results=saved_role_reviews([graded,dict(graded,strategy='Analysis'),dict(graded,event_id='missing',actual_opportunities=None)])
        self.assertEqual(results[0]['role_workload_mae'],2)
    def test_missing_teammate_workload_does_not_receive_zero_redistribution(self):
        roster=[{'name':'Player','status':'Active'},{'name':'Mate','status':'Active'}]
        history=[]
        for week in range(1,5):history.extend([row(week,position='RB',carries=10),row(week,pid='mate',name='Mate',position='RB',carries=None)])
        result=nfl_availability('Player','Rushing yards','A','Home',2026,5,history,roster,{'statuses':{('Home','mate'):'Out'}})
        self.assertEqual(result['workload_factor'],1)
        self.assertIn('Incomplete',result['reason'])
    def test_reliability_keeps_nfl_and_nba_separate(self):
        r={'event_id':'a','player':'Player','category':'Passing yards','sport':'NFL','model':'NFL fixture','strategy':'Original','evidence':'Published before kickoff','season_type':'Regular season','published_utc':'2026-10-18T16:00:00Z','starts_utc':'2026-10-18T17:00:00Z','graded_utc':'2026-10-19T01:00:00Z','result':'Win','probability':.65}
        self.assertEqual(len(reliability([r],NOW,sport='NFL')),1)
        self.assertEqual(reliability([r],NOW,sport='NBA'),[])

    def test_nfl_review_rejects_earlier_espn_start_before_loading_player_model(self):
        import sys
        from types import SimpleNamespace
        from unittest.mock import patch
        with patch.dict(sys.modules,{'streamlit':SimpleNamespace(cache_data=lambda **kwargs:lambda fn:fn),'requests':SimpleNamespace()}):
            from nfl_prop_model import prop_reviews
            event={'home_team':'Home','away_team':'Away','commence_time':'2026-10-20T12:05:00Z','bookmakers':[{'title':'Book','markets':[{'key':'player_pass_yds','last_update':NOW.isoformat(),'outcomes':[{'description':'Player','name':'Under','point':200.5,'price':-110}]}]}]}
            source={'date':'2026-10-20T11:55:00Z','season':{'year':2026,'type':2},'status':{'type':{'state':'in','completed':False}},'competitions':[{'competitors':[{'homeAway':'home','team':{'displayName':'Home','abbreviation':'A','id':'1'}},{'homeAway':'away','team':{'displayName':'Away','abbreviation':'B','id':'2'}}]}]}
            research={'players':[],'teams':[],'schedule':[]}
            with patch('interception_model.validation',return_value={}):
                result=prop_reviews(event,{'events':[source]},research,{}, {},NOW)
            self.assertEqual(result[0]['Decision'],'Pass')
            self.assertIn('pregame window is closed',result[0]['Reason'])
            self.assertIsNone(result[0]['Estimated win %'])


if __name__=='__main__':unittest.main()
