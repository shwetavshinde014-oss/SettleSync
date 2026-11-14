
"""
SettleSync - Digital Payment Settlement Reconciliation Engine

Features:
- Payment and settlement matching
- Split settlement support
- Successful refund calculations
- Gateway fee calculations
- Failed payment retry handling
- Unmatched payment and bank credit detection
- Discrepancy identification
- Duplicate and data-quality checks
- Reconciliation summary metrics
"""

import re
import pandas as pd


# ---------------------------------------------------------
# 1. REQUIRED DATA COLUMNS
# ---------------------------------------------------------

REQUIRED_COLUMNS = {
    "orders": [
        "order_id",
        "merchant_id",
        "order_date",
        "order_amount",
        "currency"
    ],
    "payments": [
        "payment_id",
        "order_id",
        "gateway_ref",
        "attempt_no",
        "payment_status",
        "payment_amount",
        "payment_date"
    ],
    "refunds": [
        "refund_id",
        "payment_id",
        "refund_amount",
        "refund_status",
        "refund_date"
    ],
    "settlements": [
        "settlement_id",
        "settlement_ref",
        "settlement_date",
        "gross_amount",
        "fee_amount",
        "net_amount",
        "bank_status"
    ]
}


# ---------------------------------------------------------
# 2. REFERENCE NORMALIZATION
# ---------------------------------------------------------

def normalize_reference(value):
    """
    Standardize gateway and settlement references.

    Example:
    'gw 003' -> 'GW003'
    'GW-003' -> 'GW003'
    """

    if pd.isna(value):
        return ""

    return re.sub(
        r"[^A-Z0-9]",
        "",
        str(value).upper().strip()
    )


# ---------------------------------------------------------
# 3. DATA VALIDATION
# ---------------------------------------------------------

def validate_data(data):
    """
    Validate input datasets, required columns,
    numeric values, and duplicate identifiers.
    """

    cleaned = {}
    issues = []

    for name, required in REQUIRED_COLUMNS.items():

        if name not in data:
            raise ValueError(
                f"Missing dataset: {name}"
            )

        df = data[name].copy()

        missing_columns = [
            col for col in required
            if col not in df.columns
        ]

        if missing_columns:
            raise ValueError(
                f"{name} is missing columns: "
                f"{missing_columns}"
            )

        # Remove exact duplicate rows
        original_count = len(df)

        df = df.drop_duplicates().copy()

        removed_count = original_count - len(df)

        if removed_count > 0:
            issues.append({
                "dataset": name,
                "issue": "Exact duplicate rows",
                "count": removed_count
            })

        cleaned[name] = df

    # Convert monetary and numeric columns
    numeric_columns = {
        "orders": ["order_amount"],
        "payments": ["attempt_no", "payment_amount"],
        "refunds": ["refund_amount"],
        "settlements": [
            "gross_amount",
            "fee_amount",
            "net_amount"
        ]
    }

    for name, columns in numeric_columns.items():

        for column in columns:

            cleaned[name][column] = pd.to_numeric(
                cleaned[name][column],
                errors="coerce"
            )

            invalid_count = int(
                cleaned[name][column].isna().sum()
            )

            if invalid_count > 0:
                issues.append({
                    "dataset": name,
                    "issue": f"Invalid or missing {column}",
                    "count": invalid_count
                })

    # Check duplicate identifiers
    id_columns = {
        "orders": "order_id",
        "payments": "payment_id",
        "refunds": "refund_id",
        "settlements": "settlement_id"
    }

    for name, column in id_columns.items():

        duplicates = cleaned[name][
            cleaned[name][column].duplicated(keep=False)
        ]

        if not duplicates.empty:
            issues.append({
                "dataset": name,
                "issue": f"Duplicate {column}",
                "count": len(duplicates)
            })

    # Check missing identifiers
    for name, column in id_columns.items():

        missing_count = int(
            cleaned[name][column].isna().sum()
        )

        if missing_count > 0:
            issues.append({
                "dataset": name,
                "issue": f"Missing {column}",
                "count": missing_count
            })

    # Stop if numeric values are invalid
    for name, columns in numeric_columns.items():

        if cleaned[name][columns].isna().any().any():
            raise ValueError(
                f"{name} contains invalid numeric values. "
                "Please correct them before reconciliation."
            )

    # Validate negative monetary values
    monetary_columns = {
        "orders": ["order_amount"],
        "payments": ["payment_amount"],
        "refunds": ["refund_amount"],
        "settlements": [
            "gross_amount",
            "fee_amount",
            "net_amount"
        ]
    }

    for name, columns in monetary_columns.items():

        for column in columns:

            negative_count = int(
                (cleaned[name][column] < 0).sum()
            )

            if negative_count > 0:
                issues.append({
                    "dataset": name,
                    "issue": f"Negative values in {column}",
                    "count": negative_count
                })

    return cleaned, pd.DataFrame(issues)


# ---------------------------------------------------------
# 4. MAIN RECONCILIATION ENGINE
# ---------------------------------------------------------

def reconcile_payments(
    data,
    gateway_fee_rate=0.02,
    tolerance=1.00
):
    """
    Reconcile successful gateway payments against
    bank settlement records.

    Matching is performed using normalized references.

    Multiple settlement rows with the same reference
    are treated as split settlements.
    """

    if not 0 <= gateway_fee_rate <= 1:
        raise ValueError(
            "Gateway fee rate must be between 0 and 1."
        )

    if tolerance < 0:
        raise ValueError(
            "Tolerance cannot be negative."
        )

    # Validate and clean input data
    frames, quality_issues = validate_data(data)

    orders = frames["orders"].copy()
    payments = frames["payments"].copy()
    refunds = frames["refunds"].copy()
    settlements = frames["settlements"].copy()

    # -----------------------------------------------------
    # 4.1 Normalize references and statuses
    # -----------------------------------------------------

    payments["normalized_ref"] = (
        payments["gateway_ref"].map(normalize_reference)
    )

    settlements["normalized_ref"] = (
        settlements["settlement_ref"].map(
            normalize_reference
        )
    )

    payments["payment_status"] = (
        payments["payment_status"]
        .astype(str)
        .str.upper()
        .str.strip()
    )

    refunds["refund_status"] = (
        refunds["refund_status"]
        .astype(str)
        .str.upper()
        .str.strip()
    )

    settlements["bank_status"] = (
        settlements["bank_status"]
        .astype(str)
        .str.upper()
        .str.strip()
    )

    # -----------------------------------------------------
    # 4.2 Separate successful and failed payment attempts
    # -----------------------------------------------------

    successful = payments[
        payments["payment_status"] == "SUCCESS"
    ].copy()

    failed = payments[
        payments["payment_status"] == "FAILED"
    ].copy()

    # Flag unknown payment statuses
    known_statuses = ["SUCCESS", "FAILED", "PENDING"]

    unknown_status = payments[
        ~payments["payment_status"].isin(known_statuses)
    ]

    if not unknown_status.empty:
        quality_issues = pd.concat([
            quality_issues,
            pd.DataFrame([{
                "dataset": "payments",
                "issue": "Unknown payment status",
                "count": len(unknown_status)
            }])
        ], ignore_index=True)

    # -----------------------------------------------------
    # 4.3 Process successful refunds
    # -----------------------------------------------------

    successful_refunds = refunds[
        refunds["refund_status"] == "SUCCESS"
    ].copy()

    refund_totals = (
        successful_refunds
        .groupby("payment_id")["refund_amount"]
        .sum()
    )

    successful["refund_amount"] = (
        successful["payment_id"]
        .map(refund_totals)
        .fillna(0.0)
    )

    # Detect refunds linked to unknown payments
    unknown_refunds = successful_refunds[
        ~successful_refunds["payment_id"].isin(
            payments["payment_id"]
        )
    ]

    if not unknown_refunds.empty:
        quality_issues = pd.concat([
            quality_issues,
            pd.DataFrame([{
                "dataset": "refunds",
                "issue": "Refund linked to unknown payment ID",
                "count": len(unknown_refunds)
            }])
        ], ignore_index=True)

    # Detect refunds greater than original payment
    excessive_refunds = successful[
        successful["refund_amount"] >
        successful["payment_amount"]
    ]

    if not excessive_refunds.empty:
        quality_issues = pd.concat([
            quality_issues,
            pd.DataFrame([{
                "dataset": "refunds",
                "issue": "Refund exceeds original payment amount",
                "count": len(excessive_refunds)
            }])
        ], ignore_index=True)

    # -----------------------------------------------------
    # 4.4 Calculate expected settlement
    # -----------------------------------------------------

    successful["expected_fee"] = (
        successful["payment_amount"]
        * gateway_fee_rate
    ).round(2)

    successful["expected_net"] = (
        successful["payment_amount"]
        - successful["expected_fee"]
        - successful["refund_amount"]
    ).round(2)

    # -----------------------------------------------------
    # 4.5 Detect multiple successful captures
    # -----------------------------------------------------

    multiple_captures = (
        successful.groupby("order_id")
        .filter(lambda group: len(group) > 1)
    )

    if not multiple_captures.empty:
        quality_issues = pd.concat([
            quality_issues,
            pd.DataFrame([{
                "dataset": "payments",
                "issue": "Multiple successful captures for one order",
                "count": multiple_captures[
                    "order_id"
                ].nunique()
            }])
        ], ignore_index=True)

    # -----------------------------------------------------
    # 4.6 Select credited bank settlements
    # -----------------------------------------------------

    credited = settlements[
        settlements["bank_status"] == "CREDITED"
    ].copy()

    pending_settlements = settlements[
        settlements["bank_status"] == "PENDING"
    ].copy()

    # -----------------------------------------------------
    # 4.7 Group settlements by normalized reference
    # -----------------------------------------------------

    # Supports split settlements
    bank_groups = {
        ref: group
        for ref, group in credited.groupby("normalized_ref")
        if ref
    }

    # Keep blank payment references so they are
    # classified as unmatched instead of silently omitted.
    payment_groups = {
        ref: group
        for ref, group in successful.groupby("normalized_ref")
    }

    # -----------------------------------------------------
    # 4.8 Match payments with bank settlements
    # -----------------------------------------------------

    transaction_results = []
    reference_results = []

    used_settlement_ids = set()

    for ref, group in payment_groups.items():

        expected_total = round(
            group["expected_net"].sum(),
            2
        )

        # Blank references cannot be matched
        bank_group = (
            bank_groups.get(ref)
            if ref
            else None
        )

        if bank_group is None:

            received_total = 0.0
            settlement_ids = ""
            status = "Unmatched"

        else:

            # Add all credits with this reference.
            # This handles split settlements.
            received_total = round(
                bank_group["net_amount"].sum(),
                2
            )

            settlement_ids = ", ".join(
                bank_group["settlement_id"].astype(str)
            )

            used_settlement_ids.update(
                bank_group["settlement_id"].astype(str)
            )

            reference_variance = round(
                received_total - expected_total,
                2
            )

            if abs(reference_variance) <= tolerance:
                status = "Matched"
            else:
                status = "Discrepant"

        reference_variance = round(
            received_total - expected_total,
            2
        )

        # Allocate received bank amount proportionally
        # to payment records sharing the same reference.
        payment_base = group["payment_amount"].sum()

        for _, payment in group.iterrows():

            if payment_base > 0:

                allocation = (
                    received_total
                    * payment["payment_amount"]
                    / payment_base
                )

            else:
                allocation = 0.0

            allocation = round(allocation, 2)

            transaction_results.append({

                "payment_id": payment["payment_id"],

                "order_id": payment["order_id"],

                "gateway_ref": payment["gateway_ref"],

                "normalized_ref": ref,

                "payment_amount": payment["payment_amount"],

                "refund_amount": payment["refund_amount"],

                "expected_fee": payment["expected_fee"],

                "expected_net": payment["expected_net"],

                "allocated_received_net": allocation,

                "settlement_ids": settlement_ids,

                "reference_expected_net": expected_total,

                "reference_received_net": received_total,

                "reference_variance": reference_variance,

                "status": status
            })

        reference_results.append({

            "normalized_ref": ref,

            "payment_count": len(group),

            "expected_net": expected_total,

            "received_net": received_total,

            "variance": reference_variance,

            "status": status
        })

    # -----------------------------------------------------
    # 4.9 Convert results into DataFrames
    # -----------------------------------------------------

    transaction_results = pd.DataFrame(
        transaction_results
    )

    reference_results = pd.DataFrame(
        reference_results
    )

    # -----------------------------------------------------
    # 4.10 Identify unmatched bank credits
    # -----------------------------------------------------

    matched_refs = set(payment_groups.keys())

    unmatched_bank = credited[
        (
            ~credited["normalized_ref"].isin(matched_refs)
        )
        | (
            credited["normalized_ref"] == ""
        )
    ].copy()

    # -----------------------------------------------------
    # 4.11 Identify orders without successful payments
    # -----------------------------------------------------

    orders_without_capture = orders[
        ~orders["order_id"].isin(
            successful["order_id"]
        )
    ].copy()

    # -----------------------------------------------------
    # 4.12 Calculate reconciliation metrics
    # -----------------------------------------------------

    if not reference_results.empty:

        total_refs = len(reference_results)

        matched_refs_count = int(
            (
                reference_results["status"] == "Matched"
            ).sum()
        )

        discrepant_refs_count = int(
            (
                reference_results["status"] == "Discrepant"
            ).sum()
        )

        unmatched_refs_count = int(
            (
                reference_results["status"] == "Unmatched"
            ).sum()
        )

        expected_total = round(
            reference_results["expected_net"].sum(),
            2
        )

    else:

        total_refs = 0
        matched_refs_count = 0
        discrepant_refs_count = 0
        unmatched_refs_count = 0
        expected_total = 0.0

    # All credited bank amounts, including unmatched credits
    received_total = round(
        credited["net_amount"].sum(),
        2
    )

    # Match rate is calculated by payment reference,
    # not by individual payment attempts.
    match_rate = (
        matched_refs_count / total_refs * 100
        if total_refs > 0
        else 0.0
    )

    total_refunded = round(
        successful_refunds["refund_amount"].sum(),
        2
    )

    total_expected_fees = round(
        successful["expected_fee"].sum(),
        2
    )

    # -----------------------------------------------------
    # 4.13 Summary
    # -----------------------------------------------------

    summary = {

        "total_orders": len(orders),

        "total_payment_attempts": len(payments),

        "successful_captures": len(successful),

        "failed_attempts": len(failed),

        "successful_refunds": len(successful_refunds),

        "total_refunded": total_refunded,

        "total_gateway_fees_expected": total_expected_fees,

        "total_payment_references": total_refs,

        "matched_references": matched_refs_count,

        "discrepant_references": discrepant_refs_count,

        "unmatched_references": unmatched_refs_count,

        "unmatched_bank_credits": len(unmatched_bank),

        "pending_settlements": len(pending_settlements),

        "orders_without_successful_payment": len(
            orders_without_capture
        ),

        "match_rate": round(match_rate, 2),

        "expected_net_settlement": expected_total,

        "actual_bank_credits": received_total,

        # Includes unmatched bank credits.
        # Review unmatched_bank separately when interpreting it.
        "overall_variance": round(
            received_total - expected_total,
            2
        ),

        "gateway_fee_rate": gateway_fee_rate,

        "tolerance": tolerance
    }

    # -----------------------------------------------------
    # 4.14 Return all reconciliation outputs
    # -----------------------------------------------------

    return {

        "transactions": transaction_results,

        "references": reference_results,

        "unmatched_bank": unmatched_bank,

        "orders_without_capture": orders_without_capture,

        "quality_issues": quality_issues,

        "pending_settlements": pending_settlements,

        "summary": summary
    }
