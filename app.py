"""Dark Pool Scanner - local web dashboard (Streamlit).

    uv run streamlit run app.py

Two views:
  Scanner  - heaviest off-exchange (ATS) volume by symbol, for a chosen week
  Analysis - one symbol's participation-rate history, the reversal/follow-through
             test, and a prediction for the current week (see dark_pool/analysis.py)
"""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from dark_pool.analysis import MIN_ROWS_FOR_TEST, participation_series, predict_this_week, reversal_test
from dark_pool.scanner import available_weeks, top_symbols

# Same reference palette used across the NOI tool and market-charts, for a
# consistent look across all three projects.
UP, DOWN, BLUE, NEUTRAL = "#0ca30c", "#d03b3b", "#2a78d6", "#898781"
INK, INK_2, GRID, SURFACE = "#0b0b0b", "#52514e", "#e8e7e3", "#fcfcfb"

st.set_page_config(page_title="Dark Pool Scanner", layout="wide")

PLOTLY_LAYOUT = dict(
    paper_bgcolor=SURFACE, plot_bgcolor=SURFACE,
    font=dict(color=INK_2), xaxis=dict(gridcolor=GRID, zerolinecolor=GRID),
    yaxis=dict(gridcolor=GRID, zerolinecolor=GRID), margin=dict(t=40, l=10, r=10, b=10),
)

st.title("Dark Pool Scanner")
st.caption("Free tier: FINRA weekly off-exchange (ATS) data, 2-4 week lag. "
           "Switches to Massive's live trades feed once that subscription is active.")

tab_scanner, tab_analysis = st.tabs(["Scanner", "Analysis"])

# ---------------------------------------------------------------------------
with tab_scanner:
    weeks = available_weeks()
    if not weeks:
        st.warning("No data pulled yet. Run: `uv run python -m dark_pool.finra.collect --all`")
    else:
        col1, col2 = st.columns([2, 1])
        week = col1.selectbox("Week", options=list(reversed(weeks)), index=0)
        top_n = col2.slider("Top N", 5, 50, 20)

        result = top_symbols(week, top_n)
        if result.empty:
            st.info("No ATS rows for this week.")
        else:
            fig = go.Figure(go.Bar(
                x=result["ats_shares"][::-1], y=result["symbol"][::-1], orientation="h",
                marker_color=BLUE, hovertemplate="%{y}: %{x:,.0f} shares<extra></extra>",
            ))
            fig.update_layout(**PLOTLY_LAYOUT, title=f"Heaviest off-exchange volume - week of {week}",
                               height=max(320, 28 * len(result)))
            st.plotly_chart(fig, use_container_width=True)
            st.dataframe(result, use_container_width=True, hide_index=True)

# ---------------------------------------------------------------------------
with tab_analysis:
    symbol = st.text_input("Symbol (S&P 500 only - needs price/volume reference data)", value="JPM").upper().strip()

    if symbol:
        try:
            series = participation_series(symbol)
        except SystemExit as e:
            st.error(str(e))
            series = None

        if series is not None and not series.empty:
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=series["week"], y=series["participation_pct"], mode="lines+markers",
                                      line=dict(color=BLUE), name="Participation %"))
            fig.update_layout(**PLOTLY_LAYOUT, title=f"{symbol} - off-exchange share of weekly volume",
                               yaxis_title="% of volume")
            st.plotly_chart(fig, use_container_width=True)

            weeks_with_z = series.dropna(subset=["z_score"])
            st.caption(f"{len(weeks_with_z)} weeks with a z-score computed "
                       f"(needs {MIN_ROWS_FOR_TEST} with a known next-week outcome for a reliable test).")

            st.subheader("This week's prediction")
            pred = predict_this_week(symbol)
            if pred:
                reliable = pred["reliable"]
                badge = "✅ statistically reliable (|t| ≥ 2)" if reliable else "⚠️ not yet reliable (|t| < 2) - treat as exploratory"
                c1, c2, c3 = st.columns(3)
                c1.metric("Participation this week", f"{pred['participation_pct']}%", f"z={pred['z_score']}")
                c2.metric("Predicted return", f"{pred['predicted_return_pct']:+.2f}%")
                c3.metric("Predicted price", f"${pred['predicted_price']}", f"from ${pred['last_close']}")
                st.caption(f"Fit on {pred['n_weeks_fit']} weeks · beta={pred['beta']} · t-stat={pred['t_stat']} · {badge}")
            else:
                st.info("Not enough historical weeks with a known outcome yet - see console/log for the exact count.")

            st.subheader("Reversal / follow-through test (full detail)")
            with st.expander("Show test output"):
                import io, contextlib
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    reversal_test(symbol)
                st.text(buf.getvalue())
