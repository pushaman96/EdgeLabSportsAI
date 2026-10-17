import copy,unittest
from datetime import datetime,timezone
from pick_presentation import team_color,accent_html,badge_html,pick_status,filter_matchup
class PresentationTests(unittest.TestCase):
    def test_team_colors_reject_markup(self):
        self.assertEqual(team_color('123ABC'),'#123ABC')
        self.assertEqual(team_color('<script>'),'#64748b')
        self.assertNotIn('<script>',accent_html('<script>'))
        self.assertNotIn('<script>',badge_html('<script>'))
    def test_live_under_is_not_won(self):
        self.assertEqual(pick_status({'result':'Pending'},{'Final result':'Pending','Live position':'Below line — game ongoing'}),'Live')
        self.assertEqual(pick_status({'result':'Pending'},{'Final result':'Win','Live position':'Final'}),'Won')
        self.assertEqual(pick_status({'result':'Pending'},{'Final result':'Pending','Live position':'Final — stat missing; settlement review needed'}),'Final · review needed')
    def test_unknown_feed_does_not_invent_live_state(self):
        r={'result':'Pending','starts_utc':'2026-10-18T17:00:00Z'}
        self.assertEqual(pick_status(r,now=datetime(2026,10,17,tzinfo=timezone.utc)),'Pregame')
        self.assertEqual(pick_status(r,now=datetime(2026,10,19,tzinfo=timezone.utc)),'Awaiting update')
    def test_matchup_filter_preserves_original_records(self):
        records=[{'id':'a','game':'Away at Home'},{'id':'b','game':'Other at Team'}];before=copy.deepcopy(records)
        self.assertEqual(len(filter_matchup(records,'All games')),2)
        self.assertEqual(filter_matchup(records,'Away at Home'),[records[0]])
        self.assertEqual(records,before)
