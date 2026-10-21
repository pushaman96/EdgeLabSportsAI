import copy
import math
import unittest
from datetime import date,timedelta,datetime,timezone
from unittest.mock import patch
from nba_forecast_quality import stat_band,attach_quality,quantile,settled_quality
from nba_season_prior import season_projection
from nba_prop_model import research,reviews
from pick_history import make_record
from saved_pick_explanation import explanation


class QualityTests(unittest.TestCase):
    def rows(self,minutes=None,season=2026,team='A',start='2026-01-01'):
        return [dict(player='p',name='Player',season=season,team=team,date=(date.fromisoformat(start)+timedelta(days=i)).isoformat(),game=str(season)+str(i),minutes=m,PTS=m*.5,REB=6,AST=4,FG3M=2)for i,m in enumerate(minutes or [30]*12)]
    def test_band_uses_actual_residuals_without_claiming_fixed_coverage(self):
        self.assertEqual(stat_band(25,[-1.]*50),(20.,20.))
        self.assertIsNone(stat_band(25,[0.]*49))
        self.assertIsNone(stat_band(25,[float('nan')]*50))
        self.assertEqual(stat_band(1,[-100.]*50),(0.,0.))
        self.assertAlmostEqual(quantile([10,20],.1),11)
    def test_minutes_sensitivity_is_context_not_direction_or_probability_change(self):
        rows=self.rows([10,12,14,16,20,22,24,28,32,34,36,38])
        before=copy.deepcopy(rows)
        row={'Line':15.5,'Selection':'Under','Estimated win %':60.,'Decision':'Watch — experimental'}
        attach_quality(row,rows,'2026-10-20','A',15,30,[0.]*50)
        self.assertEqual(row['Minutes risk'],'Variable observed minutes')
        self.assertEqual(row['Minutes sensitivity'],'Observed minutes scenarios cross the line')
        self.assertEqual(row['Selection'],'Under');self.assertEqual(row['Estimated win %'],60)
        self.assertEqual(rows,before)
        self.assertIn('not guaranteed',row['Range method'])
    def test_future_minutes_do_not_change_context_and_missing_not_zero(self):
        rows=self.rows();a={};b={}
        attach_quality(a,rows,'2026-10-20','A',15,30,[0.]*50)
        attach_quality(b,rows+self.rows([99]*12,2027,start='2026-10-20'),'2026-10-20','A',15,30,[0.]*50)
        self.assertEqual(a,b)
        r={};attach_quality(r,[],'2026-10-20','A',15,30,[])
        self.assertEqual(r['Minutes sample games'],0)
        self.assertNotIn('Observed minutes low',r)
    def test_return_to_old_team_uses_only_new_stint_and_marks_role_uncertain(self):
        rows=self.rows()+self.rows([30]*6,2027,start='2026-10-01')+self.rows([20]*2,2027,'B','2026-10-07')+self.rows([10],2027,'A','2026-10-09')
        f=season_projection(rows,'PTS',2027,'A','2026-10-10')
        self.assertEqual(f['current_games'],1);self.assertTrue(f['role_uncertain'])
        r={};attach_quality(r,rows,'2026-10-10','A',15,30,[])
        self.assertEqual(r['Minutes sample games'],1)
        self.assertEqual(r['Minutes risk'],'Insufficient current-role minutes evidence')
    def test_range_coverage_is_measured_on_later_games_and_not_assumed_80_percent(self):
        rows=[]
        for year in (2024,2025,2026):
            for player in range(8):
                rows.extend(dict(r,player=str(player),game=r['game']+'-'+str(player))for r in self.rows([30]*60,year,start=str(year-1)+'-10-20'))
        report=research(rows,'2026-10-20')['cohort_reports']['PTS','Early season (0–7 appearances)']
        self.assertEqual(report['empirical_band_validation_coverage'],1.)
        self.assertEqual(report['mean_actual_minus_forecast'],0.)
        self.assertFalse(report['passed'])
    def test_frozen_quality_evidence_and_explanation(self):
        now=datetime(2026,10,20,tzinfo=timezone.utc)
        row={'Game':'A at B','Player':'Player','Category':'Points','Selection':'Under','Line':15.5,'Odds':-110,'Sportsbook':'Book','Decision':'Watch — experimental','Estimated win %':60,'Quote updated UTC':now.isoformat(),'Model':'quality fixture','Projection (count)':15,'Expected opportunities':30,'Opportunity type':'Minutes'}
        attach_quality(row,self.rows(),'2026-10-20','A',15,30,[-1.,1.]*25)
        record=make_record(row,'g','2026-10-21T02:00:00Z',now)
        self.assertEqual(record['forecast_context']['Minutes sample games'],12)
        self.assertIn('Historical error range low',record['forecast_context'])
        self.assertIn('Minutes evidence',explanation(record)['uncertainty'])
    def test_unvalidated_absence_boost_does_not_change_live_base_forecast(self):
        now=datetime(2026,10,19,12,tzinfo=timezone.utc)
        start='2026-10-20T02:00:00+00:00'
        rows=self.rows([30]*60,start='2026-01-01',team='100')
        event={'away_team':'Away','home_team':'Home','commence_time':start,'bookmakers':[{'title':'Book','markets':[{'key':'player_points','last_update':now.isoformat(),'outcomes':[{'description':'Player','name':'Over','point':5.5,'price':-110}]}]}]}
        board={'events':[{'name':'Away at Home','date':start,'season':{'type':2,'year':2027},'competitions':[{'competitors':[{'team':{'displayName':'Home','id':'100','abbreviation':'GS'}},{'team':{'displayName':'Away','id':'2','abbreviation':'LAL'}}]}]}]}
        data={'logs':rows,'season':2027,'id_namespace':'ESPN','retrieved':now.isoformat()}
        injuries={'source_timestamp':now.isoformat(),'retrieved':now.strftime('%Y-%m-%d %H:%M UTC'),'teams':['Home','Away'],'rows':[]}
        roster={'Home':[{'name':'Player','status':'Active'}],'Away':[]}
        with patch('nba_prop_model.minutes_replacement',return_value=(39.,1.3)):
            row=reviews([event],board,data,injuries,roster,now)[0]
        self.assertEqual(row['Minutes forecast'],30.)
        self.assertEqual(row['Projection (count)'],15.)
        self.assertEqual(row['Absence scenario minutes'],39.)
        self.assertEqual(row['Injury adjustment %'],0.)
        self.assertEqual(row['Injury source updated UTC'],now.isoformat())

    def test_postgame_diagnostics_exclude_missing_stats_manual_picks_and_later_duplicates(self):
        r={'id':'a','event_id':'g','player':'Player','category':'Points','sport':'NBA','strategy':'Original','evidence':'Published before kickoff','season_type':'Regular season','published_utc':'2026-10-20T20:00:00Z','starts_utc':'2026-10-21T02:00:00Z','result':'Win','actual':0,'projected_count':10,'actual_opportunities':None,'expected_opportunities':30,'forecast_context':{'Minutes risk':'Variable observed minutes','Historical error range low':0,'Historical error range high':20}}
        duplicate=dict(r,id='b',published_utc='2026-10-20T21:00:00Z',projected_count=0)
        manual=dict(r,id='c',player='Other',strategy='Manual',actual=100)
        missing=dict(r,id='d',player='Missing',actual=None)
        result=settled_quality([r,duplicate,manual,missing])[0]
        self.assertEqual(result['Stat comparisons'],1)
        self.assertEqual(result['Stat average absolute error'],10)
        self.assertEqual(result['Minutes comparisons'],0)
        self.assertIsNone(result['Minutes average absolute error'])
        self.assertEqual(result['Measured range coverage %'],100)

    def test_postgame_comparisons_weight_games_equally(self):
        rows=[]
        for game,player,actual in [('a','One',0),('a','Two',0),('b','Three',30)]:
            rows.append({'event_id':game,'player':player,'category':'Points','sport':'NBA','strategy':'Original','evidence':'Published before kickoff','season_type':'Regular season','published_utc':'2026-10-20T20:00:00Z','starts_utc':'2026-10-21T02:00:00Z','result':'Win','actual':actual,'projected_count':10,'forecast_context':{'Minutes risk':'Steadier observed minutes'}})
        result=settled_quality(rows)[0]
        self.assertEqual(result['Stat average absolute error'],15)
        self.assertEqual(result['Average actual minus forecast'],5)


if __name__=='__main__':unittest.main()
