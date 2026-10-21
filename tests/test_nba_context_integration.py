"""Check context and calibration at the NBA recommendation/save boundary."""
import unittest
from datetime import datetime,timedelta,timezone
from unittest.mock import patch
from nba_prop_model import reviews
from pick_history import make_record
from pick_learning import adjust_row


class IntegrationTests(unittest.TestCase):
    def fixture(self):
        now=datetime(2026,10,19,12,tzinfo=timezone.utc);start=(now+timedelta(days=1)).isoformat()
        logs=[]
        for i in range(120):
            minutes=20+i*.1
            logs.append({'player':'nba-player','name':'Player One','team':'100','date':(now-timedelta(days=120-i)).date().isoformat(),'game':str(i),'minutes':minutes,'PTS':minutes,'REB':minutes*.3,'AST':minutes*.2,'FG3M':minutes*.05})
        event={'away_team':'Away','home_team':'Home','commence_time':start,'bookmakers':[{'title':'Book','markets':[{'key':'player_points','last_update':now.isoformat(),'outcomes':[{'description':'Player One','name':'Over','point':5.5,'price':-110}]}]}]}
        board={'events':[{'id':'espn','name':'Away at Home','date':start,'season':{'type':2,'year':2027},'competitions':[{'competitors':[{'team':{'displayName':'Home','id':'espn-team','abbreviation':'GS'}},{'team':{'displayName':'Away','id':'away-team','abbreviation':'LAL'}}]}]}]}
        data={'season':2027,'logs':logs,'team_ids':{'GSW':'100'},'retrieved':now.isoformat()}
        injuries={'source_timestamp':now.isoformat(),'retrieved':now.strftime('%Y-%m-%d %H:%M UTC'),'teams':['Home','Away'],'rows':[]}
        roster={'Home':[{'name':'Player One','status':'Active'}],'Away':[]}
        return now,event,board,data,injuries,roster

    def test_fresh_minutes_limit_requires_review_even_with_active_status(self):
        now,event,board,data,injuries,roster=self.fixture()
        injuries['rows']=[{'Team':'Home','Player':'Player One','Status':'Active','Report updated (UTC)':now.isoformat(),'Short comment':'Player One will play with a minutes restriction.'}]
        row=reviews([event],board,data,injuries,roster,now,context={})[0]
        self.assertEqual(row['Decision'],'Pass')
        self.assertIn('minutes limit',row['Reason'])
        self.assertTrue(row['Minutes restriction check']['Review required'])
        self.assertIsNotNone(row['Projection (count)'])

    def test_calibration_output_reaches_edge_gate_and_context_freezes(self):
        now,event,board,data,injuries,roster=self.fixture()
        calls=[]
        def calibrated(row,p,now=None,sport=None):
            calls.append(sport)
            row['Raw estimated win %']=100*p
            row['Feedback status']='Validated fixture correction'
            return .4
        with patch('pick_learning.adjust_row',side_effect=calibrated):
            row=reviews([event],board,data,injuries,roster,now,context={})[0]
        self.assertEqual(calls,['NBA'])
        self.assertEqual(row['Estimated win %'],40)
        self.assertLess(row['Model edge (pp)'],0)
        self.assertEqual(row['Decision'],'Pass')
        record=make_record(dict(row,Sport='NBA'),'espn',event['commence_time'],now,strategy='Analysis')
        self.assertIn('Verified schedule context',record['forecast_context'])
        self.assertEqual(record['forecast_context']['Probability calibration status'],'Validated fixture correction')
        self.assertIsNone(record['forecast_context']['Starting lineup check']['Starter'])
        self.assertEqual(record['probability'],.4)

    def test_no_validated_nba_parameters_means_no_correction(self):
        now,*_=self.fixture()
        row={'Model':'NBA fixture','Category':'Points','Selection':'Over'}
        state={'schema':1,'method':'probability-feedback-v1','generated_utc':now.isoformat(),'groups':{}}
        self.assertEqual(adjust_row(row,.65,now,state,sport='NBA'),.65)
        self.assertEqual(row['Raw estimated win %'],65)


if __name__=='__main__':unittest.main()
