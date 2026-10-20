import copy
import unittest
from datetime import date,timedelta
from types import SimpleNamespace
from unittest.mock import patch
import sys
import nba_prop_model as model
from nba_season_prior import season_projection,normalize_espn_logs

class SeasonPriorTests(unittest.TestCase):
    def rows(self,season=2026,team='A',n=20,start='2026-01-01',points=20,minutes=30):
        return [dict(player='p',name='Player',team=team,season=season,date=(date.fromisoformat(start)+timedelta(days=i)).isoformat(),game=str(season)+str(i),minutes=minutes,PTS=points,REB=6,AST=4,FG3M=2) for i in range(n)]
    def test_opening_day_uses_prior_season_without_new_games(self):
        f=season_projection(self.rows(),'PTS',2027,'A','2026-10-20')
        self.assertEqual(f['projected'],20);self.assertEqual(f['current_games'],0)
        self.assertEqual(f['current_weight'],0);self.assertFalse(f['role_uncertain']);self.assertGreater(f['uncertainty'],1)
    def test_new_season_blends_gradually(self):
        prior=self.rows();current=self.rows(2027,n=8,start='2026-10-20',points=30)
        early=season_projection(prior+current[:1],'PTS',2027,'A','2026-11-01')
        later=season_projection(prior+current,'PTS',2027,'A','2026-11-01')
        self.assertAlmostEqual(early['current_weight'],1/9)
        self.assertEqual(later['current_weight'],.5);self.assertAlmostEqual(later['projected'],25)
    def test_prior_is_full_season_not_recent_hot_stretch(self):
        prior=self.rows(n=40);prior[-1]['PTS']=60
        self.assertAlmostEqual(season_projection(prior,'PTS',2027,'A','2026-10-20')['projected'],21)
    def test_future_and_same_day_stats_cannot_change_forecast(self):
        prior=self.rows();future=self.rows(2027,start='2026-10-20',points=999)
        self.assertEqual(season_projection(prior,'PTS',2027,'A','2026-10-20'),season_projection(prior+future,'PTS',2027,'A','2026-10-20'))
    def test_trade_does_not_claim_verified_role(self):
        f=season_projection(self.rows(),'PTS',2027,'B','2026-10-20')
        self.assertTrue(f['team_changed']);self.assertTrue(f['role_uncertain'])
        current=self.rows(2027,'B',3,'2026-10-20',points=10,minutes=15)
        f=season_projection(self.rows()+current,'PTS',2027,'B','2026-11-01')
        self.assertFalse(f['role_uncertain']);self.assertLess(f['minutes'],30)
    def test_rookie_or_older_season_is_not_invented(self):
        self.assertIsNone(season_projection(self.rows(n=7),'PTS',2027,'A','2026-10-20'))
        self.assertIsNone(season_projection(self.rows(season=2025),'PTS',2027,'A','2026-10-20'))
    def test_research_is_chronological_and_exposes_opening_cohorts(self):
        logs=self.rows(2024,start='2023-11-01')+self.rows(2025,start='2024-11-01')+self.rows(2026,start='2025-11-01')
        a=model.research(logs,'2026-10-20');b=model.research(logs+self.rows(2027,start='2026-10-20',points=999),'2026-10-20')
        self.assertEqual(a,b)
        self.assertIn(('PTS','Early season (0–7 appearances)'),a['cohort_reports'])
        self.assertGreater(a['cohort_reports']['PTS','Early season (0–7 appearances)']['validation_games'],0)

class EspnLogTests(unittest.TestCase):
    def payload(self):
        return dict(filters=[dict(name='season',value='2026')],labels=['MIN','PTS','REB','AST','3PT'],events={'g':dict(gameResult='W',gameDate='2026-01-01T03:00:00Z',team=dict(id='13'))},seasonTypes=[dict(displayName='2025-26 Regular Season',categories=[dict(type='event',events=[dict(eventId='g',stats=['30:30','20','6','4','2-5'])])]),dict(displayName='2025-26 Postseason',categories=[dict(type='event',events=[dict(eventId='g',stats=['40','99','99','99','9-9'])])])])
    def test_explicit_regular_season_and_source_ids(self):
        rows=normalize_espn_logs(self.payload(),2026,'1966','Player')
        self.assertEqual(len(rows),1);self.assertEqual(rows[0]['PTS'],20);self.assertEqual(rows[0]['minutes'],30.5)
        self.assertEqual(rows[0]['player'],'espn:1966');self.assertEqual(rows[0]['team'],'13')
    def test_season_mismatch_missing_stats_and_duplicates(self):
        with self.assertRaises(ValueError):normalize_espn_logs(self.payload(),2027,'1966','Player')
        d=self.payload();d['seasonTypes'][0]['categories'][0]['events'][0]['stats'][1]='--'
        self.assertEqual(normalize_espn_logs(d,2026,'1966','Player'),[])
        d=self.payload();d['seasonTypes'][0]['categories'][0]['events']*=2
        with self.assertRaises(ValueError):normalize_espn_logs(d,2026,'1966','Player')
    def test_fallback_preserves_prior_when_current_request_fails(self):
        st=SimpleNamespace(cache_data=lambda **kwargs:lambda fn:fn)
        def fetch(year,pid,name):
            if year==2027:raise TimeoutError()
            return [dict(season=year,player='espn:'+pid)]
        with patch.dict(sys.modules,{'streamlit':st}),patch.object(model,'_try_load_data',return_value=None),patch.object(model,'fetch_espn_logs',side_effect=fetch):
            data=model.load_data(2027,(('1966','Player'),))
        self.assertEqual(len(data['logs']),3);self.assertIn('espn:1966',data['missing_current'])
        self.assertEqual(data['id_namespace'],'ESPN')

if __name__=='__main__':unittest.main()
