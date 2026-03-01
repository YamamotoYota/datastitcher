# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Yamamoto Yota

"""Generic SQL database access helpers via SQLAlchemy."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote_plus

import pandas as pd

SQLSERVER_ODBC_DRIVER_CANDIDATES: tuple[str, ...] = (
    "ODBC Driver 18 for SQL Server",
    "ODBC Driver 17 for SQL Server",
)

SUPPORTED_DBMS: tuple[str, ...] = ("sqlserver", "mysql", "sqlite", "oracle", "postgresql")


class DatabaseError(RuntimeError):
    """Raised when DB connection or query execution fails."""


@dataclass(frozen=True)
class DatabaseConfig:
    """Generic connection settings for supported DBMS."""

    dbms: str
    host: str = ""
    port: int | None = None
    database: str = ""
    username: str = ""
    password: str = ""
    sqlite_path: str = ""
    schema: str = ""


def dbms_label(dbms: str) -> str:
    """Return display label for DBMS key."""
    labels = {
        "sqlserver": "SQL Server",
        "mysql": "MySQL",
        "sqlite": "SQLite",
        "oracle": "Oracle Database",
        "postgresql": "PostgreSQL",
    }
    return labels.get(dbms, dbms)


def build_sql_connection_options() -> list[dict[str, str]]:
    """Return dropdown options for supported DBMS."""
    return [{"label": dbms_label(key), "value": key} for key in SUPPORTED_DBMS]


def normalize_dbms(value: str | None) -> str:
    """Normalize dbms key."""
    key = str(value or "sqlserver").strip().lower()
    return key if key in SUPPORTED_DBMS else "sqlserver"


def normalize_port(value: int | float | str | None) -> int | None:
    """Normalize optional port number."""
    if value in (None, ""):
        return None
    try:
        port = int(value)
    except (TypeError, ValueError):
        return None
    return port if port > 0 else None


def validate_config(config: DatabaseConfig) -> None:
    """Validate required fields by DBMS."""
    dbms = normalize_dbms(config.dbms)
    if dbms == "sqlite":
        if not str(config.sqlite_path or "").strip():
            raise DatabaseError("SQLite を選択した場合はDBファイルパスを入力してください。")
        return

    if not str(config.host or "").strip():
        raise DatabaseError("ホスト名/サーバー名を入力してください。")
    if not str(config.database or "").strip():
        raise DatabaseError("データベース名（Oracleはサービス名）を入力してください。")
    if dbms in {"mysql", "oracle", "postgresql", "sqlserver"}:
        if not str(config.username or "").strip():
            raise DatabaseError("ユーザー名を入力してください。")
        if not str(config.password or ""):
            raise DatabaseError("パスワードを入力してください。")


def _sqlalchemy_imports():
    """Import SQLAlchemy runtime dependencies lazily."""
    try:
        from sqlalchemy import create_engine, inspect, text
    except ImportError as exc:  # pragma: no cover
        raise DatabaseError("DB接続には sqlalchemy が必要です。") from exc
    return create_engine, inspect, text


def _build_sqlserver_url(config: DatabaseConfig, driver: str) -> str:
    """Create SQLAlchemy URL for SQL Server via pyodbc."""
    port_fragment = f",{config.port}" if config.port else ""
    odbc_connect = (
        f"DRIVER={{{driver}}};"
        f"SERVER={config.host}{port_fragment};"
        f"DATABASE={config.database};"
        f"UID={config.username};"
        f"PWD={config.password};"
        "TrustServerCertificate=yes;"
    )
    return f"mssql+pyodbc:///?odbc_connect={quote_plus(odbc_connect)}"


def _build_url_and_ping_query(config: DatabaseConfig) -> tuple[str, str]:
    """Build SQLAlchemy URL and ping query string."""
    dbms = normalize_dbms(config.dbms)
    if dbms == "sqlserver":
        # Driver fallback is handled separately.
        return "", "SELECT 1"
    if dbms == "mysql":
        port = config.port or 3306
        try:
            import pymysql  # noqa: F401
        except ImportError as exc:
            raise DatabaseError("MySQL接続には `pymysql` が必要です。") from exc
        return (
            f"mysql+pymysql://{quote_plus(config.username)}:{quote_plus(config.password)}@"
            f"{config.host}:{port}/{config.database}",
            "SELECT 1",
        )
    if dbms == "sqlite":
        file_path = Path(str(config.sqlite_path)).expanduser()
        return f"sqlite:///{file_path}", "SELECT 1"
    if dbms == "oracle":
        port = config.port or 1521
        try:
            import oracledb  # noqa: F401
        except ImportError as exc:
            raise DatabaseError("Oracle接続には `oracledb` が必要です。") from exc
        return (
            f"oracle+oracledb://{quote_plus(config.username)}:{quote_plus(config.password)}@"
            f"{config.host}:{port}/?service_name={quote_plus(config.database)}",
            "SELECT 1 FROM DUAL",
        )
    if dbms == "postgresql":
        port = config.port or 5432
        try:
            import psycopg2  # noqa: F401
        except ImportError as exc:
            raise DatabaseError("PostgreSQL接続には `psycopg2-binary` が必要です。") from exc
        return (
            f"postgresql+psycopg2://{quote_plus(config.username)}:{quote_plus(config.password)}@"
            f"{config.host}:{port}/{config.database}",
            "SELECT 1",
        )
    raise DatabaseError(f"未対応のDBMSです: {config.dbms}")


def _connect_engine(config: DatabaseConfig):
    """Create and validate engine (with SQL Server driver fallback)."""
    validate_config(config)
    create_engine, _inspect, text = _sqlalchemy_imports()
    dbms = normalize_dbms(config.dbms)

    if dbms == "sqlserver":
        errors: list[str] = []
        for driver in SQLSERVER_ODBC_DRIVER_CANDIDATES:
            try:
                import pyodbc  # noqa: F401
            except ImportError as exc:
                raise DatabaseError("SQL Server接続には `pyodbc` が必要です。") from exc
            url = _build_sqlserver_url(config, driver)
            engine = create_engine(url, future=True, pool_pre_ping=True)
            try:
                with engine.connect() as connection:
                    connection.execute(text("SELECT 1"))
                return engine, text
            except Exception as exc:  # pragma: no cover
                errors.append(f"{driver}: {type(exc).__name__}")
                engine.dispose()
        raise DatabaseError(f"SQL Server接続に失敗しました。詳細: {'; '.join(errors)}")

    url, ping_query = _build_url_and_ping_query(config)
    engine = create_engine(url, future=True, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            connection.execute(text(ping_query))
    except Exception as exc:  # pragma: no cover
        engine.dispose()
        raise DatabaseError(f"{dbms_label(dbms)} 接続に失敗しました: {exc}") from exc
    return engine, text


def _default_schema(config: DatabaseConfig) -> str | None:
    """Return default schema by DBMS."""
    dbms = normalize_dbms(config.dbms)
    user_schema = str(config.schema or "").strip()
    if user_schema:
        return user_schema
    if dbms == "sqlserver":
        return "dbo"
    if dbms == "postgresql":
        return "public"
    if dbms == "oracle":
        return str(config.username or "").upper() or None
    return None


def list_tables(config: DatabaseConfig) -> list[str]:
    """List tables as `schema.table` or `table` strings."""
    engine, _text = _connect_engine(config)
    _create_engine, inspect, _ = _sqlalchemy_imports()
    schema = _default_schema(config)
    dbms = normalize_dbms(config.dbms)
    try:
        inspector = inspect(engine)
        tables: list[str] = []
        if dbms == "sqlite":
            names = inspector.get_table_names()
            tables.extend(names)
        else:
            if schema:
                names = inspector.get_table_names(schema=schema)
                tables.extend([f"{schema}.{name}" for name in names])
            else:
                names = inspector.get_table_names()
                tables.extend(names)
        return sorted(set(tables))
    except Exception as exc:  # pragma: no cover
        raise DatabaseError(f"テーブル一覧の取得に失敗しました: {exc}") from exc
    finally:
        engine.dispose()


def _split_schema_table(raw_table: str) -> tuple[str | None, str]:
    """Split `schema.table` into parts."""
    stripped = str(raw_table or "").strip().replace("[", "").replace("]", "").replace("`", "").replace('"', "")
    if not stripped:
        raise DatabaseError("テーブル名が空です。")
    parts = [part for part in stripped.split(".") if part]
    if len(parts) == 1:
        return None, parts[0]
    return parts[0], ".".join(parts[1:])


def _quote_ident(dbms: str, name: str) -> str:
    """Quote identifier for dbms."""
    if dbms == "sqlserver":
        return f"[{name}]"
    if dbms == "mysql":
        return f"`{name}`"
    return f'"{name}"'


def build_select_sample_query(config: DatabaseConfig, table_name: str, top_n: int = 1000) -> str:
    """Build SELECT sample query for selected DBMS."""
    dbms = normalize_dbms(config.dbms)
    schema, table = _split_schema_table(table_name)
    bounded_n = max(int(top_n), 1)
    qualified = _quote_ident(dbms, table)
    if schema:
        qualified = f"{_quote_ident(dbms, schema)}.{qualified}"

    if dbms == "sqlserver":
        return f"SELECT TOP ({bounded_n}) * FROM {qualified}"
    if dbms in {"mysql", "sqlite", "postgresql"}:
        return f"SELECT * FROM {qualified} LIMIT {bounded_n}"
    if dbms == "oracle":
        return f"SELECT * FROM {qualified} FETCH FIRST {bounded_n} ROWS ONLY"
    return f"SELECT * FROM {qualified}"


def _apply_row_limit_query(config: DatabaseConfig, query: str, row_limit: int | None) -> str:
    """Wrap query with DB-specific row limit expression for previews."""
    if row_limit is None:
        return query
    bounded = max(1, int(row_limit))
    dbms = normalize_dbms(config.dbms)
    stripped = query.strip().rstrip(";")

    if dbms == "sqlserver":
        return f"SELECT TOP ({bounded}) * FROM ({stripped}) AS _ds_src"
    if dbms == "oracle":
        return f"SELECT * FROM ({stripped}) _ds_src WHERE ROWNUM <= {bounded}"
    return f"SELECT * FROM ({stripped}) AS _ds_src LIMIT {bounded}"


def execute_query(config: DatabaseConfig, query: str, row_limit: int | None = None) -> pd.DataFrame:
    """Execute SQL query and return dataframe."""
    normalized_query = (query or "").strip()
    if not normalized_query:
        raise DatabaseError("SQLクエリを入力してください。")
    normalized_query = _apply_row_limit_query(config, normalized_query, row_limit)

    engine, text = _connect_engine(config)
    try:
        with engine.connect() as connection:
            return pd.read_sql_query(text(normalized_query), connection)
    except Exception as exc:  # pragma: no cover
        raise DatabaseError(f"SQL実行に失敗しました: {exc}") from exc
    finally:
        engine.dispose()
