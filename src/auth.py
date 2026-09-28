"""
Minimal single/multi-user login for the Streamlit app.

Two ways credentials can be supplied, checked in this order:

1. Streamlit secrets -- a `[credentials]` table (username = sha256(password))
   configured through the hosting dashboard when this app is deployed to
   Streamlit Community Cloud (or any host that supports st.secrets). This is
   the only option that makes sense once the app is running somewhere you
   can't just edit a local file -- see scripts/hash_password.py to generate
   the hash to paste in. Secrets are never read from or written to disk by
   this app.
2. config/credentials.yaml as {username: sha256(password)} -- used when
   running locally (e.g. from your USB drive) and no secrets are configured.
   On first local run, if that file doesn't exist, a default account
   (admin / jse2026) is created automatically so the app is usable
   immediately -- change it with `python3 scripts/set_password.py`.

Either way, this is a convenience login gate, not a hardened auth system.
"""
import hashlib
import os

import streamlit as st
import yaml

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_DIR = os.path.join(BASE, "config")
CREDENTIALS_PATH = os.path.join(CONFIG_DIR, "credentials.yaml")

DEFAULT_USERNAME = "admin"
DEFAULT_PASSWORD = "jse2026"


def _hash(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def _cloud_credentials():
    """Returns the {username: hash} dict from st.secrets["credentials"], or
    None if no such secret is configured (e.g. running locally)."""
    try:
        if "credentials" in st.secrets:
            return dict(st.secrets["credentials"])
    except Exception:
        pass
    return None


def _ensure_default_credentials():
    os.makedirs(CONFIG_DIR, exist_ok=True)
    if not os.path.exists(CREDENTIALS_PATH):
        with open(CREDENTIALS_PATH, "w") as f:
            yaml.safe_dump({DEFAULT_USERNAME: _hash(DEFAULT_PASSWORD)}, f)


def _load_credentials() -> dict:
    cloud_creds = _cloud_credentials()
    if cloud_creds is not None:
        return cloud_creds
    _ensure_default_credentials()
    with open(CREDENTIALS_PATH) as f:
        return yaml.safe_load(f) or {}


def is_authenticated() -> bool:
    return bool(st.session_state.get("authenticated"))


def logout():
    st.session_state["authenticated"] = False
    st.session_state.pop("username", None)


def login_gate():
    """Call at the top of app.py. Renders a login form and stops execution
    until the user is authenticated."""
    if is_authenticated():
        return

    creds = _load_credentials()
    is_cloud = _cloud_credentials() is not None
    is_default = (not is_cloud) and creds == {DEFAULT_USERNAME: _hash(DEFAULT_PASSWORD)}

    st.markdown(
        "<h1 style='text-align:center; margin-top: 8vh;'>Global Security Analyser</h1>",
        unsafe_allow_html=True,
    )
    col1, col2, col3 = st.columns([1, 1, 1])
    with col2:
        with st.form("login_form"):
            st.subheader("Sign in")
            username = st.text_input("Username")
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Log in", width="stretch")
        if is_default:
            st.caption(
                f"Default login: `{DEFAULT_USERNAME}` / `{DEFAULT_PASSWORD}` -- "
                "run `python3 scripts/set_password.py` to change it."
            )
        if submitted:
            if username in creds and creds[username] == _hash(password):
                st.session_state["authenticated"] = True
                st.session_state["username"] = username
                st.rerun()
            else:
                st.error("Incorrect username or password.")
    st.stop()
