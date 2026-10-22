"""Owner authorization shared by every Admin / Research section.

Configure [admin] password in Streamlit Secrets (at least 16 characters).
Admin / Research panels require owner sign-in.
When enabled, no configured password means no admin access.
"""
import hashlib
import hmac
import time

MAIN = "Main dashboard"
RESEARCH = "Admin / Research"
SESSION_SECONDS = 8 * 60 * 60
ADMIN_LOCK_ENABLED = True


def _password():
    import streamlit as st
    try:
        value = st.secrets.get("admin", {}).get("password", "")
    except (FileNotFoundError, KeyError):
        return ""
    return value if isinstance(value, str) and len(value.strip()) >= 16 else ""


def _proof(password, issued):
    return hmac.new(password.encode("utf-8"),
                    ("kamikaze-owner:" + repr(issued)).encode("utf-8"),
                    hashlib.sha256).hexdigest()


def is_admin():
    """Validate this session, expiry and current secret on every protected render."""
    if not ADMIN_LOCK_ENABLED:
        return True
    import streamlit as st
    password = _password()
    issued = st.session_state.get("_owner_issued")
    proof = st.session_state.get("_owner_proof")
    if not password or not isinstance(issued, (int, float)) or not isinstance(proof, str):
        return False
    if not 0 <= time.time() - issued < SESSION_SECONDS:
        return False
    return hmac.compare_digest(proof, _proof(password, issued))


def is_research():
    import streamlit as st
    return is_admin() and st.session_state.get("app_view_mode", MAIN) == RESEARCH


def _login():
    import streamlit as st
    candidate = st.session_state.pop("_owner_password_input", "")
    now = time.time()
    if now < st.session_state.get("_owner_retry_after", 0):
        st.session_state["_owner_login_error"] = "Please wait before trying again."
        return
    password = _password()
    if password and hmac.compare_digest(candidate.encode("utf-8"), password.encode("utf-8")):
        st.session_state["_owner_issued"] = now
        st.session_state["_owner_proof"] = _proof(password, now)
        st.session_state["app_view_mode"] = RESEARCH
        for key in ("_owner_login_error", "_owner_failures", "_owner_retry_after"):
            st.session_state.pop(key, None)
    else:
        failures = st.session_state.get("_owner_failures", 0) + 1
        st.session_state["_owner_failures"] = failures
        st.session_state["_owner_retry_after"] = now + min(60, 2 ** min(failures, 6))
        st.session_state["_owner_login_error"] = "Login failed. Check your password and try again shortly."


def _logout():
    import streamlit as st
    # Discard research widgets, loaded records and API credentials in this session.
    st.session_state.clear()


def render_owner_navigation():
    import streamlit as st
    if not ADMIN_LOCK_ENABLED:
        st.sidebar.radio("View", [MAIN, RESEARCH], key="app_view_mode")
        return
    if is_admin():
        st.sidebar.caption("Owner signed in")
        st.sidebar.radio("View", [MAIN, RESEARCH], key="app_view_mode")
        st.sidebar.button("Sign out of owner access", key="owner_logout", on_click=_logout)
        return
    # A stale widget value or manually supplied URL cannot authorize research.
    st.session_state["app_view_mode"] = MAIN
    st.session_state.pop("_owner_proof", None)
    st.session_state.pop("_owner_issued", None)
    with st.sidebar.expander("Owner sign in"):
        if not _password():
            st.caption("Owner access is locked. Configure your private admin password in Streamlit Secrets.")
            return
        with st.form("owner_login_form", clear_on_submit=True):
            st.text_input("Owner password", type="password", key="_owner_password_input")
            st.form_submit_button("Sign in", on_click=_login)
        if st.session_state.get("_owner_login_error"):
            st.error(st.session_state["_owner_login_error"])

