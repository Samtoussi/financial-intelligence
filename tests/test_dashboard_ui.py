"""UI regression checks; fixtures are test-only, never dashboard fallback data."""
from unittest.mock import patch

import pandas as pd
import pyarrow as pa
import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest


@pytest.fixture
def dashboard(request):
    rows = [
        dict(cik=789019, fiscal_year=year, revenue_usd=revenue,
             yoy_growth_pct=growth, is_comparable=comparable,
             period_start=f"{year - 1}-07-01", period_end=f"{year}-06-30",
             source_concept="RevenueFromContractWithCustomerExcludingAssessedTax",
             source_accession="0000789019-25-000100", source_filed_date="2025-07-30")
        for year, revenue, growth, comparable in [
            (2024, 100_000_000_000, None, False),
            (2025, 110_000_000_000, 10.0, True),
        ]
    ]
    if getattr(request, "param", None) == "long_history":
        rows = [dict(rows[-1], fiscal_year=year) for year in range(2016, 2026)]
    elif hasattr(request, "param"):
        growth, comparable, previous_year = request.param
        rows[-1].update(yoy_growth_pct=growth, is_comparable=comparable)
        if previous_year is None:
            rows = rows[1:]
        else:
            rows[0]["fiscal_year"] = previous_year
        if growth == 0:
            rows[-1]["revenue_usd"] = 100_000_000_000
        elif growth is not None and growth < 0:
            rows[-1]["revenue_usd"] = 90_000_000_000
    st.cache_data.clear()
    with patch("src.analytics.financials.get_financial_history", return_value=rows):
        app = AppTest.from_file("../app.py", default_timeout=15).run()
        yield app


def test_selection_and_noncomparable_growth(dashboard):
    assert not dashboard.exception
    assert any(":green[↑ +10.00%]" in m.value for m in dashboard.markdown)
    assert any(":green[↑ +$10.000B]" in m.value for m in dashboard.markdown)
    dashboard.selectbox[1].select(2024).run()
    assert not dashboard.exception
    assert sum(":gray[N/A]" in m.value for m in dashboard.markdown) == 2


@pytest.mark.parametrize("dashboard, expected_growth, expected_change", [
    ((-10.0, True, 2024), ":red[↓ −10.00%]", ":red[↓ −$10.000B]"),
    ((0.0, True, 2024), ":gray[0.00%]", ":gray[$0.000B]"),
    ((10.0, False, 2024), ":gray[N/A]", ":gray[N/A]"),
    ((10.0, True, 2023), ":green[↑ +10.00%]", ":gray[N/A]"),
    ((10.0, True, None), ":green[↑ +10.00%]", ":gray[N/A]"),
    ((None, True, 2024), ":gray[N/A]", ":green[↑ +$10.000B]"),
], indirect=["dashboard"])
def test_change_semantics(dashboard, expected_growth, expected_change):
    assert not dashboard.exception
    values = [m.value for m in dashboard.markdown]
    assert any(expected_growth in value for value in values)
    assert any(expected_change in value for value in values)
    history = dashboard.dataframe[0].value
    growth = history.iloc[0]["YoY growth"]
    assert growth in expected_growth
    charts = dashboard.get("vega_lite_chart")
    assert len(charts) == 2
    datasets = [pa.ipc.open_stream(dataset.data.data).read_all().to_pandas()
                for dataset in charts[1].proto.datasets]
    chart_data = next(data for data in datasets if "Growth" in data.columns)
    selected_growth = chart_data.loc[chart_data["Fiscal year"] == "2025"].iloc[0]
    assert selected_growth["Change"] == growth
    if growth == "N/A":
        assert pd.isna(selected_growth["Growth"])
        assert selected_growth["Color"] == "#94A3B8"
    else:
        expected_color = "#6BBF9A" if "↑" in growth else "#E18B8B" if "↓" in growth else "#94A3B8"
        assert selected_growth["Color"] == expected_color


def test_panel_retains_conversation_and_original_context(dashboard):
    dashboard.button[0].click().run()
    with patch("src.ai.dashboard.answer_dashboard_question", return_value="See [SEC](https://www.sec.gov/).") as answer:
        dashboard.chat_input[0].set_value("Explain revenue").run()
    assert not dashboard.exception
    assert answer.call_args.args[1].ticker == "MSFT"
    assert answer.call_args.args[1].fiscal_year == 2025
    dashboard.selectbox[0].select("CAT").run()
    dashboard.selectbox[1].select(2024).run()
    assert dashboard.session_state.messages[0]["context"] == "MSFT · FY2025"
    dashboard.button[1].click().run()
    assert len(dashboard.chat_input) == 0
    dashboard.button[0].click().run()
    assert len(dashboard.chat_message) == 2
    assert "https://www.sec.gov/" in dashboard.session_state.messages[1]["content"]


def test_analysis_error_is_displayed_and_retained(dashboard):
    dashboard.button[0].click().run()
    with patch("src.ai.dashboard.answer_dashboard_question", side_effect=RuntimeError("Unavailable")):
        dashboard.chat_input[0].set_value("Explain risks").run()
    assert not dashboard.exception
    assert "Please try again" in dashboard.session_state.messages[-1]["content"]


@pytest.mark.parametrize("dashboard", ["long_history"], indirect=True)
def test_recent_history_and_full_history_access(dashboard):
    assert not dashboard.exception
    assert dashboard.dataframe[0].value["Fiscal year"].tolist() == [
        "2025", "2024", "2023", "2022", "2021",
    ]
    assert not dashboard.expander[0].proto.expanded
    dashboard.toggle[0].set_value(True).run()
    assert not dashboard.exception
    assert len(dashboard.dataframe[0].value) == 10
    assert dashboard.dataframe[0].value.iloc[-1]["Fiscal year"] == "2016"
    dashboard.button[0].click().run()
    assert not dashboard.exception
    assert len(dashboard.dataframe[0].value) == 10
    assert len(dashboard.get("vega_lite_chart")) == 2
    dashboard.toggle[0].set_value(False).run()
    assert len(dashboard.dataframe[0].value) == 5


def test_long_answer_keeps_input_outside_conversation(dashboard):
    dashboard.button[0].click().run()
    answer = "Financial analysis paragraph.\n\n" * 100 + "[SEC](https://www.sec.gov/)"
    with patch("src.ai.dashboard.answer_dashboard_question", return_value=answer):
        dashboard.chat_input[0].set_value("Explain revenue").run()
    assert not dashboard.exception
    assert dashboard.session_state.messages[-1]["content"] == answer
    assert len(dashboard.chat_input) == 1
    conversation = next(element for element in dashboard.get("flex_container")
                        if element.proto.id.endswith("-analyst_conversation"))
    assert not conversation.get("chat_input")
    assert len(conversation.get("chat_message")) == 2


def test_only_new_answers_reveal_progressively_and_use_custom_avatar(dashboard):
    dashboard.button[0].click().run()
    answer = "SEC risk analysis\n\nMSFT\n\n1. Competition may affect demand.\nChunk: chunk-1\nSource: https://www.sec.gov/filing.htm"
    with patch("src.ai.dashboard.answer_dashboard_question", return_value=answer):
        with patch("src.ui.analyst.pause") as sleep:
            dashboard.chat_input[0].set_value("How could risks affect growth?").run()
        assert sleep.call_count > 1
    assert not dashboard.exception
    assert dashboard.session_state.messages[-1]["content"] == answer
    assert any(answer == code.value for code in dashboard.code)
    assert dashboard.chat_message[1].proto.avatar_type != dashboard.chat_message[0].proto.avatar_type
    with patch("src.ui.analyst.pause") as sleep:
        dashboard.selectbox[1].select(2024).run()
        sleep.assert_not_called()
    assert not dashboard.exception
    assert dashboard.session_state.messages[-1]["context"] == "MSFT · FY2025"
    assert not any(element.type == "html" and "Analyzing" in element.proto.body
                   for element in dashboard)
