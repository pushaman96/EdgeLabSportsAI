import unittest
from datetime import datetime,timezone
from free_game_shortlist import build
NOW=datetime(2026,10,23,12,tzinfo=timezone.utc)
START='2026-10-23T20:00:00Z'
def fixtures():
    board={'season':{'type':2},'events':[{'id':'e','date':START,'name':'A at B','status':{'type':{'state':'pre'}}}]}
    rows=[{'event_id':'e','starts_utc':START,'published_utc':'2026-10-23T10:00:00Z','player':p,'category':c,'projection':10,'workload':25,'role_uncertain':False} for p in ('One','Two') for c in ('Points','Assists')]
    report={'generated_utc':'2026-10-23T10:00:00Z','sports':{'NBA':{'projections':rows}}}
    return board,report
class FreeShortlistTests(unittest.TestCase):
    def test_ready_game_and_no_mutation(self):
        board,report=fixtures();result=build(report,'NBA',board,NOW)
        self.assertEqual(len(result['shortlist']),1)
        self.assertEqual(result['shortlist'][0]['Categories to inspect'],'Assists, Points')
        self.assertEqual(report['sports']['NBA']['projections'][0]['projection'],10)
    def test_stale_research_not_shortlisted(self):
        board,report=fixtures();report['generated_utc']='2026-10-22T10:00:00Z'
        self.assertFalse(build(report,'NBA',board,NOW)['shortlist'])
    def test_uncertain_roles_do_not_qualify(self):
        board,report=fixtures()
        for p in report['sports']['NBA']['projections']:p['role_uncertain']=True
        self.assertFalse(build(report,'NBA',board,NOW)['shortlist'])
    def test_started_and_wrong_game_excluded(self):
        board,report=fixtures();board['events'][0]['status']['type']['state']='in'
        self.assertFalse(build(report,'NBA',board,NOW)['all_games'])
        board['events'][0]['status']['type']['state']='pre'
        for p in report['sports']['NBA']['projections']:p['event_id']='wrong'
        self.assertFalse(build(report,'NBA',board,NOW)['shortlist'])
