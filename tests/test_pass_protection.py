import unittest
from pass_protection import profiles,matchup
class ProtectionTests(unittest.TestCase):
    def fixtures(self):
        games=[];rows=[]
        for week in range(1,6):
            ident=str(week);games.append(dict(game_id=ident,gameday=f'2026-09-{week:02}',home_score='20',away_score='10'))
            rows.extend([dict(game_id=ident,team='A',opponent_team='B',season_type='REG',attempts='30',sacks_suffered='2',def_qb_hits='5'),dict(game_id=ident,team='B',opponent_team='A',season_type='REG',attempts='20',sacks_suffered='4',def_qb_hits='6')])
        return rows,games
    def test_rates_use_opponent_dropbacks_and_prior_games_only(self):
        rows,games=self.fixtures();data=profiles(rows,games,'2026-09-05')
        self.assertEqual(data['A']['Games'],4)
        self.assertEqual(data['A']['Sacks allowed'],8)
        self.assertAlmostEqual(data['A']['Defensive sack rate %'],100*4/24)
        self.assertAlmostEqual(matchup(data['A'],data['B']),4)
    def test_missing_sacks_not_zero_and_small_sample_withheld(self):
        rows,games=self.fixtures();rows[0]['sacks_suffered']=''
        data=profiles(rows,games,'2026-09-03')
        self.assertEqual(data['A']['Games'],1)
        self.assertIsNone(matchup(data['A'],data['B']))
