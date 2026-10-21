import copy
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from datetime import date,timedelta
from extended_stats import current_value
from nfl_scoring_models import td_index,td_estimate,td_validate,total_estimate,total_validate,score_games
from nba_season_prior import season_projection
from scoring_quote_merge import with_game_totals

def player(season=2024,week=1,**kw):
    r=dict(season=season,week=week,game_id=str(season)+'-'+str(week),player_id='p',player_display_name='Receiver',team='A',position='WR',carries=0,targets=8,rushing_tds=0,receiving_tds=1,passing_tds=0)
    r.update(kw);return r
def summary():
    return {'header':{'id':'g','competitions':[{'status':{'type':{'completed':True}},'competitors':[{'homeAway':'home','score':'7'},{'homeAway':'away','score':'0'}]}]},'boxscore':{'players':[{'statistics':[{'name':'receiving','labels':['REC','YDS','TD'],'athletes':[{'athlete':{'id':'p','displayName':'Receiver'},'stats':['2','20','0']}]},{'name':'passing','labels':['C/ATT','YDS','TD'],'athletes':[{'athlete':{'id':'q','displayName':'Quarterback'},'stats':['10/20','100','1']}]}]}]},'scoringPlays':[{'scoringType':{'name':'touchdown'},'text':'Receiver 9 Yd pass from Quarterback (Kick)','homeScore':7,'awayScore':0}]}
class ScoringTests(unittest.TestCase):
    @patch.dict(sys.modules,{'requests':SimpleNamespace(),'streamlit':SimpleNamespace(cache_data=lambda **kwargs:lambda fn:fn)})
    def test_touchdown_quote_gate_and_frozen_final_grade(self):
        from datetime import datetime,timezone
        from nfl_scoring_models import reviews
        from pick_history import make_record,grade_record
        now=datetime(2026,10,25,16,55,tzinfo=timezone.utc)
        source={'id':'g','date':'2026-10-25T17:00:00Z','season':{'year':2026,'type':2},'status':{'type':{'state':'pre'}},'competitions':[{'competitors':[{'homeAway':'home','team':{'displayName':'Home','abbreviation':'A','id':'1'}},{'homeAway':'away','team':{'displayName':'Away','abbreviation':'B','id':'2'}}]}]}
        event={'home_team':'Home','away_team':'Away','commence_time':source['date'],'bookmakers':[{'title':'Book','markets':[{'key':'player_anytime_td','last_update':now.isoformat(),'outcomes':[{'name':'Receiver','price':200}]}]}]}
        data={'players':[player(2025,w)for w in range(1,10)],'teams':[],'schedule':[dict(game_id='g',game_type='REG',season='2026',week='8',gameday='2026-10-25',home_team='A',away_team='B')],'td_report':{'temperature':1,'passed':False},'total_report':{'residuals':[0]*100,'passed':False}}
        injuries={'season':2026,'source_updated':now.isoformat(),'retrieved':now.isoformat(),'teams':{'Home','Away'},'statuses':{},'rows':[]}
        roster={'Home':[{'name':'Receiver','status':'Active'}]}
        rows=reviews(event,{'events':[source]},data,injuries,roster,now)
        self.assertEqual(rows[0]['Decision'],'Pass')
        self.assertIsNotNone(rows[0]['Estimated win %'])
        data['td_report']['passed']=True
        row=reviews(event,{'events':[source]},data,injuries,roster,now)[0]
        self.assertNotEqual(row['Decision'],'Pass')
        record=make_record(row,'g',source['date'],now)
        graded=grade_record(record,summary())
        self.assertEqual(graded['result'],'Win')
        self.assertEqual(graded['actual'],1)
    def test_anytime_scorer_is_receiver_not_passer_and_unknown_not_loss(self):
        d=summary()
        self.assertEqual(current_value('Anytime touchdown','Receiver',d),1)
        self.assertEqual(current_value('Anytime touchdown','Quarterback',d),0)
        self.assertIsNone(current_value('Anytime touchdown','Not Reported',d))
        d['scoringPlays'][0]['text']='Unrecognized scoring description'
        self.assertIsNone(current_value('Anytime touchdown','Quarterback',d))
    def test_incomplete_scoring_ledger_never_creates_zero(self):
        d=summary();d['scoringPlays'][0]['homeScore']=0
        self.assertIsNone(current_value('Anytime touchdown','Quarterback',d))
        self.assertEqual(current_value('Game total points','Teams',d),7)
        d['header']['competitions'][0]['competitors'][1]['score']='--'
        self.assertIsNone(current_value('Game total points','Teams',d))
    def test_pra_requires_all_three_reported_components(self):
        d={'boxscore':{'players':[{'statistics':[{'labels':['PTS','REB','AST'],'athletes':[{'athlete':{'displayName':'P'},'stats':['20','7','5']}]}]}]}}
        self.assertEqual(current_value('PRA','P',d),32)
        d['boxscore']['players'][0]['statistics'][0]['athletes'][0]['stats'][1]='--'
        self.assertIsNone(current_value('PRA','P',d))
    def test_td_forecast_ignores_passing_scores_and_future_games(self):
        history=[player(week=w)for w in range(1,10)]
        f=td_estimate('p',2025,1,'A',td_index(history))
        changed=[dict(r,passing_tds=100)for r in history]+[player(2025,2,receiving_tds=99)]
        self.assertEqual(f,td_estimate('p',2025,1,'A',td_index(changed)))
        self.assertGreater(f['probability'],0)
        history[0]['receiving_tds']=None
        self.assertIsNone(td_estimate('p',2025,1,'A',td_index(history)))
    def test_new_team_not_reported_as_established(self):
        history=[player(week=w)for w in range(1,10)]
        self.assertTrue(td_estimate('p',2025,1,'B',td_index(history))['role_uncertain'])
    def games(self):
        return [dict(game_id=str(year)+'-'+str(i),season=year,week=i//7+1,game_type='REG',gameday=(date(year,1,1)+timedelta(days=i)).isoformat(),home_team='A',away_team='B',home_score=24,away_score=20)for year in (2023,2024,2025)for i in range(110)]
    def test_totals_excludes_same_day_and_future_and_ties_fail_gate(self):
        games=score_games(self.games());target=dict(season=2025,gameday='2025-01-01',home_team='A',away_team='B')
        f=total_estimate(target,games)
        changed=[dict(r,home_score=999)if r['gameday']>=target['gameday']else r for r in games]
        self.assertEqual(f,total_estimate(target,changed))
        report=total_validate(self.games())
        self.assertEqual(report['forecast_mae'],0)
        self.assertFalse(report['passed'])
    def test_pra_forecast_uses_observed_joint_sum(self):
        rows=[dict(date='2026-01-'+str(i).zfill(2),season=2026,game=str(i),team='A',minutes=30,PTS=20,REB=6,AST=4)for i in range(1,20)]
        f=season_projection(rows,'PRA',2027,'A','2026-10-21')
        self.assertEqual(f['projected'],30)
        self.assertNotIn('PRA',rows[0])
    def test_merging_loaded_totals_keeps_quote_timestamp_and_input_unchanged(self):
        prop={'id':'g','bookmakers':[{'title':'Book','markets':[{'key':'player_pass_yds'}]}]}
        totals={'id':'g','bookmakers':[{'title':'Book','markets':[{'key':'totals','last_update':'original-time'}]}]}
        before=copy.deepcopy(prop);merged=with_game_totals([prop],[totals])
        self.assertEqual(prop,before)
        self.assertEqual(merged[0]['bookmakers'][0]['markets'][-1]['last_update'],'original-time')
        self.assertEqual(len(with_game_totals(merged,[totals])[0]['bookmakers'][0]['markets']),2)

if __name__=='__main__':unittest.main()
