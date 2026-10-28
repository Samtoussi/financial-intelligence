import altair as alt
import pandas as pd
import streamlit as st

from src.ai.dashboard import DashboardContext, answer_dashboard_question
from src.analytics.financials import get_financial_history
from src.analytics.financial_summary import COMPANY_NAMES, format_usd
from src.ui.analyst import ANALYST_AVATAR, THINKING_ART, render_answer

BLUE = "#60A5FA"
POSITIVE = "#6BBF9A"
NEGATIVE = "#E18B8B"
NEUTRAL = "#94A3B8"


def comparable_growth(row: dict):
    return row["yoy_growth_pct"] if row["is_comparable"] is True else None


def revenue_change(history: list[dict], selected: dict):
    """Use the exact preceding fiscal year, never the preceding available row."""
    previous = next((row for row in history
                     if row["fiscal_year"] == selected["fiscal_year"] - 1), None)
    if selected["is_comparable"] is not True or previous is None:
        return None
    return selected["revenue_usd"] - previous["revenue_usd"]


def change_label(value, *, usd=False):
    if value is None:
        return "N/A"
    amount = format_usd(abs(value)) if usd else f"{abs(value):.2f}%"
    return f"{'↑ +' if value > 0 else '↓ −' if value < 0 else ''}{amount}"


def change_color(value):
    return POSITIVE if value is not None and value > 0 else (
        NEGATIVE if value is not None and value < 0 else NEUTRAL
    )


def change_card(label: str, value, *, usd=False):
    color = "green" if value is not None and value > 0 else (
        "red" if value is not None and value < 0 else "gray"
    )
    with st.container(border=True, gap="xsmall"):
        st.caption(label)
        st.markdown(f"### :{color}[{change_label(value, usd=usd)}]")


st.set_page_config(page_title="Financial Intelligence", page_icon="📊", layout="wide")


@st.cache_data(ttl=300)
def load_financial_history(ticker: str) -> list[dict]:
    return get_financial_history(ticker)


def toggle_analyst() -> None:
    st.session_state.analyst_open = not st.session_state.analyst_open


def render_analyst(ticker: str, fiscal_year: int) -> None:
    with st.container(border=True, gap="xsmall"):
        with st.container(horizontal=True, vertical_alignment="center"):
            st.markdown("#### AI Analyst")
            st.button("Close analyst", on_click=toggle_analyst, key="close_analyst")
        st.caption(f"{COMPANY_NAMES[ticker]} ({ticker}) · FY{fiscal_year} · SEC-grounded analysis")
        conversation = st.container(height=500, autoscroll=True, key="analyst_conversation")
        with conversation:
            if not st.session_state.messages:
                st.markdown("**What would you like to understand?**")
                st.caption("Ask about revenue, year-over-year growth, or risks disclosed in SEC filings.")
            for message in st.session_state.messages:
                avatar = ANALYST_AVATAR if message["role"] == "assistant" else ":material/person:"
                with st.chat_message(message["role"], avatar=avatar):
                    if message.get("context"):
                        st.caption(message["context"])
                    if message["role"] == "assistant":
                        render_answer(message["content"])
                    else:
                        st.markdown(message["content"])
        st.caption("Questions retain the company and year selected when sent.")
        question = st.chat_input("Ask about financials or SEC risks…", key="analyst_question")
        if question:
            context = DashboardContext(ticker=ticker, fiscal_year=fiscal_year)
            context_label = f"{ticker} · FY{fiscal_year}"
            st.session_state.messages.append(
                {"role": "user", "content": question, "context": context_label}
            )
            with conversation:
                with st.chat_message("user", avatar=":material/person:"):
                    st.caption(context_label)
                    st.markdown(question)
                with st.chat_message("assistant", avatar=ANALYST_AVATAR):
                    st.caption(context_label)
                    thinking = st.empty()
                    thinking.html(THINKING_ART)
                    succeeded = False
                    try:
                        answer = answer_dashboard_question(question, context)
                        succeeded = True
                    except Exception as exc:
                        answer = "The analysis could not be completed. Please try again."
                        print("[ERROR] AI analysis failed:", type(exc).__name__, str(exc))
                    finally:
                        thinking.empty()
                    # Store the completed governed answer before revealing it, so
                    # a rerun cannot lose it or replay its progressive rendering.
                    st.session_state.messages.append(
                        {"role": "assistant", "content": answer, "context": context_label}
                    )
                    render_answer(answer, progressive=succeeded)


def render_dashboard(ticker: str, history: list[dict], selected: dict) -> None:
    revenue_col, growth_col, change_col = st.columns(3, gap="small")
    with revenue_col:
        with st.container(border=True, gap="xsmall"):
            st.caption("Annual Revenue")
            st.markdown(f"### {format_usd(selected['revenue_usd'])}")
    with growth_col:
        change_card("Year-over-Year Growth", comparable_growth(selected))
    with change_col:
        change_card("Absolute Revenue Change (USD)", revenue_change(history, selected), usd=True)
    # Native columns stack below Streamlit's mobile breakpoint. With the analyst
    # open, use full-width charts so the narrower dashboard stays readable.
    if st.session_state.analyst_open:
        revenue_chart, growth_chart = st.container(), st.container()
    else:
        revenue_chart, growth_chart = st.columns(2, gap="small")
    with revenue_chart, st.container(border=True, gap="xsmall"):
        st.markdown("#### Revenue history")
        st.caption("USD billions · selected year highlighted")
        chart_data = pd.DataFrame([
            {"Fiscal year": str(row["fiscal_year"]),
             "Revenue (USD billions)": row["revenue_usd"] / 1_000_000_000,
             "Selected": row["fiscal_year"] == selected["fiscal_year"]}
            for row in history
        ])
        base = alt.Chart(chart_data).encode(
            x=alt.X("Fiscal year:O", title=None, sort="ascending", axis=alt.Axis(labelAngle=0, labelOverlap="greedy")),
            y=alt.Y("Revenue (USD billions):Q", title="USD billions", scale=alt.Scale(zero=False)),
            tooltip=[alt.Tooltip("Fiscal year:O"), alt.Tooltip("Revenue (USD billions):Q", format=",.3f")],
        )
        chart = (
            base.mark_line(color="#60A5FA", strokeWidth=3, point=True)
            + base.transform_filter(alt.datum.Selected).mark_point(
                color=BLUE, size=140, filled=True
            )
        ).properties(height=200).configure_view(strokeWidth=0).configure_axis(
            gridColor="#253449", domainColor="#334155", labelColor="#CBD5E1",
            titleColor="#94A3B8", labelPadding=8, titlePadding=12,
        )
        st.altair_chart(chart, width="stretch")
    growth_data = pd.DataFrame([
        {"Fiscal year": str(row["fiscal_year"]), "Growth": comparable_growth(row),
         "Change": change_label(comparable_growth(row)),
         "Color": change_color(comparable_growth(row))}
        for row in sorted(history, key=lambda row: row["fiscal_year"])
    ])
    with growth_chart, st.container(border=True, gap="xsmall"):
        st.markdown("#### YoY growth history")
        st.caption("↑ increase · ↓ decrease · N/A unavailable")
        base = alt.Chart(growth_data).encode(
            x=alt.X("Fiscal year:O", title=None, sort="ascending", axis=alt.Axis(labelAngle=0, labelOverlap="greedy")),
            tooltip=["Fiscal year:O", "Change:N"],
        )
        bars = base.mark_bar().encode(
            y=alt.Y("Growth:Q", title="Growth (%)"),
            color=alt.Color("Color:N", scale=None, legend=None),
        )
        missing = base.transform_filter("!isValid(datum.Growth)").mark_text(
            text="N/A", color=NEUTRAL, dy=-10,
        ).encode(y=alt.datum(0))
        unchanged = base.transform_filter("datum.Growth === 0").mark_point(
            color=NEUTRAL, filled=True, size=40,
        ).encode(y=alt.Y("Growth:Q"))
        zero = alt.Chart(pd.DataFrame({"zero": [0]})).mark_rule(color=NEUTRAL).encode(y="zero:Q")
        st.altair_chart((bars + zero + unchanged + missing).properties(height=200).configure_view(
            strokeWidth=0
        ).configure_axis(gridColor="#253449", labelColor="#CBD5E1", titleColor=NEUTRAL), width="stretch")
    with st.container(horizontal=True, vertical_alignment="center", gap="small"):
        st.markdown("#### Financial history")
        full_history = st.toggle("Show full history", key="full_history")
    rows = sorted(history, key=lambda row: row["fiscal_year"], reverse=True)
    table = pd.DataFrame([
        {"Fiscal year": str(row["fiscal_year"]), "Revenue (USD)": format_usd(row["revenue_usd"]),
         "YoY growth": change_label(comparable_growth(row)),
         "Comparability": "Comparable" if row["is_comparable"] is True else "Non-comparable / unavailable"}
        for row in rows
    ])
    colors = {change_label(comparable_growth(row)): change_color(comparable_growth(row)) for row in rows}
    visible_table = table if full_history else table.head(5)
    st.dataframe(visible_table.style.map(lambda value: f"color: {colors[value]}", subset=["YoY growth"]),
                 hide_index=True, width="stretch", height=212, row_height=30)
    with st.expander("SEC Source & Provenance", expanded=False):
        st.caption(f"Filed {selected['source_filed_date']} · Accession {selected['source_accession']}")
        st.markdown("**Reported concept**")
        st.code(selected["source_concept"], language=None, wrap_lines=True)
        st.link_button(
            "Open SEC filing",
            f"https://www.sec.gov/Archives/edgar/data/{int(selected['cik'])}/"
            f"{selected['source_accession'].replace('-', '')}/"
            f"{selected['source_accession']}-index.html",
        )
        st.caption("Source: SEC CompanyFacts → dbt Gold. Revenue and growth use governed model values; growth is not recalculated here.")


st.session_state.setdefault("messages", [])
st.session_state.setdefault("analyst_open", False)

with st.container(horizontal=True, vertical_alignment="bottom", gap="small"):
    with st.container(width=350, gap="xsmall"):
        st.markdown("### Financial Intelligence")
        st.caption("SEC financial data · dbt Gold · AI analysis")
    ticker = st.selectbox(
        "Company", options=list(COMPANY_NAMES), width=280,
        format_func=lambda value: f"{COMPANY_NAMES[value]} ({value})",
    )
    try:
        history = load_financial_history(ticker)
    except (FileNotFoundError, RuntimeError) as exc:
        st.error(f"Could not load financial data: {exc}")
        st.stop()
    if not history:
        st.warning("No financial data is available for this company.")
        st.stop()
    years = sorted({row["fiscal_year"] for row in history}, reverse=True)
    fiscal_year = st.selectbox("Fiscal year", options=years, width=160)
    st.button(
        "Ask AI Analyst", icon=":material/auto_awesome:", type="secondary", on_click=toggle_analyst,
        help="Open or close the analyst workspace. Your conversation is retained.",
    )

selected = next(row for row in history if row["fiscal_year"] == fiscal_year)
st.caption(f"**{COMPANY_NAMES[ticker]} · FY{selected['fiscal_year']}** · Reporting period: {selected['period_start']} to {selected['period_end']}")
if st.session_state.analyst_open:
    dashboard, analyst = st.columns([1.65, 1], gap="large")
    with dashboard, st.container(gap="xsmall"):
        render_dashboard(ticker, history, selected)
    with analyst:
        render_analyst(ticker, fiscal_year)
else:
    with st.container(gap="xsmall"):
        render_dashboard(ticker, history, selected)
