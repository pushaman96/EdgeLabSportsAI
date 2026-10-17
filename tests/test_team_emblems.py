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
