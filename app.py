
import altair as alt
import pandas as pd
import streamlit as st

from src.ai.dashboard import DashboardContext, answer_dashboard_question
from src.analytics.financials import get_financial_history
from src.analytics.financial_summary import COMPANY_NAMES, format_usd


st.set_page_config(
    page_title="Financial Intelligence",
    page_icon="📊",
    layout="wide",
)


@st.cache_data(ttl=300)
def load_financial_history(ticker: str) -> list[dict]:
    return get_financial_history(ticker)


def render_analyst_answer(answer: str) -> None:
    """
    Render analyst responses with readable line breaks
    while preserving clickable SEC source links.
    """
    for paragraph in answer.split("\n\n"):
        st.markdown(paragraph.replace("\n", "  \n"))


# --- Dashboard ---

st.title("Financial Intelligence")
st.caption("SEC financial data · dbt Gold · AI-powered analytics")

ticker = st.selectbox(
    "Company",
    options=list(COMPANY_NAMES),
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

years = sorted(
    {record["fiscal_year"] for record in history},
    reverse=True,
)

fiscal_year = st.selectbox(
    "Fiscal year",
    options=years,
)

selected = next(
    record
    for record in history
    if record["fiscal_year"] == fiscal_year
)

st.subheader(f"{COMPANY_NAMES[ticker]} · FY{fiscal_year}")

revenue_col, growth_col = st.columns(2)

with revenue_col:
    st.metric(
        "Annual revenue",
        format_usd(selected["revenue_usd"]),
    )

with growth_col:
    growth = selected["yoy_growth_pct"]

    if selected["is_comparable"] is True and growth is not None:
        st.metric(
            "Year-over-year growth",
            f"{growth:+.2f}%",
        )
    else:
        st.metric(
            "Year-over-year growth",
            "N/A",
        )

st.caption(
    f"Reporting period: "
    f"{selected['period_start']} to {selected['period_end']}"
)

st.divider()

# --- Revenue History ---

st.subheader("Revenue history")

chart_data = pd.DataFrame(
    [
        {
            "Fiscal year": str(record["fiscal_year"]),
            "Revenue (USD billions)": (
                record["revenue_usd"] / 1_000_000_000
            ),
        }
        for record in history
    ]
)

chart = (
    alt.Chart(chart_data)
    .mark_line(point=True)
    .encode(
        x=alt.X(
            "Fiscal year:O",
            title="Fiscal year",
        ),
        y=alt.Y(
            "Revenue (USD billions):Q",
            title="Revenue (USD billions)",
            scale=alt.Scale(zero=False),
        ),
        tooltip=[
            alt.Tooltip(
                "Fiscal year:O",
                title="Fiscal year",
            ),
            alt.Tooltip(
                "Revenue (USD billions):Q",
                title="Revenue (USD billions)",
                format=",.3f",
            ),
        ],
    )
    .properties(height=350)
)

st.altair_chart(
    chart,
    use_container_width=True,
)

st.divider()

# --- SEC Source ---

st.subheader("SEC source")

st.write(f"**Concept:** {selected['source_concept']}")
st.write(f"**Accession:** {selected['source_accession']}")
st.write(f"**Filed:** {selected['source_filed_date']}")

st.caption(
    "Financial metrics are sourced from governed dbt Gold models. "
    "Year-over-year growth is not recalculated in the dashboard."
)

# --- AI Financial Analyst ---

st.divider()

st.subheader("AI Financial Analyst")

st.caption(
    "Ask questions about company financials and SEC filings. "
    "Answers use governed financial data and source-linked evidence."
)

if "messages" not in st.session_state:
    st.session_state.messages = []

# Render existing conversation history.
# Each user message retains its original dashboard context.
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        if message["role"] == "user" and message.get("context"):
            st.caption(message["context"])

        if message["role"] == "assistant":
            render_analyst_answer(message["content"])
        else:
            st.markdown(message["content"])

question = st.chat_input(
    "Ask about revenue, growth, or SEC risks..."
)

if question:
    # Capture the selection at the moment the question is asked.
    context = DashboardContext(
        ticker=ticker,
        fiscal_year=fiscal_year,
    )

    context_label = f"{ticker} · FY{fiscal_year}"

    st.session_state.messages.append(
        {
            "role": "user",
            "content": question,
            "context": context_label,
        }
    )

    with st.chat_message("user"):
        st.caption(context_label)
        st.markdown(question)

    with st.chat_message("assistant"):
        with st.spinner(
            "Analyzing financial data and SEC filings..."
        ):
            try:
                answer = answer_dashboard_question(
                    question,
                    context,
                )
            except Exception as exc:
                answer = (
                    "The analysis could not be completed. "
                    "Please try again."
                )
                print(
                    "[ERROR] AI analysis failed:",
                    type(exc).__name__,
                    str(exc),
                )

        render_analyst_answer(answer)

    st.session_state.messages.append(
        {
            "role": "assistant",
            "content": answer,
        }
    )
