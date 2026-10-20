"""Authorization regression tests; no network or production credentials needed."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app_view


class OwnerAccessTests(unittest.TestCase):
    def setUp(self):
        # These tests exercise locked mode regardless of the deployment switch.
        lock = patch.object(app_view, "ADMIN_LOCK_ENABLED", True)
        lock.start()
        self.addCleanup(lock.stop)
        self.st = SimpleNamespace(session_state={}, secrets={"admin": {"password": "test-only-owner-password-123"}})
        self.streamlit = patch.dict(sys.modules, {"streamlit": self.st})
        self.streamlit.start()
        self.addCleanup(self.streamlit.stop)

    def login(self, password="test-only-owner-password-123"):
        self.st.session_state["_owner_password_input"] = password
        app_view._login()

    def test_view_selection_alone_cannot_authorize(self):
        self.st.session_state["app_view_mode"] = app_view.RESEARCH
        self.st.session_state["password_correct"] = True
        self.assertFalse(app_view.is_research())

    def test_missing_blank_or_short_configuration_denies_access(self):
        for secrets in ({}, {"admin": {"password": ""}}, {"admin": {"password": "short"}}):
            self.st.secrets = secrets
            self.login("")
            self.assertFalse(app_view.is_admin())

    def test_wrong_password_is_removed_and_cannot_open_research(self):
        self.login("wrong")
        self.assertFalse(app_view.is_research())
        self.assertNotIn("_owner_password_input", self.st.session_state)
        self.assertGreater(self.st.session_state["_owner_retry_after"], app_view.time.time())

    def test_valid_login_and_logout(self):
        self.login()
        self.assertTrue(app_view.is_admin())
        self.assertTrue(app_view.is_research())
        self.assertNotIn("_owner_password_input", self.st.session_state)
        self.st.session_state["app_view_mode"] = app_view.MAIN
        self.assertFalse(app_view.is_research())
        self.st.session_state["private_loaded_records"] = [1]
        app_view._logout()
        self.assertFalse(app_view.is_admin())
        self.assertEqual(self.st.session_state, {})

    def test_separate_visitor_session_is_not_authorized(self):
        self.login()
        self.st.session_state = {"app_view_mode": app_view.RESEARCH}
        self.assertFalse(app_view.is_research())

    def test_password_rotation_or_removal_revokes_access(self):
        self.login()
        self.st.secrets["admin"]["password"] = "different-owner-password-456"
        self.assertFalse(app_view.is_admin())
        self.st.secrets = {}
        self.assertFalse(app_view.is_research())

    def test_expired_or_tampered_session_is_denied(self):
        self.login()
        issued = self.st.session_state["_owner_issued"]
        with patch.object(app_view.time, "time", return_value=issued + app_view.SESSION_SECONDS):
            self.assertFalse(app_view.is_research())
        self.st.session_state["_owner_proof"] = "forged"
        self.assertFalse(app_view.is_admin())



class UnlockedAccessTests(unittest.TestCase):
    def test_research_is_available_without_password_when_lock_disabled(self):
        st = SimpleNamespace(session_state={"app_view_mode": app_view.RESEARCH}, secrets={})
        with patch.dict(sys.modules, {"streamlit": st}), patch.object(app_view, "ADMIN_LOCK_ENABLED", False):
            self.assertTrue(app_view.is_admin())
            self.assertTrue(app_view.is_research())
            st.session_state["app_view_mode"] = app_view.MAIN
            self.assertFalse(app_view.is_research())

    def test_unlocked_navigation_offers_both_views_without_login(self):
        calls = []
        def radio(label, options, key):
            calls.append((label, options, key))
        st = SimpleNamespace(session_state={}, secrets={}, sidebar=SimpleNamespace(radio=radio))
        with patch.dict(sys.modules, {"streamlit": st}), patch.object(app_view, "ADMIN_LOCK_ENABLED", False):
            app_view.render_owner_navigation()
        self.assertEqual(calls, [("View", [app_view.MAIN, app_view.RESEARCH], "app_view_mode")])


if __name__ == "__main__":
    unittest.main()
