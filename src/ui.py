"""
Small shared HTML-rendering helpers for Streamlit pages -- things that
don't fit neatly as a plain st.dataframe (custom multi-column grids etc).
"""
import math

import pandas as pd

from src.theme import BORDER, DOWN, MUTED, PANEL, TEXT, UP

# Self-contained styling for range_bar_html -- deliberately NOT added to
# theme.py's app-wide CUSTOM_CSS, so this component's look can be changed
# (or removed) without touching every other page's styling. It's bundled
# into each call's returned HTML; a duplicate <style> tag on a page with
# two range bars is harmless (browsers just apply it twice).
_RANGE_BAR_CSS = f"""
<style>
    .jse-range {{ margin: 4px 0 18px 0; }}
    .jse-range-header {{
        display: flex;
        justify-content: space-between;
        align-items: baseline;
        margin-bottom: 8px;
    }}
    .jse-range-val {{ font-size: 1.05rem; font-weight: 600; color: {TEXT}; }}
    .jse-range-title {{
        font-size: 0.75rem;
        letter-spacing: 0.04em;
        text-transform: uppercase;
        color: {MUTED};
    }}
    .jse-range-track {{
        position: relative;
        height: 6px;
        background: {BORDER};
        border-radius: 3px;
    }}
    .jse-range-fill {{
        position: absolute;
        top: 0;
        left: 0;
        height: 100%;
        border-radius: 3px;
    }}
    .jse-range-fill.jse-range-up {{ background: {UP}; }}
    .jse-range-fill.jse-range-down {{ background: {DOWN}; }}
    .jse-range-marker {{
        position: absolute;
        top: -5px;
        width: 16px;
        height: 16px;
        border-radius: 50%;
        background: {TEXT};
        border: 3px solid {PANEL};
        box-shadow: 0 0 0 1px {BORDER};
        transform: translateX(-50%);
    }}
</style>
"""


def range_bar_html(low, high, current, label: str, decimals: int = 2, value_prefix: str = "") -> str:
    """A horizontal 'day's range' / '52-week range' style bar (as seen on
    most broker/quote apps): a low..high track with a small round marker at
    the current price's position, coloured green if that position is in the
    upper half of the range and red if it's in the lower half -- a quick
    visual read of "close to the high" vs. "close to the low" that a plain
    low/high number pair doesn't give you.

    Fully self-contained: the returned HTML includes its own <style> block,
    so using this doesn't touch the app's shared theme/CSS anywhere else.

    Returns a "not enough data" placeholder instead of crashing if any of
    low/high/current is None or NaN, or if high <= low."""

    def _bad(v):
        return v is None or (isinstance(v, float) and math.isnan(v))

    if _bad(low) or _bad(high) or _bad(current) or high <= low:
        return (
            _RANGE_BAR_CSS
            + "<div class='jse-range'>"
            + f"<div class='jse-range-title'>{label}: not enough data</div>"
            + "</div>"
        )

    pct = max(0.0, min(100.0, (current - low) / (high - low) * 100))
    color_class = "jse-range-up" if pct >= 50 else "jse-range-down"
    low_str = f"{value_prefix}{low:,.{decimals}f}"
    high_str = f"{value_prefix}{high:,.{decimals}f}"

    return (
        _RANGE_BAR_CSS
        + "<div class='jse-range'>"
        + "<div class='jse-range-header'>"
        + f"<span class='jse-range-val'>{low_str}</span>"
        + f"<span class='jse-range-title'>{label}</span>"
        + f"<span class='jse-range-val'>{high_str}</span>"
        + "</div>"
        + "<div class='jse-range-track'>"
        + f"<div class='jse-range-fill {color_class}' style='width:{pct:.2f}%'></div>"
        + f"<div class='jse-range-marker' style='left:{pct:.2f}%'></div>"
        + "</div>"
        + "</div>"
    )


def percentile_grid_html(pct_table: pd.DataFrame, title: str = "Percentiles") -> str:
    """Render a 1st-99th percentile table as a compact 3-pair-column grid:
    1%-15% in steps of 1, 20%-80% in steps of 5, 85%-99% in steps of 1 --
    fine detail at the tails (where stop/target decisions actually live),
    coarser in the middle where it matters less. Matches the layout the
    user asked for, rather than a single long 99-row table or a dropdown.
    """
    lookup = dict(zip(pct_table["Percentile"], pct_table["Value"]))
    col_a = list(range(1, 16))
    col_b = list(range(20, 81, 5))
    col_c = list(range(85, 100))
    n = max(len(col_a), len(col_b), len(col_c))
    col_a += [None] * (n - len(col_a))
    col_b += [None] * (n - len(col_b))
    col_c += [None] * (n - len(col_c))

    row_html = []
    for a, b, c in zip(col_a, col_b, col_c):
        cells = []
        for p in (a, b, c):
            if p is None:
                cells.append("<td></td><td></td>")
            else:
                v = lookup.get(p)
                val_str = f"{v:.2%}" if v is not None and v == v else "—"
                cells.append(f"<td class='jse-pct-p'>{p}%</td><td class='jse-pct-v'>{val_str}</td>")
        row_html.append(f"<tr>{''.join(cells)}</tr>")

    return (
        "<table class='jse-percentile-table'>"
        f"<thead><tr><th colspan='6'>{title}</th></tr></thead>"
        f"<tbody>{''.join(row_html)}</tbody>"
        "</table>"
    )
