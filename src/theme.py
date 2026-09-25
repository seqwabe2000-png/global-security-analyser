"""
Shared visual theme for the app: a Koyfin-inspired dark, data-dense look.
Provides a CSS injector for Streamlit and a matching Plotly template.
"""
import plotly.graph_objects as go
import plotly.io as pio
import streamlit as st

BG = "#0B0E14"
PANEL = "#131722"
PANEL_2 = "#1A1F2B"
BORDER = "#232838"
TEXT = "#E6E9EF"
MUTED = "#8B93A7"
ACCENT = "#00D3A7"
ACCENT_2 = "#3D8BFF"
UP = "#26A69A"
DOWN = "#EF5350"

CUSTOM_CSS = f"""
<style>
    .stApp {{ background-color: {BG}; }}
    section[data-testid="stSidebar"] {{
        background-color: {PANEL};
        border-right: 1px solid {BORDER};
    }}
    div[data-testid="stMetric"] {{
        background-color: {PANEL};
        border: 1px solid {BORDER};
        border-radius: 8px;
        padding: 10px 14px;
    }}
    div[data-testid="stMetricLabel"] {{ color: {MUTED}; }}
    .block-container {{ padding-top: 1.5rem; }}
    h1, h2, h3 {{ color: {TEXT}; font-weight: 600; }}
    .jse-card {{
        background-color: {PANEL};
        border: 1px solid {BORDER};
        border-radius: 10px;
        padding: 16px 18px;
        margin-bottom: 12px;
    }}
    .jse-pill {{
        display: inline-block;
        background-color: {PANEL_2};
        border: 1px solid {BORDER};
        border-radius: 999px;
        padding: 2px 10px;
        font-size: 0.78rem;
        color: {MUTED};
        margin-right: 6px;
    }}
    .jse-up {{ color: {UP}; font-weight: 600; }}
    .jse-down {{ color: {DOWN}; font-weight: 600; }}
    thead tr th {{ background-color: {PANEL_2} !important; }}
    .jse-percentile-table {{
        border-collapse: collapse;
        width: 100%;
        margin-bottom: 8px;
    }}
    .jse-percentile-table th, .jse-percentile-table td {{
        border: 1px solid {BORDER};
        padding: 4px 10px;
        text-align: center;
        font-size: 0.85rem;
        color: {TEXT};
    }}
    .jse-percentile-table thead th {{
        background-color: {PANEL_2} !important;
        font-weight: 700;
        font-size: 0.95rem;
        padding: 8px;
    }}
    .jse-percentile-table td.jse-pct-p {{ font-weight: 700; background-color: {PANEL}; }}
</style>
"""


def inject_css():
    st.markdown(CUSTOM_CSS, unsafe_allow_html=True)


def plotly_dark_template() -> go.layout.Template:
    template = pio.templates["plotly_dark"]
    template.layout.paper_bgcolor = PANEL
    template.layout.plot_bgcolor = PANEL
    template.layout.font = dict(color=TEXT, family="sans-serif", size=12)
    template.layout.xaxis.gridcolor = BORDER
    template.layout.yaxis.gridcolor = BORDER
    template.layout.xaxis.linecolor = BORDER
    template.layout.yaxis.linecolor = BORDER
    template.layout.legend = dict(bgcolor="rgba(0,0,0,0)")
    template.layout.margin = dict(l=40, r=20, t=40, b=30)
    return template


def apply_plotly_theme():
    pio.templates["jse_dark"] = plotly_dark_template()
    pio.templates.default = "jse_dark"
