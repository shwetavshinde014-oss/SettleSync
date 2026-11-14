
import streamlit as st
import pandas as pd
import sqlite3
import plotly.express as px
from pathlib import Path

# Application configuration
st.set_page_config(
    page_title="Payment Reconciliation",
    page_icon="💳",
    layout="wide"
)

st.title("💳 Digital Payment Settlement Reconciliation")
st.write("Merchant Finance Dashboard")

# Project paths
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = BASE_DIR / "reconciliation.db"

# Load datasets
@st.cache_data
def load_data():
    orders = pd.read_csv(DATA_DIR / "orders.csv")
    payments = pd.read_csv(DATA_DIR / "payments.csv")
    refunds = pd.read_csv(DATA_DIR / "refunds.csv")
    settlements = pd.read_csv(DATA_DIR / "settlements.csv")

    return orders, payments, refunds, settlements


try:
    orders, payments, refunds, settlements = load_data()
except Exception as e:
    st.error(f"Dataset loading error: {e}")
    st.stop()

# Data cleaning
payments["gateway_ref"] = (
    payments["gateway_ref"].astype(str).str.upper()
    .str.replace(r"[^A-Z0-9]", "", regex=True)
)

settlements["settlement_ref"] = (
    settlements["settlement_ref"].astype(str).str.upper()
    .str.replace(r"[^A-Z0-9]", "", regex=True)
)

# Select successful payments
successful = payments[
    payments["payment_status"] == "SUCCESS"
].copy()

# Calculate successful refunds
successful_refunds = refunds[
    refunds["refund_status"] == "SUCCESS"
]

refund_totals = (
    successful_refunds.groupby("payment_id")["refund_amount"]
    .sum()
)

successful["refund_amount"] = (
    successful["payment_id"].map(refund_totals).fillna(0)
)

# Calculate fees and expected settlement
successful["fee_expected"] = (
    successful["payment_amount"] * 0.02
).round(2)

successful["expected_net"] = (
    successful["payment_amount"]
    - successful["fee_expected"]
    - successful["refund_amount"]
).round(2)

# Match payment references with bank settlements
bank = settlements[
    settlements["bank_status"] == "CREDITED"
].copy()

bank_summary = (
    bank.groupby("settlement_ref")
    .agg(
        received_net=("net_amount", "sum"),
        settlement_ids=("settlement_id",
                        lambda x: ", ".join(x))
    )
    .reset_index()
)

result = successful.merge(
    bank_summary,
    left_on="gateway_ref",
    right_on="settlement_ref",
    how="left"
)

result["received_net"] = result["received_net"].fillna(0)

result["variance"] = (
    result["received_net"] - result["expected_net"]
).round(2)

result["status"] = result.apply(
    lambda r: (
        "Unmatched" if pd.isna(r["settlement_ref"])
        else "Matched" if abs(r["variance"]) <= 1
        else "Discrepant"
    ),
    axis=1
)

# Store processed data in SQLite
with sqlite3.connect(DB_PATH) as conn:
    orders.to_sql("orders", conn, if_exists="replace", index=False)
    payments.to_sql("payments", conn, if_exists="replace", index=False)
    refunds.to_sql("refunds", conn, if_exists="replace", index=False)
    settlements.to_sql("settlements", conn, if_exists="replace", index=False)
    result.to_sql(
        "reconciliation_results",
        conn,
        if_exists="replace",
        index=False
    )

# Dashboard KPIs
st.header("Reconciliation Overview")

total = len(successful)
matched = (result["status"] == "Matched").sum()
unmatched = (result["status"] == "Unmatched").sum()
discrepant = (result["status"] == "Discrepant").sum()

match_rate = (matched / total * 100) if total else 0

expected = successful["expected_net"].sum()
received = bank["net_amount"].sum()

c1, c2, c3, c4 = st.columns(4)

c1.metric("Successful Payments", total)
c2.metric("Matched Payments", int(matched))
c3.metric("Unmatched Payments", int(unmatched))
c4.metric("Match Rate", f"{match_rate:.1f}%")

c5, c6, c7 = st.columns(3)

c5.metric("Expected Net", f"₹{expected:,.2f}")
c6.metric("Received Net", f"₹{received:,.2f}")
c7.metric("Discrepant Payments", int(discrepant))

# Charts
st.subheader("Payment Status Analysis")

status_data = result["status"].value_counts().reset_index()
status_data.columns = ["Status", "Count"]

fig = px.pie(
    status_data,
    names="Status",
    values="Count",
    hole=0.45,
    title="Reconciliation Status"
)

st.plotly_chart(fig, use_container_width=True)

# Transaction records
st.subheader("Reconciliation Records")

filter_status = st.multiselect(
    "Filter by status",
    options=result["status"].unique().tolist(),
    default=result["status"].unique().tolist()
)

filtered = result[result["status"].isin(filter_status)]

st.dataframe(filtered, use_container_width=True)

# Finance report
st.subheader("Finance Review Report")

csv = result.to_csv(index=False).encode("utf-8")

st.download_button(
    "Download Reconciliation Report",
    data=csv,
    file_name="finance_reconciliation_report.csv",
    mime="text/csv"
)

# Interpretation
st.subheader("Interpretation")

st.write(f"""
- Total successful payments: {total}
- Matched payments: {matched}
- Unmatched payments: {unmatched}
- Discrepant payments: {discrepant}
- Reconciliation match rate: {match_rate:.2f}%
- Expected net settlement: ₹{expected:,.2f}
- Bank credits received: ₹{received:,.2f}

Transactions marked as unmatched or discrepant require
further finance team investigation.
""")
