import json
import os
import tempfile
import unittest
from datetime import datetime,timezone,timedelta,date
from pathlib import Path
from unittest.mock import patch
import background_research as bg
from background_moneyline import build_elo_model

NOW=datetime(2026,10,21,23,tzinfo=timezone.utc)
def event(eid='espn',offset=60):
    return {'id':eid,'date':(NOW+timedelta(minutes=offset)).isoformat(),'name':'Away at Home','season':{'year':2027,'type':2},'status':{'type':{'state':'pre','completed':False}},'competitions':[{'competitors':[{'homeAway':'home','team':{'id':'1','displayName':'Home'}},{'homeAway':'away','team':{'id':'2','displayName':'Away'}}]}]}
class BackgroundTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.old=os.getcwd();os.chdir(self.temp.name)
    def tearDown(self):os.chdir(self.old);self.temp.cleanup()
    def report(self):
        bg.write(bg.REPORT,{'generated_utc':NOW.isoformat(),'sports':{'NBA':{'scoreboard':{'events':[event()]}}}})
    def test_source_status_not_only_schedule_controls_pregame(self):
        self.assertTrue(bg.upcoming(event(),NOW))
        e=event();e['status']['type']['state']='in'
        self.assertFalse(bg.upcoming(e,NOW))
        self.assertFalse(bg.upcoming(event(offset=-1),NOW))
    def test_missing_secret_never_calls_provider(self):
        with patch.dict(os.environ,{},clear=True),patch.object(bg,'get',side_effect=AssertionError('No request')):
            self.assertEqual(bg.reserve(NOW,'run',False),[])
        self.assertEqual(bg.read(bg.BUDGET,{})['days'][str(bg.day(NOW))]['reserved'],0)
    def test_daily_shared_budget_and_same_run_retry_are_durable(self):
        self.report()
        provider=[{'id':'odds','home_team':'Home','away_team':'Away','commence_time':event()['date']}]
        with patch.dict(os.environ,{'ODDS_API_KEY':'fixture'}),patch.object(bg,'get',return_value=provider):
            self.assertEqual(len(bg.reserve(NOW,'run',True)),1)
            account=bg.read(bg.BUDGET,{})['days'][str(bg.day(NOW))]
            self.assertEqual(account['reserved'],6)
            self.assertNotIn('fixture',json.dumps(account))
            self.assertEqual(bg.reserve(NOW,'run',True),[])
            self.assertEqual(bg.read('background_pending.json',None),[])
            self.assertEqual(bg.reserve(NOW,'another',True),[])
    def test_started_and_non_nfl_rotation_day_do_not_reserve(self):
        self.report()
        data=bg.read(bg.REPORT,{})
        data['sports']['NFL']=data['sports'].pop('NBA');bg.write(bg.REPORT,data)
        with patch.dict(os.environ,{'ODDS_API_KEY':'fixture'}),patch.object(bg,'get',side_effect=AssertionError('Wednesday NFL should skip')):
            self.assertEqual(bg.reserve(NOW,'run',True),[])
    def test_missing_boxscore_remains_pending(self):
        bg.write(bg.LEDGER,{'schema':1,'records':[{'id':'p','sport':'NBA','event_id':'e','player':'P','category':'Points','starts_utc':(NOW-timedelta(hours=1)).isoformat(),'published_utc':(NOW-timedelta(hours=2)).isoformat(),'result':'Pending','projection':20,'workload':30}]})
        source={'header':{'id':'e','competitions':[{'status':{'type':{'completed':True}}}]},'boxscore':{'players':[]}}
        with patch.object(bg,'get',return_value=source):bg.review_projections(NOW)
        self.assertEqual(bg.read(bg.LEDGER,{})['records'][0]['result'],'Pending')
    def test_model_same_date_no_result_leakage(self):
        games=[dict(date=date(2025,1,1),season=2024,home_team='A',away_team='B',home_score=20,away_score=0),dict(date=date(2025,1,1),season=2024,home_team='A',away_team='C',home_score=0,away_score=20)]
        ratings,pred=build_elo_model(games)
        self.assertEqual(pred[0]['Home Win Probability'],pred[1]['Home Win Probability'])
    def test_projection_baseline_compares_same_games_only(self):
        rows=[dict(sport='NFL',result='Measured',category='Passing yards',event_id='a',actual=100,projection=90,simple_baseline=80),dict(sport='NFL',result='Measured',category='Passing yards',event_id='b',actual=100,projection=90)]
        result=bg.projection_summary(rows,'NFL')[0]
        self.assertEqual(result['Matched forecasts'],1)
        self.assertEqual(result['Projection minus baseline MAE'],-10)
        self.assertEqual(bg.projection_summary(rows,'NBA'),[])
    def test_forecast_preserves_original_ledger(self):
        bg.write('history.json',{'records':[{'id':'old','projection':20}]})
        bg.append_records('history.json',[{'id':'old','projection':99},{'id':'new','projection':30}])
        self.assertEqual(bg.read('history.json',{})['records'][0]['projection'],20)
if __name__=='__main__':unittest.main()
