import copy
import unittest
from datetime import datetime,timezone
from nba_player_averages import summarize,player_averages,attach_averages
from nba_season_prior import normalize_espn_logs
from nba_prop_model import normalize_logs
from pick_history import make_record


class AverageTests(unittest.TestCase):
    def row(self,game='g',season=2026,day='2026-01-01',team='A',points=20,minutes=30):
        return {'player':'p','game':game,'season':season,'date':day,'team':team,'PTS':points,'minutes':minutes,'REB':5,'AST':4,'FG3M':2}
    def test_shooting_percentage_uses_total_attempts_not_average_game_percentages(self):
        rows=[dict(self.row('a'),FGM=1,FGA=1,FG3M=1,FG3A=1,FTM=1,FTA=2),dict(self.row('b'),FGM=0,FGA=9,FG3M=0,FG3A=9,FTM=3,FTA=4)]
        result=summarize(rows,'PTS')
        self.assertEqual(result['FG %'],10)
        self.assertEqual(result['3PT %'],10)
        self.assertAlmostEqual(result['FT %'],100*4/6)
        self.assertEqual(result['FG attempts/game'],5)
    def test_missing_shooting_is_unknown_but_observed_zero_makes_is_valid(self):
        result=summarize([self.row()],'PTS')
        self.assertIsNone(result['FG %']);self.assertEqual(result['FG shooting games'],0)
        result=summarize([dict(self.row(),FGM=0,FGA=4,FTM=0,FTA=0)],'PTS')
        self.assertEqual(result['FG %'],0);self.assertIsNone(result['FT %'])
        self.assertEqual(result['FT attempts/game'],0)
    def test_mean_median_rate_and_line_results_are_distinct_and_handle_pushes(self):
        rows=[self.row('a',points=10,minutes=10),self.row('b',points=20,minutes=30),self.row('c',points=60,minutes=20)]
        r=summarize(rows,'PTS',20)
        self.assertEqual(r['Average'],30);self.assertEqual(r['Median'],20)
        self.assertEqual(r['Stat per minute'],1.5)
        self.assertEqual(r['Historical overs'],1);self.assertEqual(r['Historical unders'],1);self.assertEqual(r['Historical pushes'],1)
        self.assertEqual(r['Historical over % (excluding pushes)'],50)
    def test_cutoff_preseason_duplicate_and_trade_stint_handling(self):
        rows=[self.row('prior'),self.row('old',2027,'2026-10-01','A'),self.row('away',2027,'2026-10-02','B'),self.row('return',2027,'2026-10-03','A',10),self.row('future',2027,'2026-10-20',points=999),dict(self.row('pre',2027,'2026-10-04',points=999),season_type=1)]
        rows.append(copy.deepcopy(rows[0]));before=copy.deepcopy(rows)
        profile=player_averages(rows,'PTS',2027,'A','2026-10-20',15.5)
        look={r['Sample']:r for r in profile}
        self.assertEqual(look['Last season — all teams']['Games'],1)
        self.assertEqual(look['This season — all teams']['Games'],3)
        self.assertEqual(look['Current-team current stint']['Games'],1)
        self.assertEqual(look['Current-team current stint']['Average'],10)
        self.assertTrue(look['Last 5 appearances']['Includes prior season'])
        self.assertTrue(look['Last 5 appearances']['Includes prior team'])
        self.assertEqual(rows,before)
    def test_unavailable_current_history_is_not_zero_games(self):
        row={'Line':20.5};attach_averages(row,[self.row()],'PTS',2027,'A','2026-10-20',False)
        current=next(r for r in row['Player averages']if r['Sample']=='This season — all teams')
        self.assertIsNone(current['Games']);self.assertIsNone(current['Average'])
        self.assertIn('could not be verified',row['Player averages method'])
    def test_averages_freeze_without_changing_probability_or_selection(self):
        now=datetime(2026,10,20,tzinfo=timezone.utc)
        row={'Game':'A at B','Player':'Player','Category':'Points','Selection':'Under','Line':20.5,'Odds':-110,'Sportsbook':'Book','Decision':'Watch — experimental','Estimated win %':60,'Quote updated UTC':now.isoformat(),'Model':'fixture'}
        attach_averages(row,[self.row()],'PTS',2027,'A','2026-10-20')
        record=make_record(row,'g','2026-10-21T02:00:00Z',now)
        self.assertEqual(record['probability'],.6);self.assertEqual(record['direction'],'Under')
        self.assertEqual(record['forecast_context']['Last-season average'],20)
        self.assertIn('Player averages',record['forecast_context'])


class ShootingParserTests(unittest.TestCase):
    def test_nba_optional_attempts_do_not_require_fabricated_values(self):
        row={'SEASON_ID':'22025','WL':'W','MIN':30,'PTS':20,'REB':5,'AST':4,'FG3M':2,'PLAYER_ID':1,'PLAYER_NAME':'Player','TEAM_ID':100,'GAME_ID':'g','GAME_DATE':'2026-01-01','FGM':7,'FGA':15,'FG3A':6,'FTM':4,'FTA':5}
        parsed=normalize_logs([row],2026)[0]
        self.assertEqual(parsed['FGA'],15);self.assertEqual(parsed['FG3A'],6)
        del row['FTA']
        parsed=normalize_logs([row],2026)[0]
        self.assertIsNone(parsed['FTA']);self.assertIsNone(parsed['FTM'])
        self.assertEqual(parsed['PTS'],20)
        row['FG3A']=1
        self.assertEqual(normalize_logs([row],2026),[])
    def test_espn_paired_shooting_stats_and_missing_optional_values(self):
        data={'filters':[{'name':'season','value':'2026'}],'labels':['MIN','PTS','REB','AST','3PT','FG','FT'],'events':{'g':{'gameResult':'W','gameDate':'2026-01-01T03:00:00Z','team':{'id':'13'}}},'seasonTypes':[{'displayName':'2025-26 Regular Season','categories':[{'type':'event','events':[{'eventId':'g','stats':['30','20','5','4','2-6','7-15','4-5']}]}]}]}
        r=normalize_espn_logs(data,2026,'p','Player')[0]
        self.assertEqual((r['FGM'],r['FGA'],r['FG3A'],r['FTM'],r['FTA']),(7,15,6,4,5))
        data['seasonTypes'][0]['categories'][0]['events'][0]['stats'][-1]='--'
        r=normalize_espn_logs(data,2026,'p','Player')[0]
        self.assertIsNone(r['FTA']);self.assertEqual(r['PTS'],20)
        data['seasonTypes'][0]['categories'][0]['events'][0]['stats'][4]='2-1'
        self.assertEqual(normalize_espn_logs(data,2026,'p','Player'),[])


if __name__=='__main__':unittest.main()
