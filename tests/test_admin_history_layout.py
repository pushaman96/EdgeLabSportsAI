import sys,types,unittest
from unittest.mock import MagicMock,patch
import dashboard_history
class AdminHistoryLayoutTests(unittest.TestCase):
    def modules(self,calls):
        specs={'live_pick_board':['render_live_board'],'game_day_diagnostics':['render'],'pick_history':['sync_session_records'],'automatic_reports':['render_storage_status'],'nba_calibration':['render'],'slate_review':['render_review'],'pick_learning':['render_feedback'],'learning_audit':['render'],'validate_prediction_research':['render'],'background_research':['render'],'nfl_scoring_models':['render_validation']}
        modules={}
        for name,functions in specs.items():
            module=types.ModuleType(name)
            for function in functions:
                setattr(module,function,lambda *a,_name=name,**k:calls.append(_name))
            modules[name]=module
        st=MagicMock();st.session_state={};st.columns.return_value=[MagicMock(),MagicMock(),MagicMock()]
        modules['streamlit']=st
        return modules
    def test_main_page_keeps_board_and_accuracy_without_admin_panels(self):
        calls=[]
        with patch.dict(sys.modules,self.modules(calls)),patch.object(dashboard_history,'tracked_records',return_value=[]):
            dashboard_history.render_public_history('NFL')
        self.assertIn('live_pick_board',calls)
        self.assertIn('nba_calibration',calls)
        self.assertFalse(set(calls)&{'automatic_reports','pick_learning','learning_audit','validate_prediction_research','background_research','nfl_scoring_models'})
    def test_owner_admin_renders_all_moved_panels(self):
        calls=[]
        with patch('app_view.is_research',return_value=True),patch.dict(sys.modules,self.modules(calls)):
            dashboard_history.render_admin_panels([],'NFL')
        self.assertTrue({'automatic_reports','pick_learning','learning_audit','validate_prediction_research','background_research','nfl_scoring_models'}.issubset(calls))
    def test_direct_call_cannot_bypass_owner_view(self):
        calls=[]
        with patch('app_view.is_research',return_value=False),patch.dict(sys.modules,self.modules(calls)):
            dashboard_history.render_admin_panels([],'NFL')
        self.assertEqual(calls,[])
