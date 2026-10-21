import copy
import unittest
from datetime import datetime,timezone,timedelta
from unittest.mock import patch
from types import SimpleNamespace
import sys
import nba_game_context as context
from nba_calibration import reliability


NOW=datetime(2026,10,21,tzinfo=timezone.utc)


def player(name='Target',minutes='48',points='20',starter=True,dnp=False):
    return {'athlete':{'displayName':name},'starter':starter,'didNotPlay':dnp,'stats':[]if dnp else [minutes,points,'5','4','2-5','8-16']}


def game(eid='g',day='2026-10-01T02:00:00Z',absent=False,points='20',period=4,completed=True):
    def team(tid):
        return {'team':{'id':tid},'statistics':[{'name':k,'displayValue':v}for k,v in [('fieldGoalsMade-fieldGoalsAttempted','40-90'),('freeThrowsMade-freeThrowsAttempted','15-20'),('offensiveRebounds','10'),('totalTurnovers','12')]]}
    def athletes(tid):
        rows=[player('Target',points=points),player('Mate',dnp=absent),player('Third'),player('Fourth'),player('Fifth')]
        # All played rows have 48 minutes; explicit DNP means one replacement.
        if absent:rows.append(player('Replacement'))
        return {'team':{'id':tid},'statistics':[{'labels':['MIN','PTS','REB','AST','3PT','FG'],'athletes':rows}]}
    return {'header':{'id':eid,'season':{'type':2},'competitions':[{'date':day,'status':{'period':period,'type':{'completed':completed,'state':'post'if completed else'pre'}}}]},'boxscore':{'teams':[team('1'),team('2')],'players':[athletes('1'),athletes('2')]}}


class ContextTests(unittest.TestCase):
    def test_team_schedule_season_identity_and_no_preseason_or_canceled_games(self):
        event={'id':'g','date':'2026-10-21T23:00:00Z','timeValid':True,'season':{'year':2027},'seasonType':{'type':2},'competitions':[{'competitors':[{'team':{'id':'1'},'homeAway':'home'},{'team':{'id':'2'},'homeAway':'away'}],'status':{'type':{'completed':False}}}]}
        payload={'team':{'id':'1'},'season':{'year':2027,'type':2},'events':[event]}
        self.assertEqual(len(context.schedule_rows(payload,'1',2027)),1)
        payload['season']['year']=2028 # ESPN current-season header; event remains authoritative.
        self.assertEqual(len(context.schedule_rows(payload,'1',2027)),1)
        with self.assertRaises(ValueError):context.schedule_rows(payload,'2',2027)
        bad=copy.deepcopy(payload);bad['events'][0]['seasonType']['type']=1
        self.assertEqual(context.schedule_rows(bad,'1',2027),[])
        bad=copy.deepcopy(payload);bad['events'][0]['competitions'][0]['status']['type']['name']='STATUS_POSTPONED'
        self.assertEqual(context.schedule_rows(bad,'1',2027),[])
    def test_verified_back_to_back_uses_pacific_team_schedule_not_player_appearances(self):
        rows=[{'id':'old','team':'1','date':'2026-10-21T02:00:00Z','venue':'A'},{'id':'new','team':'1','date':'2026-10-22T02:00:00Z','venue':'B'},{'id':'future','team':'1','date':'2026-10-23T02:00:00Z'}]
        result=context.rest_context(rows,'new','2026-10-22T02:00:00Z','1')
        self.assertTrue(result['Back-to-back']);self.assertEqual(result['Scheduled off days'],0)
        self.assertTrue(result['Venue change'])
        self.assertIsNone(context.rest_context([],'new','2026-10-22T02:00:00Z','1')['Back-to-back'])
    def test_starting_lineup_requires_five_explicit_starters_and_matching_future_game(self):
        data=game('g','2026-10-22T02:00:00Z',completed=False)
        result=context.lineup_context(data,'g','2026-10-22T02:00:00Z','1','Target',NOW)
        self.assertTrue(result['Starter'])
        data['boxscore']['players'][0]['statistics'][0]['athletes'][0].pop('starter')
        self.assertIsNone(context.lineup_context(data,'g','2026-10-22T02:00:00Z','1','Target',NOW)['Starter'])
        self.assertIsNone(context.lineup_context(game(),'wrong','2026-10-22T02:00:00Z','1','Target',NOW)['Starter'])
    def test_restriction_flags_fresh_short_report_but_not_negation_or_old_long_comment(self):
        row={'Team':'Home','Player':'Target','Report updated (UTC)':NOW.isoformat(),'Short comment':'Target will play with a minutes restriction.','Long comment':''}
        report={'rows':[row]}
        self.assertTrue(context.restriction_context(report,'Home','Target',NOW)['Review required'])
        row['Short comment']='Target will have no minutes restriction.'
        self.assertFalse(context.restriction_context(report,'Home','Target',NOW)['Review required'])
        row['Short comment']="Target's minutes restriction will not be lifted."
        self.assertTrue(context.restriction_context(report,'Home','Target',NOW)['Review required'])
        row['Short comment']='Active tonight.';row['Long comment']='Minutes restriction in an old season.'
        self.assertFalse(context.restriction_context(report,'Home','Target',NOW)['Review required'])
        row['Short comment']='Minutes restriction tonight.';row['Report updated (UTC)']=(NOW-timedelta(days=3)).isoformat()
        self.assertFalse(context.restriction_context(report,'Home','Target',NOW)['Review required'])
    def test_teammate_usage_requires_explicit_dnp_and_both_sample_groups(self):
        games=[game(str(i),absent=i<3,points='30'if i<3 else'20')for i in range(6)]
        before=copy.deepcopy(games)
        result=context.teammate_context(games+[games[0]],'2026-10-22T02:00:00Z','1','Target',['Mate'],'PTS')[0]
        self.assertEqual(result['With teammate']['Games'],3);self.assertEqual(result['Without teammate']['Games'],3)
        self.assertEqual(result['Observed stat difference'],10)
        self.assertEqual(games,before)
        games[0]['boxscore']['players'][0]['statistics'][0]['athletes']=[player('Target')]
        result=context.teammate_context(games,'2026-10-22T02:00:00Z','1','Target',['Mate'],'PTS')[0]
        self.assertEqual(result['Without teammate']['Games'],2);self.assertIsNone(result['Observed stat difference'])
    def test_future_unfinished_and_preseason_do_not_enter_context(self):
        games=[game('future','2026-10-23T02:00:00Z'),game('live',completed=False),game('pre')]
        games[-1]['header']['season']['type']=1
        result=context.teammate_context(games,'2026-10-22T02:00:00Z','1','Target',['Mate'],'PTS')[0]
        self.assertEqual(result['With teammate']['Games'],0)
    def test_pace_formula_overtime_normalization_and_missing_totals(self):
        games=[game(str(i))for i in range(3)]
        result=context.opponent_context(games,'2026-10-22T02:00:00Z','1','2','PTS')
        self.assertAlmostEqual(result['Team estimated possessions per 48'],100.8)
        self.assertEqual(result['Opponent allowed stat per 48'],100)
        for data in games:
            c=data['header']['competitions'][0];c['status'].pop('period')
            c['competitors']=[{'linescores':[{}]*4},{'linescores':[{}]*4}]
        self.assertAlmostEqual(context.opponent_context(games,'2026-10-22T02:00:00Z','1','2','PTS')['Team estimated possessions per 48'],100.8)
        games=[game(str(i),period=5)for i in range(3)]
        result=context.opponent_context(games,'2026-10-22T02:00:00Z','1','2','PTS')
        self.assertAlmostEqual(result['Team estimated possessions per 48'],100.8*48/53)
        self.assertIsNone(result['Opponent allowed stat per 48']) # 240 player minutes do not reconcile to OT.
        for data in games:data['boxscore']['teams'][0]['statistics']=[]
        self.assertIsNone(context.opponent_context(games,'2026-10-22T02:00:00Z','1','2','PTS')['Team estimated possessions per 48'])
    def test_context_attaches_without_changing_selection_or_probability(self):
        row={'Decision':'Watch — experimental','Selection':'Over','Estimated win %':60,'Projection (count)':20}
        result=context.attach_context(row,{},'g','Home','1','Target','2026-10-22T02:00:00Z','PTS',{'rows':[]},NOW)
        self.assertEqual(result['Estimated win %'],60);self.assertEqual(result['Projection (count)'],20)
        self.assertIsNone(result['Starting lineup check']['Starter'])
    def test_rest_can_include_preseason_but_preseason_never_enters_usage_or_pace(self):
        data=game();data['header']['season']['type']=1
        self.assertFalse(context.completed_game(data,'2026-10-22T02:00:00Z'))
        rows=[{'id':'pre','team':'1','date':'2026-10-21T02:00:00Z','season_type':1},{'id':'reg','team':'1','date':'2026-10-22T02:00:00Z','season_type':2}]
        self.assertTrue(context.rest_context(rows,'reg','2026-10-22T02:00:00Z','1')['Back-to-back'])
    def test_context_source_failure_is_partial_and_does_not_invent_data(self):
        st=SimpleNamespace(cache_data=lambda **kwargs:lambda fn:fn)
        event={'away_team':'Away','home_team':'Home','commence_time':'2026-10-22T02:00:00Z'}
        board={'events':[{'id':'g','name':'Away at Home','date':event['commence_time'],'season':{'year':2027,'type':2},'competitions':[{'competitors':[{'team':{'id':'1','displayName':'Home'}},{'team':{'id':'2','displayName':'Away'}}]}]}]}
        with patch.dict(sys.modules,{'streamlit':st}),patch.object(context,'request',side_effect=TimeoutError()):
            result=context.load_context([event],board,now=NOW,max_history=2)
        self.assertEqual(result['history_loaded'],0);self.assertEqual(result['schedules'],[])
        self.assertTrue(result['issues']);self.assertIn('g',result['games'])


class CalibrationTests(unittest.TestCase):
    def row(self,eid='g',player='Player',result='Win',p=.65):
        return {'id':eid+player,'event_id':eid,'player':player,'sport':'NBA','category':'Points','strategy':'Original','evidence':'Published before kickoff','season_type':'Regular season','model':'model','direction':'Over','line':10.5,'published_utc':'2026-10-19T18:00:00Z','starts_utc':'2026-10-19T20:00:00Z','graded_utc':'2026-10-20T02:00:00Z','result':result,'probability':p,'raw_probability':p}
    def test_reliability_separates_game_weight_and_excludes_manual_or_ungraded(self):
        rows=[self.row('a','One'),self.row('a','Two'),self.row('b','Three','Loss'),dict(self.row('c','Manual'),strategy='Manual'),self.row('d','Pending','Pending')]
        result=reliability(rows,NOW)[0]
        self.assertEqual(result['Original picks'],3);self.assertEqual(result['Distinct games'],2)
        self.assertEqual(result['Observed win %'],50)
        self.assertIn('Small sample',result['Evidence status'])
    def test_earliest_pending_cannot_be_replaced_by_later_winning_duplicate(self):
        original=self.row(result='Pending');later=dict(self.row(),id='later',published_utc='2026-10-19T19:00:00Z')
        self.assertEqual(reliability([original,later],NOW),[])
    def test_future_grade_and_historical_import_never_calibrate(self):
        future=dict(self.row(),graded_utc='2026-10-23T02:00:00Z')
        historical=dict(self.row(),evidence='Historical import')
        self.assertEqual(reliability([future,historical],NOW),[])


if __name__=='__main__':unittest.main()
