import unittest
from datetime import datetime,timezone
from credit_saver import spending_allowed,choose_targets,balance_record
class CreditSaverTests(unittest.TestCase):
    def test_zero_credit_and_saved_only_block_spending(self):
        self.assertFalse(spending_allowed('Credit-saving mode',2,10,0)[0])
        self.assertFalse(spending_allowed('Saved data only — 0 credits',2,10,100)[0])
    def test_budget_caps_and_unknown_balance(self):
        self.assertFalse(spending_allowed('Credit-saving mode',14,10,None)[0])
        self.assertTrue(spending_allowed('Credit-saving mode',2,10,None)[0])
        self.assertFalse(spending_allowed('Standard mode',14,500,10)[0])
    def test_only_selected_upcoming_games_are_requested(self):
        events=[dict(id='a',commence_time='2026-10-19T00:00:00Z'),dict(id='b',commence_time='2026-10-19T00:00:00Z'),dict(id='past',commence_time='2026-10-17T00:00:00Z')]
        selected=choose_targets(events,['a','past'],datetime(2026,10,18,tzinfo=timezone.utc))
        self.assertEqual([r['id'] for r in selected],['a'])
    def test_older_cached_balance_cannot_override_new_zero_balance(self):
        prior={'key_hash':'key','remaining':'0','checked':'2026-10-18T23:30:00Z'}
        self.assertEqual(balance_record(prior,'key','100','2026-10-18T22:00:00Z'),prior)
        self.assertEqual(balance_record(prior,'key','500','2026-11-01T00:00:00Z')['remaining'],'500')
