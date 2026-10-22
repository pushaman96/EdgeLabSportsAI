import sys
import types
import unittest
from unittest.mock import patch
from sportsbook_presets import STANDARD_PRESETS,NBA_EXTRA_MARKETS,preset_budget,archive_market_board
class PresetTests(unittest.TestCase):
    def test_nba_categories_and_credit_budget(self):
        self.assertEqual(len(STANDARD_PRESETS['NBA']),5)
        self.assertEqual(preset_budget('NBA',5),28)
        self.assertEqual(NBA_EXTRA_MARKETS['PRA — points + rebounds + assists'],'player_points_rebounds_assists')
        self.assertEqual(NBA_EXTRA_MARKETS['Free throws attempted'],'player_frees_attempts')
        self.assertNotIn('player_field_goal_attempts',NBA_EXTRA_MARKETS.values())
    def test_archives_quotes_separately_from_recommendations(self):
        calls=[];mock=types.ModuleType('automatic_reports');mock.autosave_report=lambda *a,**k:calls.append((a,k))
        with patch.dict(sys.modules,{'automatic_reports':mock}):archive_market_board([dict(id='one'),dict(id='two')],'time','NBA')
        self.assertEqual(len(calls),3)
        self.assertEqual(calls[0][1]['file_name'],'nba_market_one.json')
        self.assertIn('not model recommendations',calls[0][0][1])
        self.assertEqual(calls[-1][1]['file_name'],'nba_loaded_market_board.json')

class AutomaticRotationTests(unittest.TestCase):
    def test_days_budget_and_repeat_block(self):
        from datetime import date
        from sportsbook_presets import automatic_plan
        sunday=date(2026,10,18)
        self.assertEqual(automatic_plan('NFL',sunday,sunday,8,'Credit-saving mode',False)['max_games'],1)
        self.assertFalse(automatic_plan('NFL',sunday,sunday,8,'Credit-saving mode',True)['enabled'])
        tuesday=date(2026,10,20)
        self.assertFalse(automatic_plan('NFL',tuesday,tuesday,8,'Standard mode',False)['enabled'])
        self.assertTrue(automatic_plan('NBA',tuesday,tuesday,8,'Standard mode',False)['enabled'])
        self.assertFalse(automatic_plan('NBA',tuesday,tuesday,7,'Standard mode',False)['enabled'])
        self.assertFalse(automatic_plan('NBA',tuesday,tuesday,8,'Saved data only — 0 credits',False)['enabled'])


class SelectionRecoveryTests(unittest.TestCase):
    def test_date_change_removes_stale_widget_values(self):
        from sportsbook_presets import reconcile_prop_selection
        state={'sportsbook_props_game_NFL':'old','credit_saver_games_NFL':['old','new'],'sportsbook_props_categories_NFL':['Passing yards','removed']}
        reconcile_prop_selection(state,'NFL',['new'],['Passing yards','Receiving yards'])
        self.assertEqual(state['sportsbook_props_game_NFL'],'__multiple_prop_games__')
        self.assertEqual(state['credit_saver_games_NFL'],['new'])
        self.assertEqual(state['sportsbook_props_categories_NFL'],['Passing yards'])
    def test_retains_started_game_and_user_choices(self):
        from sportsbook_presets import reconcile_prop_selection
        state={'sportsbook_props_game_NFL':'started','credit_saver_games_NFL':['started'],'sportsbook_props_categories_NFL':[]}
        reconcile_prop_selection(state,'NFL',['started','upcoming'],STANDARD_PRESETS['NFL'])
        self.assertEqual(state['sportsbook_props_game_NFL'],'started')
        self.assertEqual(state['credit_saver_games_NFL'],['started'])
        self.assertEqual(state['sportsbook_props_categories_NFL'],[])
    def test_nfl_four_market_budget(self):
        self.assertEqual(STANDARD_PRESETS['NFL'],['Passing yards','Rushing yards','Anytime touchdown scorer','Receiving yards'])
        self.assertEqual(preset_budget('NFL',2),11)
