import unittest
from datetime import datetime,timezone,timedelta
from game_day_diagnostics import software_status,evidence,pacific_day
NOW=datetime(2026,10,21,20,tzinfo=timezone.utc)
class DiagnosticTests(unittest.TestCase):
    def report(self,**kw):
        r=dict(passed=True,tests_run=238,tests_skipped=1,checked_utc=NOW.isoformat(),pacific_date=pacific_day(NOW),source_hash='code');r.update(kw);return r
    def row(self,**kw):
        r={'Decision':'Watch — experimental','Quote updated UTC':NOW.isoformat(),'Estimated win %':60,'Validation':{'passed':True,'calibration_examples':500,'validation_games':272}};r.update(kw);return r
    def test_good_health_and_actual_history_counts_are_distinct(self):
        a=evidence(self.row(),self.report(),NOW,'code')
        self.assertTrue(a['ready']);self.assertEqual(a['software']['tests_run'],238);self.assertEqual(a['later_historical_games_or_examples'],272)
    def test_changes_failures_and_stale_runs_do_not_qualify(self):
        self.assertFalse(software_status(self.report(),NOW,'new-code')['passed'])
        self.assertFalse(software_status(self.report(passed=False),NOW,'code')['passed'])
        self.assertFalse(software_status(self.report(),NOW+timedelta(hours=4),'code')['passed'])
    def test_old_quote_failed_model_and_missing_probability_do_not_qualify(self):
        for row in (self.row(**{'Quote updated UTC':(NOW-timedelta(minutes=16)).isoformat()}),self.row(Validation={'passed':False}),self.row(**{'Estimated win %':None})):
            self.assertFalse(evidence(row,self.report(),NOW,'code')['ready'])
        self.assertFalse(evidence(self.row(**{'Estimated win %':True}),self.report(),NOW,'code')['ready'])
    def test_existing_pass_is_not_promoted_and_no_invented_samples(self):
        a=evidence(self.row(Decision='Pass',Validation={'passed':True}),self.report(),NOW,'code')
        self.assertFalse(a['ready']);self.assertIsNone(a['later_historical_games_or_examples'])
    def test_previous_pacific_day_does_not_qualify(self):
        self.assertFalse(software_status(self.report(pacific_date='2026-10-20'),NOW,'code')['passed'])
if __name__=='__main__':unittest.main()
