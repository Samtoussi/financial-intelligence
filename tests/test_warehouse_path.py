"""Local warehouse selection across ingestion, analytics and AI financial tools."""
import json
from datetime import datetime, timezone

import duckdb
import pytest

import run_pipeline
from src import warehouse
from src.ai.analyst import execute_tool
from src.analytics import financials
from src.transformation import load_companyfacts as loader


def test_default_path_is_stable_outside_repository(tmp_path, monkeypatch):
    monkeypatch.delenv('FI_DUCKDB_PATH', raising=False)
    monkeypatch.chdir(tmp_path)
    assert warehouse.get_duckdb_path() == warehouse.ROOT / 'data/warehouse/financial_intelligence.duckdb'


def test_relative_override_uses_current_working_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv('FI_DUCKDB_PATH', 'isolated/warehouse.duckdb')
    assert warehouse.get_duckdb_path() == tmp_path / 'isolated/warehouse.duckdb'


@pytest.fixture
def warehouses(tmp_path, monkeypatch):
    monkeypatch.setattr(loader, 'PARQUET_DIR', tmp_path / 'parquet')
    paths = []
    for index, value in enumerate((100_000_000_000, 200_000_000_000)):
        path = tmp_path / f'warehouse-{index}.duckdb'
        monkeypatch.setenv('FI_DUCKDB_PATH', str(path))
        snapshot_id = f'snapshot-{index}'
        rows = loader.normalize({'cik': 789019, 'facts': {'us-gaap': {'Revenues': {'units': {'USD': [{
            'val': value, 'start': '2023-07-01', 'end': '2024-06-30',
            'accn': 'test-filing', 'filed': '2024-07-30', 'form': '10-K', 'fy': 2024, 'fp': 'FY',
        }]}}}}}, snapshot_id)
        parquet = loader.write_parquet(rows, 'MSFT', snapshot_id)
        assert loader.load_duckdb(parquet, snapshot_id, 1, 789019, datetime.now(timezone.utc)) == 1
        assert run_pipeline.get_active_snapshot(789019) == snapshot_id
        # Materialize the actual Gold SQL locally; no dbt subprocess or network.
        with duckdb.connect(str(path)) as con:
            con.execute('CREATE SCHEMA main_gold')
            for model in ('annual_revenue', 'annual_revenue_growth'):
                sql = (warehouse.ROOT / f'dbt/models/gold/{model}.sql').read_text()
                sql = sql.replace("{{ ref('annual_revenue') }}", 'main_gold.annual_revenue')
                con.execute(f'CREATE TABLE main_gold.{model} AS {sql}')
        paths.append(path)
    return paths


def test_runtime_changes_reach_pipeline_analytics_and_ai(warehouses, monkeypatch):
    for index in (0, 1, 0):
        monkeypatch.setenv('FI_DUCKDB_PATH', str(warehouses[index]))
        assert run_pipeline.get_active_snapshot(789019) == f'snapshot-{index}'
        annual = financials.get_annual_financials('MSFT', 2024)
        assert annual['revenue_usd'] == (index + 1) * 100_000_000_000
        assert financials.get_financial_history('MSFT') == [annual]
        assert execute_tool('get_annual_financials', json.dumps({'ticker': 'MSFT', 'fiscal_year': 2024})) == annual


def test_missing_override_never_falls_back_or_creates_database(tmp_path, monkeypatch):
    path = tmp_path / 'missing.duckdb'
    monkeypatch.setenv('FI_DUCKDB_PATH', str(path))
    with pytest.raises(FileNotFoundError, match='missing.duckdb'):
        financials.get_annual_financials('MSFT', 2024)
    assert run_pipeline.get_active_snapshot(789019) is None
    assert not path.exists()


def test_dashboard_cache_changes_with_warehouse(warehouses, monkeypatch):
    import streamlit as st
    from streamlit.testing.v1 import AppTest

    st.cache_data.clear()
    try:
        monkeypatch.setenv('FI_DUCKDB_PATH', str(warehouses[0]))
        app = AppTest.from_file(str(warehouse.ROOT / 'app.py'), default_timeout=20)
        app.session_state['main_view'] = 'Dashboard'
        app.run()
        assert not app.exception
        assert any('$100.000B' in item.value for item in app.markdown)
        monkeypatch.setenv('FI_DUCKDB_PATH', str(warehouses[1]))
        app.run()
        assert not app.exception
        assert any('$200.000B' in item.value for item in app.markdown)
        assert not any('$100.000B' in item.value for item in app.markdown)
    finally:
        st.cache_data.clear()
