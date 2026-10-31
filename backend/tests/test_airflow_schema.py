"""airflow DAG가 SQL로 직접 읽고 쓰는 RDB 컬럼이 backend 모델에 있는지 — 모델 컬럼을 바꾸면 DAG SQL도 함께 고치게 한다.

목록은 airflow/dags의 SQL(INSERT·SELECT·UPDATE)에서 옮겼다. market_calendar·kis_tokens는 모델 없이
docker/db/init/02_schema.sql에만 있는 테이블이라 여기서 보지 않는다.
"""
import pytest

import app.models  # noqa: F401  모든 모델을 Base.metadata에 올린다
from app.database import Base

AIRFLOW_COLUMNS = {
    # rdb.record_collection_run
    "collection_runs": {"collected_at"},
    # ai_config.load_ai_config
    "ai_settings": {"id", "llm_api_base", "llm_api_key", "llm_model",
                    "embedding_api_base", "embedding_api_key", "embedding_model"},
    # discord_notice
    "discord_settings": {"id", "enabled", "webhook_url", "threshold", "added_threshold", "rise_threshold"},
    "discord_notification_logs": {"id", "kind", "base_date", "status", "threshold", "items", "message_count",
                                  "error", "sent_at"},
    # weight_change_calc, discord_notice
    "weight_changes": {"base_date", "prev_date", "etf_code", "etf_name", "stock_code", "stock_name",
                       "change_type", "previous_weight", "current_weight", "weight_change"},
    "weight_change_dates": {"base_date", "computed_at"},
    # dart_sync
    "dart_settings": {"id", "api_key"},
    "dart_corps": {"corp_code", "corp_name", "stock_code", "modify_date"},
    "stock_disclosures": {"rcept_no", "stock_code", "corp_code", "report_nm", "rcept_dt", "flr_nm", "rm"},
    "stock_financials": {"stock_code", "bsns_year", "reprt_code", "fs_div", "account", "amount", "amount_cum",
                         "rcept_no", "fetched_at"},
    # report_index
    "stock_reports": {"rcept_no", "stock_code", "report_nm", "period", "status", "created_at", "parser_version",
                      "indexed_at", "summarized_at", "error", "overview", "model"},
    "stock_report_docs": {"rcept_no", "zip", "fetched_at"},
    "report_nodes": {"rcept_no", "node_id", "parent_id", "seq", "level", "title", "path", "chars", "blocks",
                     "content_hash", "summary", "summary_model"},
    # chat_reviewer
    "chat_logs": {"id", "session_id", "question", "refined_question", "answer", "result", "status", "layout",
                  "steps", "created_at"},
    "chat_slots": {"chat_log_id", "slot_id", "skill", "status", "message", "summary"},
    # weekly_opinion DAG
    "opinion_runs": {"run_on", "status"},
    # embed_code_examples DAG
    "code_examples": {"id", "question", "question_generalized", "status", "embedding"},
    "layout_examples": {"id", "question", "question_generalized", "status", "embedding"},
    # realtime_prices_rdb DAG
    "ticker_prices": {"ticker", "date", "price", "updated_at"},
    "holdings": {"portfolio_id", "ticker", "quantity"},
    "portfolios": {"id", "snapshot_enabled"},
    "portfolio_snapshots": {"portfolio_id", "date", "total_value", "prev_value", "change_amount", "change_rate",
                            "created_at", "updated_at"},
    # sync_metadata_rdb DAG
    "etfs": {"code", "name", "updated_at"},
}


@pytest.mark.parametrize("table", sorted(AIRFLOW_COLUMNS))
def test_airflow_sql_columns_exist_in_models(table):
    assert table in Base.metadata.tables, f"모델에 {table} 테이블이 없습니다"
    missing = AIRFLOW_COLUMNS[table] - set(Base.metadata.tables[table].columns.keys())
    assert not missing, f"{table}에 없는 컬럼: {sorted(missing)}"
