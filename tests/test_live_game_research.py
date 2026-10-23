import unittest
from datetime import datetime, timezone
from live_game_research import observe

class LiveResearchTests(unittest.TestCase):
    def test_snapshot_missing_stats_and_frozen_pick(self):
        now=datetime(2026,10,23,1,tzinfo=timezone.utc)
        r={'id':'p','strategy':'Original','evidence':'Published before kickoff','starts_utc':'2026-10-23T00:00:00Z','sport':'NFL','event_id':'e','category':'Receiving yards','player':'Receiver','game':'A at B','line':40,'result':'Pending'}
        data={'header':{'id':'e','competitions':[{'status':{'type':{'state':'in'}}}]}}
        output,errors=observe([r],{},lambda *args:data,now)
        self.assertFalse(errors)
        self.assertIsNone(output['NFL:e']['observations'][0]['pick_stats'][0]['observed_stat'])
        self.assertEqual(r['result'],'Pending')
        self.assertEqual(r['line'],40)
    def test_wrong_game_never_archived(self):
        r={'id':'p','strategy':'Original','starts_utc':'2026-10-23T00:00:00Z','event_id':'e'}
        output,errors=observe([r],{},lambda *args:{'header':{'id':'wrong'}},datetime(2026,10,23,1,tzinfo=timezone.utc))
        self.assertEqual(output,{})
        self.assertEqual(len(errors),1)
    def test_future_manual_and_imports_not_fetched(self):
        rows=[{'strategy':'Manual'},{'strategy':'Original','evidence':'Historical import'},{'strategy':'Original','starts_utc':'2027-01-01T00:00:00Z'}]
        output,errors=observe(rows,{},lambda *args:self.fail('unexpected request'),datetime(2026,10,23,1,tzinfo=timezone.utc))
        self.assertEqual(output,{})
        self.assertFalse(errors)
