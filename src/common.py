"""
Shared page bootstrap: page config, theme, login gate, and the sidebar
account/status panel. Call bootstrap() as the first thing in every page.
"""
import streamlit as st

from src import auth, data, theme


def bootstrap(page_title: str, icon: str = "📈"):
    st.set_page_config(
        page_title=f"{page_title} · Global Security Analyser",
        page_icon=icon,
        layout="wide",
        initial_sidebar_state="expanded",
    )
    theme.inject_css()
    theme.apply_plotly_theme()
    auth.login_gate()

    with st.sidebar:
        st.markdown("### 🌍 Global Security Analyser")
        st.caption(f"Signed in as **{st.session_state.get('username', '?')}**")
        if st.button("Log out", width="stretch"):
            auth.logout()
            st.rerun()
        st.divider()
        status = data.cache_status()
        if status["count"]:
            st.caption(f"Cached series: {status['count']}")
            st.caption(f"Oldest: {status['oldest'].strftime('%Y-%m-%d %H:%M')}")
            st.caption(f"Newest: {status['newest'].strftime('%Y-%m-%d %H:%M')}")
        else:
            st.caption("No cached data yet — first load will fetch from Yahoo Finance.")
