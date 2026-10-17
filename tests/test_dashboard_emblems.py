import copy
import unittest
from team_emblems import enrich_rows,team_index
class DashboardEmblemTests(unittest.TestCase):
    def test_all_league_aliases_and_display_copies(self):
        competitions=[{'competitors':[{'team':{'id':'1','displayName':'Golden State Warriors','abbreviation':'GS','logo':'https://a.espncdn.com/gs.png'}}]}]
        index=team_index(competitions,'NBA')
        rows=[{'Team':'GSW','Points/game':100}];before=copy.deepcopy(rows)
        shown=enrich_rows(rows,'NBA',index)
        self.assertEqual(shown[0]['Team emblem'],'https://a.espncdn.com/gs.png')
        self.assertEqual(rows,before)
    def test_quote_game_teams_get_both_logos(self):
        index={'NFL:Away':{'logo':'https://a.espncdn.com/a.png'},'NFL:Home':{'logo':'https://a.espncdn.com/h.png'}}
        shown=enrich_rows([{'Game':'Away at Home','Player':'QB'}],'NFL',index)
        self.assertIn('Away emblem',shown[0]);self.assertIn('Home emblem',shown[0])
