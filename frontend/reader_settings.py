"""Keep display preferences separate from ephemeral Streamlit widget state."""
import streamlit as st
from frontend import client as api

FIELDS = ("font_size", "line_height", "width", "dark")


def load():
    if "reader_preferences" not in st.session_state:
        st.session_state["reader_preferences"] = api.get("/reading/settings")
    preferences = st.session_state["reader_preferences"]
    for name in FIELDS:
        st.session_state["reader-setting-" + name] = preferences[name]
    return preferences


def save(full_key=None):
    preferences = dict(st.session_state["reader_preferences"])
    preferences.update({name: st.session_state["reader-setting-" + name] for name in FIELDS})
    if full_key:
        preferences["show_full_text"] = st.session_state[full_key]
    st.session_state["reader_preferences"] = preferences
    try:
        api.request("PUT", "/reading/settings", body=preferences)
        st.session_state.pop("reader_settings_error", None)
    except api.APIError as exc:
        st.session_state["reader_settings_error"] = str(exc)
