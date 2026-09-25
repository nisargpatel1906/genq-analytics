# backend/services/schema_linker.py

import json
import logging
import re
import sqlite3
from typing import Dict, Any, List, Optional, Tuple
import numpy as np
import pandas as pd
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.pool import StaticPool

from services.llm import chat_completion
from services.agent_prompts import SCHEMA_LINKER_PROMPT
from app.utils import parse_json_safely

logger = logging.getLogger("genq_api.schema_linker")


def clean_table_name(name: str) -> str:
    """Sanitizes raw file or table names into valid SQL table identifiers."""
    base = re.sub(r"\.(csv|xlsx|parquet|tsv)$", "", name, flags=re.IGNORECASE)
    cleaned = re.sub(r"[^\w]+", "_", base).strip("_").lower()
    if cleaned and cleaned[0].isdigit():
        cleaned = f"t_{cleaned}"
    return cleaned or "table_data"


class RelationalDatabaseEngine:
    """In-memory and external relational database management for multi-table analysis."""

    def __init__(self, db_uri: Optional[str] = None):
        self.db_uri = db_uri
        self.is_external = bool(db_uri)
        if self.is_external:
            if db_uri.startswith("sqlite"):
                self.engine = create_engine(
                    db_uri,
                    connect_args={"check_same_thread": False},
                    poolclass=StaticPool,
                )
            else:
                self.engine = create_engine(db_uri)
            self.conn = None
        else:
            self.engine = None
            self.conn = sqlite3.connect(":memory:", check_same_thread=False)

    def load_dataframes(self, tables: Dict[str, pd.DataFrame]) -> Dict[str, str]:
        """Loads a dictionary of DataFrames into the in-memory SQLite database.
        Returns a mapping of original_name -> sanitized_sql_table_name."""
        table_mapping = {}
        target_conn = self.engine if self.is_external else self.conn
        for original_name, df in tables.items():
            tbl_name = clean_table_name(original_name)
            # Prevent table name collisions
            counter = 1
            unique_tbl = tbl_name
            while unique_tbl in table_mapping.values():
                unique_tbl = f"{tbl_name}_{counter}"
                counter += 1

            table_mapping[original_name] = unique_tbl
            # Write to SQLite
            # Sanitize column names for SQLite
            safe_df = df.copy()
            safe_df.columns = [re.sub(r"[^\w]+", "_", str(c)).strip("_").lower() for c in safe_df.columns]
            safe_df.to_sql(unique_tbl, target_conn, if_exists="replace", index=False)
            logger.info("Loaded table '%s' with %d rows and %d columns into SQLite.", unique_tbl, len(safe_df), len(safe_df.columns))

        return table_mapping

    def load_dataframe(self, table_name: str, df: pd.DataFrame) -> str:
        """Loads a single DataFrame into SQLite."""
        mapping = self.load_dataframes({table_name: df})
        return mapping[table_name]

    def introspect_tables(self) -> Dict[str, Any]:
        """Introspects table names, columns, data types, sample rows, and key candidates."""
        metadata = {}
        if self.is_external:
            inspector = inspect(self.engine)
            table_names = inspector.get_table_names()
            with self.engine.connect() as connection:
                for tbl in table_names:
                    cols = inspector.get_columns(tbl)
                    col_names = [c["name"] for c in cols]
                    try:
                        sample_df = pd.read_sql_query(f"SELECT * FROM {tbl} LIMIT 3", connection)
                        sample_rows = sample_df.to_dict("records")
                        count_res = connection.execute(f"SELECT COUNT(*) FROM {tbl}").scalar()
                    except Exception as e:
                        logger.warning("Failed to introspect table %s: %s", tbl, e)
                        sample_rows = []
                        count_res = 0

                    metadata[tbl] = {
                        "columns": col_names,
                        "dtypes": {c["name"]: str(c.get("type", "TEXT")) for c in cols},
                        "row_count": count_res,
                        "sample_rows": sample_rows,
                        "key_candidates": [c for c in col_names if any(k in c.lower() for k in ["id", "key", "code", "num"])],
                    }
        else:
            cursor = self.conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
            tables = [row[0] for row in cursor.fetchall()]
            for tbl in tables:
                df_sample = pd.read_sql_query(f"SELECT * FROM {tbl} LIMIT 3", self.conn)
                cursor.execute(f"SELECT COUNT(*) FROM {tbl}")
                row_count = cursor.fetchone()[0]
                cols = list(df_sample.columns)
                key_cands = [c for c in cols if any(k in c.lower() for k in ["id", "key", "code", "num"])]
                metadata[tbl] = {
                    "columns": cols,
                    "dtypes": {c: str(df_sample[c].dtype) for c in cols},
                    "row_count": row_count,
                    "sample_rows": df_sample.to_dict("records"),
                    "key_candidates": key_cands,
                }

        return metadata

    def execute_query(self, query: str) -> pd.DataFrame:
        """Executes an ANSI SQL query and returns the materialized DataFrame."""
        if self.is_external:
            return pd.read_sql_query(query, self.engine)
        return pd.read_sql_query(query, self.conn)

    def close(self):
        """Closes any open database connections."""
        if self.conn:
            try:
                self.conn.close()
            except Exception:
                pass


def infer_candidate_relationships(tables_meta: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Analyzes column names and keys to discover potential join relationships across tables."""
    candidates = []
    table_names = list(tables_meta.keys())

    def _get_columns(item: Any) -> List[str]:
        if isinstance(item, pd.DataFrame):
            return item.columns.tolist()
        if isinstance(item, dict):
            return item.get("columns", [])
        return []

    for i in range(len(table_names)):
        for j in range(i + 1, len(table_names)):
            t1 = table_names[i]
            t2 = table_names[j]
            cols1 = _get_columns(tables_meta[t1])
            cols2 = _get_columns(tables_meta[t2])

            # 1. Exact Column Matches (e.g., customer_id in both t1 and t2)
            for c1 in cols1:
                if c1 in cols2:
                    is_id = any(k in c1.lower() for k in ["id", "code", "key", "num"])
                    candidates.append({
                        "left_table": t1,
                        "left_column": c1,
                        "from_table": t1,
                        "from_key": c1,
                        "right_table": t2,
                        "right_column": c1,
                        "to_table": t2,
                        "to_key": c1,
                        "match_type": "exact_name",
                        "is_likely_key": is_id,
                        "confidence": 0.95 if is_id else 0.70,
                    })

            # 2. Singular/Plural Prefix Matches (e.g., user.id <-> orders.user_id)
            clean_t1 = t1.rstrip("s").lower()
            clean_t2 = t2.rstrip("s").lower()

            for c1 in cols1:
                for c2 in cols2:
                    if (c1.lower() == "id" and c2.lower() == f"{clean_t1}_id") or (c2.lower() == "id" and c1.lower() == f"{clean_t2}_id"):
                        candidates.append({
                            "left_table": t1,
                            "left_column": c1,
                            "from_table": t1,
                            "from_key": c1,
                            "right_table": t2,
                            "right_column": c2,
                            "to_table": t2,
                            "to_key": c2,
                            "match_type": "entity_id_prefix",
                            "is_likely_key": True,
                            "confidence": 0.90,
                        })

    # Sort candidates by confidence descending
    candidates.sort(key=lambda x: x["confidence"], reverse=True)
    return candidates


def generate_deterministic_fallback_join(tables_meta: Dict[str, Any], candidates: List[Dict[str, Any]]) -> Tuple[str, str]:
    """Builds a robust, deterministic ANSI SQL join query when LLM planning is skipped or offline."""
    table_names = list(tables_meta.keys())
    if not table_names:
        return "", "No tables available."
    if len(table_names) == 1:
        return f"SELECT * FROM {table_names[0]}", f"Single table analysis of {table_names[0]}."

    # Identify primary Fact table: highest row count or highest foreign keys
    fact_table = max(table_names, key=lambda t: tables_meta[t].get("row_count", 0))
    joined_tables = {fact_table}
    joins_sql = []
    selected_cols = [f"{fact_table}.{c} AS {fact_table}_{c}" for c in tables_meta[fact_table]["columns"]]

    remaining_tables = [t for t in table_names if t != fact_table]

    for cand in candidates:
        t_left = cand["left_table"]
        t_right = cand["right_table"]

        if t_left in joined_tables and t_right in remaining_tables:
            joins_sql.append(f"LEFT JOIN {t_right} ON {t_left}.{cand['left_column']} = {t_right}.{cand['right_column']}")
            for c in tables_meta[t_right]["columns"]:
                if c != cand["right_column"]:
                    selected_cols.append(f"{t_right}.{c} AS {t_right}_{c}")
            joined_tables.add(t_right)
            remaining_tables.remove(t_right)
        elif t_right in joined_tables and t_left in remaining_tables:
            joins_sql.append(f"LEFT JOIN {t_left} ON {t_right}.{cand['right_column']} = {t_left}.{cand['left_column']}")
            for c in tables_meta[t_left]["columns"]:
                if c != cand["left_column"]:
                    selected_cols.append(f"{t_left}.{c} AS {t_left}_{c}")
            joined_tables.add(t_left)
            remaining_tables.remove(t_left)

    cols_clause = ",\n    ".join(selected_cols) if selected_cols else f"{fact_table}.*"
    joins_clause = "\n".join(joins_sql)
    query = f"SELECT\n    {cols_clause}\nFROM {fact_table}\n{joins_clause}"
    summary = f"Unified analytical model centered on fact table '{fact_table}', linking {len(joined_tables) - 1} dimension table(s)."

    return query, summary


def build_unified_analytical_dataset(
    tables: Dict[str, pd.DataFrame],
    user_instruction: Optional[str] = None,
    timeout: int = 120,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """Takes multiple uploaded DataFrames, analyzes relational relationships,
    executes an optimal ANSI SQL join, and returns the unified DataFrame and manifest."""
    if not tables:
        raise ValueError("No tables provided for multi-table analysis.")

    # 1. Single Table Fast-Path
    if len(tables) == 1:
        name, df = next(iter(tables.items()))
        manifest = {
            "type": "single_table",
            "tables_loaded": {name: len(df)},
            "inferred_relationships": [],
            "sql_query": f"SELECT * FROM {clean_table_name(name)}",
            "rows_produced": len(df),
            "columns_produced": list(df.columns),
            "summary": f"Single table '{name}' loaded with {len(df):,} rows.",
        }
        return df, manifest

    # 2. Multi-Table Relational Engine Setup
    engine = RelationalDatabaseEngine()
    try:
        table_mapping = engine.load_dataframes(tables)
        tables_meta = engine.introspect_tables()
        candidate_rels = infer_candidate_relationships(tables_meta)

        prompt = SCHEMA_LINKER_PROMPT.format(
            tables_metadata=json.dumps(tables_meta, default=str),
            candidate_relationships=json.dumps(candidate_rels, default=str),
            user_instruction=user_instruction or "Create an integrated, denormalized analytical dataset centered on primary transactions or observations.",
        )

        messages = [
            {"role": "system", "content": "You are a Principal Database Architect & Data Modeling Engineer. Design the optimal ANSI SQL join query for this multi-table dataset. Return JSON only."},
            {"role": "user", "content": prompt}
        ]

        sql_query = ""
        summary = ""
        joins_info = []

        try:
            response = chat_completion(messages, task="analysis", json_mode=True, timeout=timeout)
            parsed = parse_json_safely(response)
            if "sql_query" in parsed and parsed["sql_query"]:
                sql_query = parsed["sql_query"]
                summary = parsed.get("summary", "Unified analytical dataset generated.")
                joins_info = parsed.get("joins", [])
        except Exception as e:
            logger.warning("Schema linker LLM generation error: %s. Using deterministic join fallback.", e)

        # 3. Fallback deterministic query if LLM is unavailable or empty
        if not sql_query:
            sql_query, summary = generate_deterministic_fallback_join(tables_meta, candidate_rels)

        logger.info("Executing Schema Linker SQL Query:\n%s", sql_query)
        try:
            unified_df = engine.execute_query(sql_query)
        except Exception as exec_err:
            logger.warning("LLM SQL Query execution failed: %s. Executing fallback join.", exec_err)
            sql_query, summary = generate_deterministic_fallback_join(tables_meta, candidate_rels)
            unified_df = engine.execute_query(sql_query)

        manifest = {
            "type": "multi_table_relational",
            "tables": [{"table_name": orig, "row_count": len(df), "candidate_keys": list(df.columns[:2])} for orig, df in tables.items()],
            "tables_loaded": {orig: len(df) for orig, df in tables.items()},
            "table_mapping": table_mapping,
            "inferred_relationships": candidate_rels,
            "joins": joins_info,
            "sql_query": sql_query,
            "row_count": len(unified_df),
            "unified_row_count": len(unified_df),
            "rows_produced": len(unified_df),
            "columns_produced": list(unified_df.columns),
            "summary": summary,
        }

        return unified_df, manifest

    finally:
        engine.close()


def connect_and_materialize_sql(
    db_uri: str,
    query: Optional[str] = None,
    table_names: Optional[List[str]] = None,
    user_instruction: Optional[str] = None,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """Connects to an external SQL database via URI, introspects tables or executes a query,
    and returns the unified analytical DataFrame and schema manifest."""
    engine = RelationalDatabaseEngine(db_uri=db_uri)
    try:
        if query:
            logger.info("Executing user SQL query directly on %s", db_uri)
            df = engine.execute_query(query)
            manifest = {
                "type": "direct_sql_query",
                "db_uri_type": db_uri.split("://")[0] if "://" in db_uri else "database",
                "sql_query": query,
                "rows_produced": len(df),
                "columns_produced": list(df.columns),
                "summary": f"Direct SQL query executed, returning {len(df):,} rows and {len(df.columns)} columns.",
            }
            return df, manifest

        tables_meta = engine.introspect_tables()
        if table_names:
            tables_meta = {t: tables_meta[t] for t in table_names if t in tables_meta}

        candidate_rels = infer_candidate_relationships(tables_meta)
        sql_query, summary = generate_deterministic_fallback_join(tables_meta, candidate_rels)
        df = engine.execute_query(sql_query)

        manifest = {
            "type": "database_connection",
            "db_uri_type": db_uri.split("://")[0] if "://" in db_uri else "database",
            "tables_introspected": list(tables_meta.keys()),
            "inferred_relationships": candidate_rels,
            "sql_query": sql_query,
            "rows_produced": len(df),
            "columns_produced": list(df.columns),
            "summary": summary,
        }
        return df, manifest

    finally:
        engine.close()
