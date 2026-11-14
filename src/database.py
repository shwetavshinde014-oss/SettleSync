
"""
SettleSync - SQLite Database Module

Features:
- SQLite database initialization
- Save reconciliation runs
- Store transaction results
- Store unmatched bank credit exceptions
- Retrieve reconciliation history
- Retrieve historical transactions and exceptions
- Safe NumPy/Pandas value conversion
"""

import sqlite3
import json

from pathlib import Path
from datetime import datetime
from numbers import Number

import pandas as pd


# =========================================================
# 1. DATABASE CONFIGURATION
# =========================================================

BASE_DIR = Path(__file__).resolve().parent.parent

DB_PATH = BASE_DIR / "data" / "settlesync.db"


# =========================================================
# 2. VALUE CONVERSION
# =========================================================

def convert_value(value):
    """
    Convert NumPy and Pandas values into
    Python-native values for JSON and SQLite.
    """

    if value is None:
        return None

    if pd.isna(value):
        return None

    if hasattr(value, "item"):
        return value.item()

    if isinstance(value, Number):
        return value

    return str(value)


def convert_summary(summary):
    """Convert summary values into JSON-safe values."""

    return {
        str(key): convert_value(value)
        for key, value in summary.items()
    }


# =========================================================
# 3. DATABASE CONNECTION
# =========================================================

def get_connection():
    """Create and return a SQLite connection."""

    DB_PATH.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    connection = sqlite3.connect(DB_PATH)

    connection.execute("PRAGMA foreign_keys = ON")

    return connection


# =========================================================
# 4. INITIALIZE DATABASE TABLES
# =========================================================

def initialize_database():
    """Create database tables if they do not exist."""

    connection = get_connection()

    try:

        cursor = connection.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS reconciliation_runs (
                run_id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_date TEXT NOT NULL,
                total_orders INTEGER,
                successful_captures INTEGER,
                matched_references INTEGER,
                unmatched_references INTEGER,
                discrepant_references INTEGER,
                match_rate REAL,
                expected_net_settlement REAL,
                actual_bank_credits REAL,
                overall_variance REAL,
                summary_json TEXT
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS transaction_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL,
                payment_id TEXT,
                order_id TEXT,
                gateway_ref TEXT,
                payment_amount REAL,
                refund_amount REAL,
                expected_fee REAL,
                expected_net REAL,
                allocated_received_net REAL,
                status TEXT,
                FOREIGN KEY (run_id)
                    REFERENCES reconciliation_runs(run_id)
                    ON DELETE CASCADE
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS exception_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL,
                settlement_id TEXT,
                settlement_ref TEXT,
                net_amount REAL,
                bank_status TEXT,
                exception_type TEXT,
                FOREIGN KEY (run_id)
                    REFERENCES reconciliation_runs(run_id)
                    ON DELETE CASCADE
            )
        """)

        connection.commit()

    finally:

        connection.close()


# =========================================================
# 5. SAVE RECONCILIATION RESULTS
# =========================================================

def save_reconciliation(result):
    """
    Save a reconciliation run, its transactions,
    and unmatched bank credit exceptions.

    Returns the newly created run ID.
    """

    initialize_database()

    connection = get_connection()

    try:

        cursor = connection.cursor()

        summary = convert_summary(
            result["summary"]
        )

        run_date = datetime.now().isoformat(
            timespec="seconds"
        )

        # Convert summary into JSON-safe text
        summary_json = json.dumps(
            summary,
            default=convert_value
        )

        # Insert reconciliation summary
        cursor.execute("""
            INSERT INTO reconciliation_runs (
                run_date,
                total_orders,
                successful_captures,
                matched_references,
                unmatched_references,
                discrepant_references,
                match_rate,
                expected_net_settlement,
                actual_bank_credits,
                overall_variance,
                summary_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            run_date,
            summary.get("total_orders", 0),
            summary.get("successful_captures", 0),
            summary.get("matched_references", 0),
            summary.get("unmatched_references", 0),
            summary.get("discrepant_references", 0),
            summary.get("match_rate", 0.0),
            summary.get("expected_net_settlement", 0.0),
            summary.get("actual_bank_credits", 0.0),
            summary.get("overall_variance", 0.0),
            summary_json
        ))

        run_id = cursor.lastrowid

        # -------------------------------------------------
        # SAVE TRANSACTION RESULTS
        # -------------------------------------------------

        transactions = result["transactions"]

        if not transactions.empty:

            for _, row in transactions.iterrows():

                cursor.execute("""
                    INSERT INTO transaction_results (
                        run_id,
                        payment_id,
                        order_id,
                        gateway_ref,
                        payment_amount,
                        refund_amount,
                        expected_fee,
                        expected_net,
                        allocated_received_net,
                        status
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    run_id,
                    str(row["payment_id"]),
                    str(row["order_id"]),
                    str(row["gateway_ref"]),
                    float(row["payment_amount"]),
                    float(row["refund_amount"]),
                    float(row["expected_fee"]),
                    float(row["expected_net"]),
                    float(row["allocated_received_net"]),
                    str(row["status"])
                ))

        # -------------------------------------------------
        # SAVE UNMATCHED BANK CREDITS
        # -------------------------------------------------

        unmatched = result["unmatched_bank"]

        if not unmatched.empty:

            for _, row in unmatched.iterrows():

                cursor.execute("""
                    INSERT INTO exception_records (
                        run_id,
                        settlement_id,
                        settlement_ref,
                        net_amount,
                        bank_status,
                        exception_type
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    run_id,
                    str(row["settlement_id"]),
                    str(row["settlement_ref"]),
                    float(row["net_amount"]),
                    str(row["bank_status"]),
                    "Unmatched Bank Credit"
                ))

        connection.commit()

        return run_id

    except Exception:

        connection.rollback()

        raise

    finally:

        connection.close()


# =========================================================
# 6. FETCH RECONCILIATION HISTORY
# =========================================================

def get_reconciliation_history():
    """Retrieve all saved reconciliation runs."""

    initialize_database()

    connection = get_connection()

    try:

        query = """
            SELECT
                run_id,
                run_date,
                total_orders,
                successful_captures,
                matched_references,
                unmatched_references,
                discrepant_references,
                match_rate,
                expected_net_settlement,
                actual_bank_credits,
                overall_variance
            FROM reconciliation_runs
            ORDER BY run_id DESC
        """

        history = pd.read_sql_query(
            query,
            connection
        )

        return history

    finally:

        connection.close()


# =========================================================
# 7. FETCH TRANSACTIONS FOR A RUN
# =========================================================

def get_run_transactions(run_id):
    """Retrieve transaction records for a selected run."""

    initialize_database()

    connection = get_connection()

    try:

        transactions = pd.read_sql_query(
            """
            SELECT
                id,
                run_id,
                payment_id,
                order_id,
                gateway_ref,
                payment_amount,
                refund_amount,
                expected_fee,
                expected_net,
                allocated_received_net,
                status
            FROM transaction_results
            WHERE run_id = ?
            ORDER BY id
            """,
            connection,
            params=(int(run_id),)
        )

        return transactions

    finally:

        connection.close()


# =========================================================
# 8. FETCH EXCEPTIONS FOR A RUN
# =========================================================

def get_run_exceptions(run_id):
    """Retrieve unmatched bank credit exceptions."""

    initialize_database()

    connection = get_connection()

    try:

        exceptions = pd.read_sql_query(
            """
            SELECT
                id,
                run_id,
                settlement_id,
                settlement_ref,
                net_amount,
                bank_status,
                exception_type
            FROM exception_records
            WHERE run_id = ?
            ORDER BY id
            """,
            connection,
            params=(int(run_id),)
        )

        return exceptions

    finally:

        connection.close()


# =========================================================
# 9. GET A SINGLE RECONCILIATION SUMMARY
# =========================================================

def get_run_summary(run_id):
    """Retrieve the saved JSON summary for a run."""

    initialize_database()

    connection = get_connection()

    try:

        cursor = connection.cursor()

        cursor.execute(
            """
            SELECT summary_json
            FROM reconciliation_runs
            WHERE run_id = ?
            """,
            (int(run_id),)
        )

        row = cursor.fetchone()

        if row is None:
            return None

        return json.loads(row[0])

    finally:

        connection.close()
