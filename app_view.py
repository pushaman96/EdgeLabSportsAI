"""Presentation-only switch. It does not authorize access or change model logic."""
def is_research():
    import streamlit as st
    return st.session_state.get('app_view_mode','Main dashboard')=='Admin / Research'
