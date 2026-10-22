import copy
import unittest
from team_emblems import logo_url,team_index,pick_team,render_team_score
class EmblemTests(unittest.TestCase):
    def competition(self):return {'competitors':[{'team':{'id':'14','displayName':'Los Angeles Rams','abbreviation':'LAR','logo':'https://a.espncdn.com/i/teamlogos/nfl/500/lar.png'}}]}
    def test_pregame_frozen_team_alias(self):
        index=team_index([self.competition()],'NFL')
        record={'sport':'NFL','player':'QB','category':'Passing yards','forecast_context':{'Current roster team':'LA'}}
        original=copy.deepcopy(record)
        self.assertEqual(pick_team(record,index=index)['name'],'Los Angeles Rams')
        self.assertEqual(record,original)
    def test_moneyline_and_unknown(self):
        index=team_index([self.competition()],'NFL')
        self.assertIsNotNone(pick_team({'category':'Moneyline','player':'Los Angeles Rams'},index=index))
        self.assertIsNone(pick_team({'category':'Points','player':'Unknown','sport':'NBA'},index=index))
    def test_logo_hosts_and_missing_assets(self):
        self.assertIsNone(logo_url({'logo':'https://example.com/logo.png'}))
        self.assertIsNone(logo_url({}))
        self.assertEqual(logo_url({'logos':[{'href':'https://a.espncdn.com/logo.png'}]}),'https://a.espncdn.com/logo.png')
    def test_score_text_survives_missing_logo(self):
        class Column:
            def metric(self,*a):self.result=a
        column=Column();render_team_score(column,{'displayName':'Home'},'17')
        self.assertEqual(column.result,('Home','17'))

    def test_nba_punctuation_matches_team_without_changing_pick(self):
        teams=[{'id':'19','displayName':'Orlando Magic','logo':'https://a.espncdn.com/i/teamlogos/nba/500/orl.png'},
               {'id':'1','displayName':'Atlanta Hawks','logo':'https://a.espncdn.com/i/teamlogos/nba/500/atl.png'}]
        data={'header':{'competitions':[{'competitors':[{'team':t} for t in teams]}]},
              'boxscore':{'players':[{'team':teams[0],'statistics':[{'athletes':[{'athlete':{'displayName':'Wendell Carter Jr.'}}]}]},
                                     {'team':teams[1],'statistics':[{'athletes':[{'athlete':{'displayName':'CJ McCollum'}}]}]}]}}
        for player,expected in (('Wendell Carter Jr','Orlando Magic'),('C.J. McCollum','Atlanta Hawks')):
            record={'sport':'NBA','category':'Three-pointers made','player':player}
            before=copy.deepcopy(record)
            emblem=pick_team(record,data)
            self.assertEqual(emblem['name'],expected)
            self.assertTrue(emblem['logo'])
            self.assertEqual(record,before)

    def test_ambiguous_athlete_team_stays_unknown(self):
        teams=[{'id':'1','displayName':'Away'},{'id':'2','displayName':'Home'}]
        data={'header':{'competitions':[{'competitors':[{'team':t} for t in teams]}]},
              'boxscore':{'players':[{'team':t,'statistics':[{'athletes':[{'athlete':{'displayName':'Same Player'}}]}]} for t in teams]}}
        self.assertIsNone(pick_team({'sport':'NBA','category':'Points','player':'Same Player'},data))

