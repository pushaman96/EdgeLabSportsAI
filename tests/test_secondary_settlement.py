import unittest
from secondary_settlement import nfl_summary,nba_summary,resolve
from pick_history import grade_record,grade_all

def record(**kw):
    return dict(dict(id='p',event_id='123',sport='NFL',game='New England Patriots at Chicago Bears',starts_utc='2026-10-23T00:15:00Z',player='Runner',category='Rushing yards',line=20.5,direction='Over',odds=-110,result='Pending'),**kw)
def schedule():
    return [dict(espn='123',game_id='2026_07_NE_CHI',game_type='REG',gameday='2026-10-22',season='2026',home_team='CHI',away_team='NE',home_score='30',away_score='20')]
def player(**kw):
    return dict(dict(game_id='2026_07_NE_CHI',season_type='REG',player_display_name='Runner',team='NE',rushing_yards='25',carries='8'),**kw)

class SecondaryTests(unittest.TestCase):
    def test_nfl_exact_final(self):
        r=record();data=nfl_summary(r,schedule(),[player()])
        final=resolve(r,fetch=lambda *a:(data,'fixture final'))
        self.assertEqual(final['result'],'Win')
        self.assertEqual(final['actual'],25)
        self.assertEqual(final['actual_opportunities'],8)
        self.assertEqual(final['settlement_source'],'fixture final')
        self.assertEqual(r['result'],'Pending')
    def test_missing_not_zero_and_duplicate_not_accepted(self):
        for rows in ([player(rushing_yards='')],[player(),player()]):
            with self.assertRaises(ValueError):nfl_summary(record(),schedule(),rows)
    def test_wrong_game_and_player_rejected(self):
        with self.assertRaises(ValueError):nfl_summary(record(event_id='wrong'),schedule(),[player()])
        with self.assertRaises(ValueError):nfl_summary(record(player='Other'),schedule(),[player()])
    def test_conflicting_final_scores_not_graded(self):
        r=record();data=nfl_summary(r,schedule(),[player()])
        primary=nfl_summary(r,schedule(),[player()])
        primary['header']['competitions'][0]['competitors'][0]['score']='31'
        final=resolve(r,primary,fetch=lambda *a:(data,'fixture'))
        self.assertEqual(final['result'],'Pending')
        self.assertEqual(final['settlement_source_status'],'Conflict')
    def test_completed_record_never_overwritten(self):
        r=record(result='Win')
        result=grade_all([r],fetch=lambda *a:self.fail('unnecessary fetch'),fallback=lambda *a:self.fail('unnecessary fallback'))
        self.assertEqual(result,[r])
    def test_nba_explicit_participation_and_pra(self):
        r=record(sport='NBA',game='Cleveland Cavaliers at Philadelphia 76ers',player='Player',category='PRA',line=20.5)
        g={'gameId':'002','gameStatus':3,'homeTeam':{'teamCity':'Philadelphia','teamName':'76ers','score':100,'players':[{'name':'Player','played':'1','statistics':{'points':15,'reboundsTotal':5,'assists':3,'minutes':'PT30M00.00S'}}]},'awayTeam':{'teamCity':'Cleveland','teamName':'Cavaliers','score':90,'players':[]}}
        data=nba_summary(r,g,'002')
        self.assertEqual(grade_record(r,data)['actual'],23)
        g['homeTeam']['players'][0]['played']='0'
        with self.assertRaises(ValueError):nba_summary(r,g,'002')
    def test_primary_missing_uses_fallback(self):
        r=record();data=nfl_summary(r,schedule(),[player()])
        final=grade_all([r],fetch=lambda *a:{},fallback=lambda r,p:resolve(r,p,fetch=lambda *a:(data,'fixture')))
        self.assertEqual(final[0]['result'],'Win')
