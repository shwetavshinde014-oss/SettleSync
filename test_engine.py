
from pathlib import Path
import pandas as pd

from src.reconciliation_engine import reconcile_payments


# Project data folder
DATA_DIR = Path(__file__).parent / "data"


# Load the four CSV files
data = {
    "orders": pd.read_csv(DATA_DIR / "orders.csv"),
    "payments": pd.read_csv(DATA_DIR / "payments.csv"),
    "refunds": pd.read_csv(DATA_DIR / "refunds.csv"),
    "settlements": pd.read_csv(DATA_DIR / "settlements.csv")
}


# Run reconciliation
result = reconcile_payments(
    data,
    gateway_fee_rate=0.02,
    tolerance=1.00
)


# Display summary
print("\n========== SETTLESYNC RECONCILIATION ==========")

print("\nSUMMARY")
for key, value in result["summary"].items():
    print(f"{key}: {value}")


# Display transaction results
print("\nTRANSACTION RESULTS")
print(result["transactions"].to_string(index=False))


# Display reference-level results
print("\nREFERENCE RESULTS")
print(result["references"].to_string(index=False))


# Display unmatched bank credits
print("\nUNMATCHED BANK CREDITS")
print(result["unmatched_bank"].to_string(index=False))


# Display data quality issues
print("\nDATA QUALITY ISSUES")
if result["quality_issues"].empty:
    print("No data quality issues found.")
else:
    print(result["quality_issues"].to_string(index=False))


print("\n========== TEST COMPLETED ==========")
