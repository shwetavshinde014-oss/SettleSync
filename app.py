
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

from src.reconciliation_engine import reconcile_payments
from src.report_generator import (
    generate_excel_report,
    generate_pdf_report
)
from src.database import (
    initialize_database,
    save_reconciliation,
    get_reconciliation_history,
    get_run_transactions,
    get_run_exceptions
)


# =========================================================
# 1. PAGE CONFIGURATION
# =========================================================

st.set_page_config(
    page_title="SettleSync | Payment Reconciliation",
    page_icon="💳",
    layout="wide",
    initial_sidebar_state="expanded"
)

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"


# =========================================================
# 2. DARK THEME
# =========================================================

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&display=swap');

html, body, [class*="css"] {
    font-family: 'DM Sans', sans-serif;
}

.stApp {
    background: #0b1020;
    color: #edf2ff;
}

[data-testid="stSidebar"] {
    background: #11182b;
    border-right: 1px solid #26314a;
}

[data-testid="stHeader"] {
    background: rgba(11, 16, 32, 0.95);
}

h1, h2, h3 {
    color: #f4f7ff;
}

.brand {
    font-size: 27px;
    font-weight: 700;
    color: #f4f7ff;
    letter-spacing: -1px;
}

.brand span {
    color: #55d6be;
}

.subtitle {
    color: #8e9bb7;
    font-size: 14px;
    margin-top: -8px;
}

.section-label {
    color: #8e9bb7;
    font-size: 12px;
    font-weight: 700;
    letter-spacing: 1.2px;
    text-transform: uppercase;
    margin-bottom: 12px;
}

.metric-card {
    background: linear-gradient(145deg, #151f35, #111a2d);
    border: 1px solid #293650;
    border-radius: 14px;
    padding: 19px;
    min-height: 120px;
}

.metric-label {
    color: #91a0bc;
    font-size: 13px;
    margin-bottom: 10px;
}

.metric-value {
    color: #f5f7ff;
    font-size: 27px;
    font-weight: 700;
}

.metric-note {
    color: #8e9bb7;
    font-size: 12px;
    margin-top: 5px;
}

.hero {
    background: linear-gradient(110deg, #172743, #122c38);
    border: 1px solid #28505b;
    border-radius: 18px;
    padding: 25px 28px;
    margin: 10px 0 25px 0;
}

.hero-title {
    font-size: 25px;
    font-weight: 700;
    color: #ffffff;
}

.hero-text {
    color: #b7c8d9;
    font-size: 14px;
    margin-top: 5px;
}

.footer {
    color: #71809d;
    font-size: 12px;
    text-align: center;
    padding: 25px 0 10px 0;
}

div.stButton > button {
    background: #55d6be;
    color: #07151a;
    border: none;
    border-radius: 8px;
    font-weight: 700;
}

div.stButton > button:hover {
    background: #7ce8d2;
    color: #07151a;
}

</style>
""", unsafe_allow_html=True)


# =========================================================
# 3. HELPER FUNCTIONS
# =========================================================

def money(value):
    return f"₹{float(value):,.2f}"


def metric_card(label, value, note=""):

    st.markdown(
        f"""
        <div class="metric-card">
            <div class="metric-label">{label}</div>
            <div class="metric-value">{value}</div>
            <div class="metric-note">{note}</div>
        </div>
        """,
        unsafe_allow_html=True
    )


def load_default_datasets():

    filenames = {
        "orders": "orders.csv",
        "payments": "payments.csv",
        "refunds": "refunds.csv",
        "settlements": "settlements.csv"
    }

    data = {}

    for name, filename in filenames.items():

        path = DATA_DIR / filename

        if not path.exists():
            raise FileNotFoundError(
                f"Missing source file: {filename}"
            )

        data[name] = pd.read_csv(path)

    return data


def load_uploaded_datasets(uploaded_files):

    data = {}

    for name, uploaded_file in uploaded_files.items():

        if uploaded_file is None:
            raise ValueError(
                f"Please upload the {name} CSV file."
            )

        uploaded_file.seek(0)

        data[name] = pd.read_csv(uploaded_file)

    return data


def prepare_pending_settlements(data, result):
    """
    Create pending settlement records if the reconciliation
    engine has not already supplied them.
    """

    if "pending_settlements" in result:
        return result["pending_settlements"]

    settlements = data["settlements"].copy()

    if "bank_status" not in settlements.columns:
        return pd.DataFrame()

    pending = settlements[
        settlements["bank_status"]
        .astype(str)
        .str.upper()
        .str.strip()
        .isin(["PENDING", "PROCESSING", "INITIATED"])
    ].copy()

    return pending


# =========================================================
# 4. INITIALIZE DATABASE
# =========================================================

try:
    initialize_database()

except Exception as error:
    st.error(f"Database initialization failed: {error}")
    st.stop()


# =========================================================
# 5. SIDEBAR
# =========================================================

with st.sidebar:

    st.markdown(
        '<div class="brand">Settle<span>Sync</span></div>',
        unsafe_allow_html=True
    )

    st.markdown(
        '<p class="subtitle">Payment Intelligence Platform</p>',
        unsafe_allow_html=True
    )

    st.divider()

    st.markdown("### Navigation")

    page = st.radio(
        "Choose a page",
        [
            "Overview",
            "Reconciliation",
            "Exceptions",
            "Data Explorer",
            "History"
        ],
        label_visibility="collapsed"
    )

    st.divider()

    st.markdown("### Reconciliation Settings")

    fee_rate_percent = st.number_input(
        "Gateway fee rate (%)",
        min_value=0.0,
        max_value=100.0,
        value=2.0,
        step=0.25
    )

    tolerance = st.number_input(
        "Matching tolerance (₹)",
        min_value=0.0,
        value=1.0,
        step=0.5
    )

    st.caption(
        "These are configurable demonstration assumptions."
    )

    st.divider()

    st.markdown("### Data Source")

    upload_mode = st.toggle(
        "Upload my own CSV files",
        value=False
    )

    uploaded_orders = None
    uploaded_payments = None
    uploaded_refunds = None
    uploaded_settlements = None

    if upload_mode:

        st.caption("Upload all four files to run reconciliation.")

        uploaded_orders = st.file_uploader(
            "Orders CSV",
            type=["csv"],
            key="orders_upload"
        )

        uploaded_payments = st.file_uploader(
            "Payments CSV",
            type=["csv"],
            key="payments_upload"
        )

        uploaded_refunds = st.file_uploader(
            "Refunds CSV",
            type=["csv"],
            key="refunds_upload"
        )

        uploaded_settlements = st.file_uploader(
            "Settlements CSV",
            type=["csv"],
            key="settlements_upload"
        )

    else:

        st.caption("Using local CSV datasets")

    st.caption("Currency: INR")
    st.caption("Storage: SQLite database")

    if st.button("Refresh Dashboard", use_container_width=True):
        st.rerun()


# =========================================================
# 6. LOAD DATASETS
# =========================================================

try:

    if upload_mode:

        uploaded_files = {
            "orders": uploaded_orders,
            "payments": uploaded_payments,
            "refunds": uploaded_refunds,
            "settlements": uploaded_settlements
        }

        missing_files = [
            name
            for name, file in uploaded_files.items()
            if file is None
        ]

        if missing_files:

            st.info(
                "Upload all four CSV files to continue. "
                "Missing: " + ", ".join(missing_files)
            )

            st.stop()

        data = load_uploaded_datasets(uploaded_files)

        st.success("Uploaded CSV datasets loaded successfully.")

    else:

        data = load_default_datasets()

except Exception as error:

    st.error(f"Unable to load datasets: {error}")
    st.stop()


# =========================================================
# 7. RUN RECONCILIATION
# =========================================================

try:

    result = reconcile_payments(
        data,
        gateway_fee_rate=fee_rate_percent / 100,
        tolerance=tolerance
    )

    summary = result["summary"]

    # Make pending settlements available to reports and pages
    result["pending_settlements"] = prepare_pending_settlements(
        data,
        result
    )

except Exception as error:

    st.error(f"Reconciliation failed: {error}")

    st.info(
        "Check your CSV column names and numeric values."
    )

    st.stop()


# =========================================================
# 8. GENERATE REPORTS
# =========================================================

try:

    excel_report = generate_excel_report(
        result,
        data
    )

    pdf_report = generate_pdf_report(
        result
    )

except Exception as error:

    st.error(f"Report generation failed: {error}")
    st.stop()


# =========================================================
# 9. COMMON HEADER
# =========================================================

st.markdown(
    '<div class="brand">Settle<span>Sync</span></div>',
    unsafe_allow_html=True
)

st.markdown(
    '<p class="subtitle">Digital Payment Settlement Reconciliation Platform</p>',
    unsafe_allow_html=True
)

st.markdown(
    """
    <div class="hero">
        <div class="hero-title">
            Financial reconciliation, made clearer.
        </div>
        <div class="hero-text">
            Monitor payment captures, gateway fees, refunds,
            settlement credits and transaction exceptions
            from one unified workspace.
        </div>
    </div>
    """,
    unsafe_allow_html=True
)


# =========================================================
# 10. OVERVIEW PAGE
# =========================================================

if page == "Overview":

    st.markdown(
        '<div class="section-label">Platform Overview</div>',
        unsafe_allow_html=True
    )

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        metric_card(
            "Successful Captures",
            summary["successful_captures"],
            "Successfully captured payments"
        )

    with col2:
        metric_card(
            "Matched References",
            summary["matched_references"],
            "References reconciled successfully"
        )

    with col3:
        metric_card(
            "Unmatched References",
            summary["unmatched_references"],
            "No corresponding bank credit"
        )

    with col4:
        metric_card(
            "Discrepant References",
            summary["discrepant_references"],
            "Amount differences detected"
        )

    st.markdown("")

    col5, col6, col7, col8 = st.columns(4)

    with col5:
        metric_card(
            "Match Rate",
            f'{summary["match_rate"]:.1f}%',
            "Matched / total payment references"
        )

    with col6:
        metric_card(
            "Expected Settlement",
            money(summary["expected_net_settlement"]),
            "After estimated fees and refunds"
        )

    with col7:
        metric_card(
            "Bank Credits",
            money(summary["actual_bank_credits"]),
            "All credited bank settlements"
        )

    with col8:
        metric_card(
            "Unmatched Bank Credits",
            summary["unmatched_bank_credits"],
            "Credits without payment reference"
        )

    st.markdown("---")

    # SAVE RECONCILIATION

    st.subheader("Save Reconciliation")

    st.write(
        "Store the current reconciliation results "
        "in the SettleSync SQLite database."
    )

    if st.button("Save Current Reconciliation"):

        try:

            run_id = save_reconciliation(result)

            st.success(
                f"Reconciliation saved successfully! Run ID: {run_id}"
            )

        except Exception as error:

            st.error(
                f"Unable to save reconciliation: {error}"
            )

    st.markdown("---")

    # CHARTS

    left, right = st.columns(2)

    with left:

        st.subheader("Reconciliation Status")

        status_data = pd.DataFrame({
            "Status": [
                "Matched",
                "Unmatched",
                "Discrepant"
            ],
            "Count": [
                summary["matched_references"],
                summary["unmatched_references"],
                summary["discrepant_references"]
            ]
        })

        if status_data["Count"].sum() > 0:

            fig = px.pie(
                status_data,
                names="Status",
                values="Count",
                hole=0.65,
                color="Status",
                color_discrete_map={
                    "Matched": "#55d6be",
                    "Unmatched": "#f4b860",
                    "Discrepant": "#ff7185"
                }
            )

            fig.update_layout(
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                font_color="#eaf0ff",
                legend_title_text=""
            )

            st.plotly_chart(
                fig,
                use_container_width=True
            )

        else:
            st.info("No reconciliation references available.")

    with right:

        st.subheader("Settlement Comparison")

        comparison = pd.DataFrame({
            "Category": [
                "Expected Net",
                "Actual Bank Credits"
            ],
            "Amount": [
                summary["expected_net_settlement"],
                summary["actual_bank_credits"]
            ]
        })

        fig2 = px.bar(
            comparison,
            x="Category",
            y="Amount",
            color="Category",
            text_auto=".2s",
            color_discrete_sequence=[
                "#6d8cff",
                "#55d6be"
            ]
        )

        fig2.update_layout(
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            font_color="#eaf0ff",
            showlegend=False,
            yaxis_title="Amount (₹)",
            xaxis_title=""
        )

        st.plotly_chart(
            fig2,
            use_container_width=True
        )

    st.markdown("---")

    st.subheader("Reference-Level Results")

    st.dataframe(
        result["references"],
        use_container_width=True,
        hide_index=True
    )

    st.markdown("---")

    st.subheader("Download Financial Reports")

    report_col1, report_col2 = st.columns(2)

    with report_col1:

        st.download_button(
            "Download Excel Report",
            data=excel_report,
            file_name="SettleSync_Reconciliation_Report.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True
        )

    with report_col2:

        st.download_button(
            "Download PDF Report",
            data=pdf_report,
            file_name="SettleSync_Reconciliation_Report.pdf",
            mime="application/pdf",
            use_container_width=True
        )


# =========================================================
# 11. RECONCILIATION PAGE
# =========================================================

elif page == "Reconciliation":

    st.subheader("Payment Reconciliation")

    st.write(
        "Compare successful payment references with "
        "credited bank settlement records."
    )

    transactions = result["transactions"]

    if not transactions.empty:

        status_filter = st.multiselect(
            "Filter by reconciliation status",
            ["Matched", "Unmatched", "Discrepant"],
            default=["Matched", "Unmatched", "Discrepant"]
        )

        filtered = transactions[
            transactions["status"].isin(status_filter)
        ]

        st.dataframe(
            filtered,
            use_container_width=True,
            hide_index=True
        )

        st.download_button(
            "Download Reconciliation CSV",
            data=filtered.to_csv(index=False).encode("utf-8"),
            file_name="SettleSync_Reconciliation.csv",
            mime="text/csv"
        )

    else:

        st.info("No successful payment records to reconcile.")

    st.markdown("---")

    st.subheader("Reference-Level Reconciliation")

    st.dataframe(
        result["references"],
        use_container_width=True,
        hide_index=True
    )

    st.markdown("---")

    report_col1, report_col2 = st.columns(2)

    with report_col1:

        st.download_button(
            "Download Excel Report",
            data=excel_report,
            file_name="SettleSync_Reconciliation_Report.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

    with report_col2:

        st.download_button(
            "Download PDF Report",
            data=pdf_report,
            file_name="SettleSync_Reconciliation_Report.pdf",
            mime="application/pdf"
        )


# =========================================================
# 12. EXCEPTIONS PAGE
# =========================================================

elif page == "Exceptions":

    st.subheader("Exceptions & Investigation")

    st.write(
        "Review transactions that require attention "
        "before financial settlement is finalized."
    )

    tab1, tab2, tab3, tab4 = st.tabs([
        "Unmatched Bank Credits",
        "Unmatched Payments",
        "Data Quality",
        "Pending Settlements"
    ])

    with tab1:

        st.markdown("#### Bank credits without a matching payment")

        st.dataframe(
            result["unmatched_bank"],
            use_container_width=True,
            hide_index=True
        )

        if not result["unmatched_bank"].empty:

            st.download_button(
                "Download Unmatched Credits",
                data=result["unmatched_bank"].to_csv(
                    index=False
                ).encode("utf-8"),
                file_name="SettleSync_Unmatched_Credits.csv",
                mime="text/csv"
            )

    with tab2:

        st.markdown("#### Orders without successful payment captures")

        st.dataframe(
            result["orders_without_capture"],
            use_container_width=True,
            hide_index=True
        )

    with tab3:

        st.markdown("#### Data Quality Checks")

        if result["quality_issues"].empty:

            st.success("No data quality issues detected.")

        else:

            st.dataframe(
                result["quality_issues"],
                use_container_width=True,
                hide_index=True
            )

    with tab4:

        st.markdown("#### Bank settlements awaiting credit")

        st.dataframe(
            result["pending_settlements"],
            use_container_width=True,
            hide_index=True
        )


# =========================================================
# 13. DATA EXPLORER PAGE
# =========================================================

elif page == "Data Explorer":

    st.subheader("Source Data Explorer")

    st.write(
        "Inspect the original or uploaded datasets "
        "used by the reconciliation engine."
    )

    tab1, tab2, tab3, tab4 = st.tabs([
        "Orders",
        "Payments",
        "Refunds",
        "Settlements"
    ])

    with tab1:

        st.dataframe(
            data["orders"],
            use_container_width=True,
            hide_index=True
        )

    with tab2:

        st.dataframe(
            data["payments"],
            use_container_width=True,
            hide_index=True
        )

    with tab3:

        st.dataframe(
            data["refunds"],
            use_container_width=True,
            hide_index=True
        )

    with tab4:

        st.dataframe(
            data["settlements"],
            use_container_width=True,
            hide_index=True
        )


# =========================================================
# 14. RECONCILIATION HISTORY PAGE
# =========================================================

elif page == "History":

    st.subheader("Reconciliation History")

    st.write(
        "View previously saved reconciliation runs "
        "and inspect their transaction records."
    )

    try:

        history = get_reconciliation_history()

        if history.empty:

            st.info(
                "No saved reconciliation records yet. "
                "Go to Overview and click Save Current Reconciliation."
            )

        else:

            col1, col2, col3 = st.columns(3)

            with col1:

                metric_card(
                    "Total Saved Runs",
                    len(history),
                    "Stored reconciliation sessions"
                )

            with col2:

                metric_card(
                    "Latest Run ID",
                    history.iloc[0]["run_id"],
                    "Most recent saved record"
                )

            with col3:

                metric_card(
                    "Latest Match Rate",
                    f'{history.iloc[0]["match_rate"]:.1f}%',
                    "Latest reconciliation performance"
                )

            st.markdown("---")

            st.subheader("Saved Reconciliation Records")

            st.dataframe(
                history,
                use_container_width=True,
                hide_index=True
            )

            st.markdown("---")

            st.subheader("Inspect a Previous Run")

            run_ids = history["run_id"].tolist()

            selected_run = st.selectbox(
                "Select Reconciliation Run ID",
                run_ids
            )

            selected_transactions = get_run_transactions(
                int(selected_run)
            )

            selected_exceptions = get_run_exceptions(
                int(selected_run)
            )

            tab1, tab2 = st.tabs([
                "Saved Transactions",
                "Saved Exceptions"
            ])

            with tab1:

                st.dataframe(
                    selected_transactions,
                    use_container_width=True,
                    hide_index=True
                )

                if not selected_transactions.empty:

                    st.download_button(
                        "Download Historical Transactions",
                        data=selected_transactions.to_csv(
                            index=False
                        ).encode("utf-8"),
                        file_name=f"SettleSync_Run_{selected_run}_Transactions.csv",
                        mime="text/csv"
                    )

            with tab2:

                st.dataframe(
                    selected_exceptions,
                    use_container_width=True,
                    hide_index=True
                )

    except Exception as error:

        st.error(
            f"Unable to load reconciliation history: {error}"
        )


# =========================================================
# 15. FOOTER
# =========================================================

st.markdown(
    """
    <div class="footer">
        SettleSync · Digital Payment Settlement Reconciliation
        <br>
        Demonstration Platform · CSV Upload · SQLite · INR
    </div>
    """,
    unsafe_allow_html=True
)
