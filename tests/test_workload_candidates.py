import copy
import unittest
from workload_candidates import evaluate,attach,nba_sample,nfl_sample
from nfl_season_prior import indexes
import test_nfl_season_prior as nfl_fixtures
import test_nba_season_prior as nba_fixtures

class WorkloadTests(unittest.TestCase):
    def test_weight_uses_earlier_training_not_validation_outcomes(self):
        f=dict(base=10,target=20,base_stat=100,baseline_workload=10,actual_workload=20,actual_stat=200)
        samples=[(('field','stage'),'train',str(i),f)for i in range(60)]+[(('field','stage'),'test',str(i),f)for i in range(25)]
        report=evaluate(samples)['field','stage'];self.assertEqual(report['weight'],1);self.assertTrue(report['passed'])
        altered=[(k,p,g,dict(v,actual_workload=0,actual_stat=0)if p=='test'else v)for k,p,g,v in samples]
        self.assertEqual(evaluate(altered)['field','stage']['weight'],1)
        self.assertFalse(evaluate(altered)['field','stage']['passed'])
    def test_research_attachment_preserves_pick_and_probability(self):
        row=dict(Decision='Pass',Selection='Under',probability=.65,**{'Estimated win %':65,'Projection (yards)':100})
        original=copy.deepcopy(row);f=dict(base=10,target=20,base_stat=100,history=[dict(work=5+i)for i in range(8)],workload_field='work')
        attach(row,f,dict(weight=1,status='Research only'),['Absent Player'])
        for key,value in original.items():self.assertEqual(row[key],value)
        self.assertEqual(row['Workload candidate projection'],200)
        self.assertEqual(len(row['Workload sensitivity scenarios']),3)
        self.assertIn('not automatically assigned',row['Lineup scenario limitation'])
    def test_nfl_candidate_joins_team_game_and_excludes_future(self):
        p,t=nfl_fixtures.NflSeasonPriorTests().fixture();r=dict(p[-2],season=2026,week=1)
        f=nfl_sample(r,'player_pass_yds',indexes(p,t));self.assertEqual(f['target'],30)
        future=dict(r,game_id='future',attempts=99999,passing_yards=99999)
        self.assertEqual(f,nfl_sample(r,'player_pass_yds',indexes(p+[future],t+[future])))
    def test_nba_candidate_uses_only_previous_minutes_and_flags_new_team(self):
        h=nba_fixtures.SeasonPriorTests().rows();r=dict(player='p',team='A',season=2027,date='2026-10-20')
        f=nba_sample(r,h,'PTS');self.assertEqual(f['target'],30)
        self.assertIsNone(nba_sample(dict(r,team='NEW'),h,'PTS'))
        future=dict(h[0],season=2027,date='2026-10-20',minutes=99)
        self.assertEqual(f,nba_sample(r,h+[future],'PTS'))
    def test_short_training_keeps_zero_weight_and_no_promotion(self):
        f=dict(base=10,target=20,base_stat=100,baseline_workload=10,actual_workload=20,actual_stat=200)
        r=evaluate([(('x','y'),'train','1',f),(('x','y'),'test','2',f)])['x','y']
        self.assertEqual(r['weight'],0);self.assertFalse(r['passed'])

if __name__=='__main__':unittest.main()

class SavedCandidateReviewTests(unittest.TestCase):
    def test_only_frozen_prospective_complete_comparisons_count_once(self):
        from workload_candidates import saved_reviews
        r=dict(sport='NFL',event_id='game',player='Player',category='Passing yards',strategy='Original',evidence='Personal paper record',season_type='Regular season',published_utc='2026-10-19T12:00:00Z',starts_utc='2026-10-19T20:00:00Z',result='Win',actual=200,actual_opportunities=30,forecast_context={'Workload candidate version':'workload-candidates-v1','Workload candidate opportunities':29,'Workload candidate baseline opportunities':25,'Workload candidate projection':210,'Workload candidate baseline projection':230})
        rows=[r,dict(r,strategy='Analysis'),dict(r,event_id='late',published_utc='2026-10-20T00:00:00Z'),dict(r,event_id='manual',strategy='Manual'),dict(r,event_id='missing',actual_opportunities=None)]
        report=saved_reviews(rows)
        self.assertEqual(len(report['groups']),1)
        g=report['groups'][0];self.assertEqual(g['forecasts'],1);self.assertEqual(g['candidate_workload_mae'],1);self.assertEqual(g['baseline_workload_mae'],5)
        self.assertNotIn('Player',str(report));self.assertNotIn('game',g)
    def test_missing_is_not_zero_and_preseason_not_combined(self):
        from workload_candidates import saved_reviews
        self.assertEqual(saved_reviews([dict(strategy='Original',evidence='Historical import',season_type='Regular season')])['groups'],[])
