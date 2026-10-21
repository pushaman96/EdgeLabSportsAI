import unittest
from datetime import datetime,timezone
from pick_history import verified_pregame_start
from forecast_tracking import freeze


class PregameTests(unittest.TestCase):
    def test_earlier_official_start_rejects_later_sportsbook_time(self):
        now=datetime(2026,10,21,1,54,tzinfo=timezone.utc)
        event={'date':'2026-10-21T01:50:00Z','status':{'type':{'state':'pre'}}}
        with self.assertRaises(ValueError):verified_pregame_start(event,'2026-10-21T01:55:00Z',now)
    def test_live_status_rejects_even_if_both_schedules_are_in_future(self):
        now=datetime(2026,10,21,1,40,tzinfo=timezone.utc)
        event={'date':'2026-10-21T01:50:00Z','competitions':[{'status':{'type':{'state':'in'}}}]}
        with self.assertRaises(ValueError):verified_pregame_start(event,'2026-10-21T01:55:00Z',now)
    def test_freeze_uses_earlier_time_and_saves_both_sources_without_mutating_row(self):
        now=datetime(2026,10,21,1,40,tzinfo=timezone.utc)
        row={'Game':'A at B','Player':'Player','Category':'Points','Decision':'Watch — experimental','Selection':'Under','Line':15.5,'Odds':-110,'Sportsbook':'Book','Estimated win %':60,'Model':'fixture','Quote updated UTC':now.isoformat()}
        event={'away_team':'A','home_team':'B','commence_time':'2026-10-21T01:55:00Z'}
        board={'events':[{'id':'espn','name':'A at B','date':'2026-10-21T01:50:00Z','season':{'type':2},'status':{'type':{'state':'pre'}}}]}
        records=freeze([row],[event],board,sport='NBA',now=now)
        self.assertEqual(records[0]['starts_utc'],'2026-10-21T01:50:00+00:00')
        self.assertEqual(records[0]['source_audit']['Odds scheduled start UTC'],event['commence_time'])
        self.assertEqual(records[0]['source_audit']['ESPN scheduled start UTC'],board['events'][0]['date'])
        self.assertNotIn('Odds scheduled start UTC',row)
        board['events'][0]['status']['type']['state']='in'
        self.assertEqual(freeze([row],[event],board,sport='NBA',now=now),[])


if __name__=='__main__':unittest.main()
