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

    def test_existing_uncertain_research_is_not_labeled_missing(self):
        board,report=fixtures()
        for p in report['sports']['NBA']['projections']:p['role_uncertain']=True
        result=build(report,'NBA',board,NOW)
        self.assertEqual(result['all_games'][0]['Research priority'],'Research available — role caution')
        self.assertEqual(result['all_games'][0]['Prepared forecasts'],4)
    def test_recent_report_does_not_refresh_old_game_forecasts(self):
        board,report=fixtures()
        for p in report['sports']['NBA']['projections']:p['published_utc']='2026-10-22T10:00:00Z'
        result=build(report,'NBA',board,NOW)
        self.assertFalse(result['shortlist'])
        self.assertEqual(result['all_games'][0]['Research priority'],'Research available — refresh needed')

class FreeResearchHorizonTests(unittest.TestCase):
    def test_nfl_can_prepare_sunday_from_friday_without_odds(self):
        from unittest.mock import patch
        import background_research as bg
        now=datetime(2026,10,23,12,tzinfo=timezone.utc)
        event={'id':'sunday','date':'2026-10-25T17:00:00Z','season':{'type':2},'status':{'type':{'state':'pre','completed':False}}}
        urls=[]
        def free_get(url):
            urls.append(url)
            return {'events':[event]}
        with patch.object(bg,'get',side_effect=free_get):
            result=bg.boards('NFL',now)
        self.assertEqual([e['id'] for e in result['events']],['sunday'])
        self.assertEqual(len(urls),4)
        self.assertTrue(all(url.startswith('https://site.api.espn.com/') for url in urls))
        self.assertFalse(bg.upcoming(event,now))
        self.assertTrue(bg.upcoming(event,now,hours=72))
