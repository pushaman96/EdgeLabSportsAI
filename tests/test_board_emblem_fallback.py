import unittest
from datetime import datetime,timezone,timedelta
from team_emblems import roster_emblems,pick_team
from live_pick_board import build_board
class BoardEmblemTests(unittest.TestCase):
    def setUp(self):
        self.assets={'NFL:Away':dict(id='1',name='Away',logo='https://a.espncdn.com/away.png'),'NFL:Home':dict(id='2',name='Home',logo='https://a.espncdn.com/home.png')}
        self.row=dict(id='one',event_id='event',category='Anytime touchdown',game='Away at Home',sport='NFL',player='Player',direction='Over',line=.5,probability=.6,starts_utc=(datetime.now(timezone.utc)+timedelta(hours=2)).isoformat())
    def test_old_player_pick_unique_roster_gets_logo(self):
        assets=roster_emblems([self.row],self.assets,{'Home':[dict(name='Player')]},'NFL')
        self.assertEqual(pick_team(self.row,index=assets)['name'],'Home')
    def test_ambiguous_player_is_not_guessed(self):
        assets=roster_emblems([self.row],self.assets,{'Home':[dict(name='Player')],'Away':[dict(name='Player')]},'NFL')
        self.assertIsNone(pick_team(self.row,index=assets))
    def test_game_total_has_both_emblems_before_kickoff(self):
        row=build_board([dict(self.row,category='Game total points',player='Away at Home',direction='Under',line=50.5)],{},team_assets=self.assets)[0]
        self.assertEqual(row['Team logo'],self.assets['NFL:Away']['logo'])
        self.assertEqual(row['Opponent logo'],self.assets['NFL:Home']['logo'])
