
"""
SettleSync - Report Generator

Generates downloadable Excel and PDF reconciliation reports.
"""

from io import BytesIO

import pandas as pd

from openpyxl.styles import (
    Font,
    PatternFill,
    Alignment
)
from openpyxl.utils import get_column_letter

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    PageBreak
)


# =========================================================
# 1. EXCEL REPORT GENERATOR
# =========================================================

def generate_excel_report(result, data):
    """
    Generate a multi-sheet Excel reconciliation report.
    Returns the Excel file as bytes.
    """

    output = BytesIO()

    summary = result["summary"]

    sheets = {
        "Summary": pd.DataFrame(
            list(summary.items()),
            columns=["Metric", "Value"]
        ),
        "Transactions": result["transactions"],
        "References": result["references"],
        "Unmatched Bank": result["unmatched_bank"],
        "Orders Without Payment": result["orders_without_capture"],
        "Data Quality": result["quality_issues"],
        "Pending Settlements": result["pending_settlements"],
        "Orders Source": data["orders"],
        "Payments Source": data["payments"],
        "Refunds Source": data["refunds"],
        "Settlements Source": data["settlements"]
    }

    with pd.ExcelWriter(
        output,
        engine="openpyxl"
    ) as writer:

        for sheet_name, dataframe in sheets.items():

            dataframe.to_excel(
                writer,
                sheet_name=sheet_name,
                index=False
            )

            worksheet = writer.sheets[sheet_name]

            # Style header
            for cell in worksheet[1]:

                cell.font = Font(
                    bold=True,
                    color="FFFFFF"
                )

                cell.fill = PatternFill(
                    start_color="14243A",
                    end_color="14243A",
                    fill_type="solid"
                )

                cell.alignment = Alignment(
                    horizontal="center"
                )

            # Style data cells
            for row in worksheet.iter_rows(min_row=2):

                for cell in row:

                    cell.font = Font(
                        color="26354A",
                        size=10
                    )

                    cell.alignment = Alignment(
                        vertical="center"
                    )

            # Automatically adjust column widths
            for column_cells in worksheet.columns:

                max_length = 0

                column_letter = get_column_letter(
                    column_cells[0].column
                )

                for cell in column_cells:

                    if cell.value is not None:
                        max_length = max(
                            max_length,
                            len(str(cell.value))
                        )

                worksheet.column_dimensions[
                    column_letter
                ].width = min(max_length + 4, 35)

            worksheet.freeze_panes = "A2"
            worksheet.auto_filter.ref = worksheet.dimensions

    output.seek(0)

    return output.getvalue()


# =========================================================
# 2. PDF REPORT GENERATOR
# =========================================================

def generate_pdf_report(result):
    """
    Generate a formatted PDF reconciliation report.
    Returns the PDF file as bytes.
    """

    output = BytesIO()

    document = SimpleDocTemplate(
        output,
        pagesize=landscape(A4),
        rightMargin=15 * mm,
        leftMargin=15 * mm,
        topMargin=15 * mm,
        bottomMargin=15 * mm
    )

    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        "ReportTitle",
        parent=styles["Title"],
        fontSize=22,
        leading=28,
        textColor=colors.HexColor("#14243A"),
        alignment=TA_CENTER,
        spaceAfter=8
    )

    subtitle_style = ParagraphStyle(
        "ReportSubtitle",
        parent=styles["Normal"],
        fontSize=10,
        textColor=colors.HexColor("#64748B"),
        alignment=TA_CENTER,
        spaceAfter=20
    )

    section_style = ParagraphStyle(
        "SectionHeading",
        parent=styles["Heading2"],
        fontSize=13,
        textColor=colors.HexColor("#14243A"),
        spaceBefore=14,
        spaceAfter=8
    )

    normal_style = styles["Normal"]

    story = []

    summary = result["summary"]

    # -----------------------------------------------------
    # REPORT TITLE
    # -----------------------------------------------------

    story.append(
        Paragraph("SettleSync", title_style)
    )

    story.append(
        Paragraph(
            "Digital Payment Settlement Reconciliation Report",
            subtitle_style
        )
    )

    story.append(
        Paragraph(
            "Financial reconciliation summary and exception analysis",
            normal_style
        )
    )

    story.append(Spacer(1, 12))

    # -----------------------------------------------------
    # SUMMARY TABLE
    # -----------------------------------------------------

    story.append(
        Paragraph(
            "1. Reconciliation Summary",
            section_style
        )
    )

    summary_rows = [
        ["Metric", "Value"]
    ]

    for key, value in summary.items():

        if isinstance(value, float):
            display_value = f"{value:,.2f}"
        else:
            display_value = str(value)

        summary_rows.append([
            str(key).replace("_", " ").title(),
            display_value
        ])

    summary_table = Table(
        summary_rows,
        colWidths=[100 * mm, 75 * mm],
        repeatRows=1
    )

    summary_table.setStyle(
        TableStyle([
            (
                "BACKGROUND",
                (0, 0),
                (-1, 0),
                colors.HexColor("#14243A")
            ),
            (
                "TEXTCOLOR",
                (0, 0),
                (-1, 0),
                colors.white
            ),
            (
                "FONTNAME",
                (0, 0),
                (-1, 0),
                "Helvetica-Bold"
            ),
            (
                "GRID",
                (0, 0),
                (-1, -1),
                0.4,
                colors.HexColor("#CBD5E1")
            ),
            (
                "ROWBACKGROUNDS",
                (0, 1),
                (-1, -1),
                [
                    colors.white,
                    colors.HexColor("#F1F5F9")
                ]
            ),
            (
                "FONTSIZE",
                (0, 0),
                (-1, -1),
                8
            ),
            (
                "PADDING",
                (0, 0),
                (-1, -1),
                6
            )
        ])
    )

    story.append(summary_table)

    # -----------------------------------------------------
    # REFERENCE RESULTS
    # -----------------------------------------------------

    story.append(
        Paragraph(
            "2. Reference-Level Reconciliation",
            section_style
        )
    )

    references = result["references"]

    if not references.empty:

        reference_data = [
            references.columns.tolist()
        ]

        for row in references.itertuples(
            index=False,
            name=None
        ):

            reference_data.append([
                str(value) for value in row
            ])

        reference_table = Table(
            reference_data,
            repeatRows=1
        )

        reference_table.setStyle(
            TableStyle([
                (
                    "BACKGROUND",
                    (0, 0),
                    (-1, 0),
                    colors.HexColor("#14243A")
                ),
                (
                    "TEXTCOLOR",
                    (0, 0),
                    (-1, 0),
                    colors.white
                ),
                (
                    "FONTNAME",
                    (0, 0),
                    (-1, 0),
                    "Helvetica-Bold"
                ),
                (
                    "GRID",
                    (0, 0),
                    (-1, -1),
                    0.4,
                    colors.HexColor("#CBD5E1")
                ),
                (
                    "FONTSIZE",
                    (0, 0),
                    (-1, -1),
                    7
                ),
                (
                    "ROWBACKGROUNDS",
                    (0, 1),
                    (-1, -1),
                    [
                        colors.white,
                        colors.HexColor("#F1F5F9")
                    ]
                ),
                (
                    "PADDING",
                    (0, 0),
                    (-1, -1),
                    5
                )
            ])
        )

        story.append(reference_table)

    else:

        story.append(
            Paragraph(
                "No payment references available.",
                normal_style
            )
        )

    # -----------------------------------------------------
    # EXCEPTION ANALYSIS
    # -----------------------------------------------------

    story.append(PageBreak())

    story.append(
        Paragraph(
            "3. Exception Analysis",
            section_style
        )
    )

    unmatched = result["unmatched_bank"]

    story.append(
        Paragraph(
            f"Unmatched bank credits: {len(unmatched)}",
            normal_style
        )
    )

    story.append(Spacer(1, 8))

    if not unmatched.empty:

        unmatched_data = [
            unmatched.columns.tolist()
        ]

        for row in unmatched.itertuples(
            index=False,
            name=None
        ):

            unmatched_data.append([
                str(value) for value in row
            ])

        unmatched_table = Table(
            unmatched_data,
            repeatRows=1
        )

        unmatched_table.setStyle(
            TableStyle([
                (
                    "BACKGROUND",
                    (0, 0),
                    (-1, 0),
                    colors.HexColor("#14243A")
                ),
                (
                    "TEXTCOLOR",
                    (0, 0),
                    (-1, 0),
                    colors.white
                ),
                (
                    "GRID",
                    (0, 0),
                    (-1, -1),
                    0.4,
                    colors.HexColor("#CBD5E1")
                ),
                (
                    "FONTSIZE",
                    (0, 0),
                    (-1, -1),
                    7
                ),
                (
                    "PADDING",
                    (0, 0),
                    (-1, -1),
                    5
                )
            ])
        )

        story.append(unmatched_table)

    else:

        story.append(
            Paragraph(
                "No unmatched bank credits found.",
                normal_style
            )
        )

    # -----------------------------------------------------
    # DATA QUALITY
    # -----------------------------------------------------

    story.append(
        Paragraph(
            "4. Data Quality Checks",
            section_style
        )
    )

    quality = result["quality_issues"]

    if quality.empty:

        story.append(
            Paragraph(
                "No data quality issues were detected.",
                normal_style
            )
        )

    else:

        quality_data = [
            quality.columns.tolist()
        ]

        for row in quality.itertuples(
            index=False,
            name=None
        ):

            quality_data.append([
                str(value) for value in row
            ])

        quality_table = Table(
            quality_data,
            repeatRows=1
        )

        quality_table.setStyle(
            TableStyle([
                (
                    "BACKGROUND",
                    (0, 0),
                    (-1, 0),
                    colors.HexColor("#14243A")
                ),
                (
                    "TEXTCOLOR",
                    (0, 0),
                    (-1, 0),
                    colors.white
                ),
                (
                    "GRID",
                    (0, 0),
                    (-1, -1),
                    0.4,
                    colors.HexColor("#CBD5E1")
                ),
                (
                    "FONTSIZE",
                    (0, 0),
                    (-1, -1),
                    8
                ),
                (
                    "PADDING",
                    (0, 0),
                    (-1, -1),
                    5
                )
            ])
        )

        story.append(quality_table)

    # -----------------------------------------------------
    # PENDING SETTLEMENTS
    # -----------------------------------------------------

    story.append(
        Paragraph(
            "5. Pending Settlements",
            section_style
        )
    )

    pending = result["pending_settlements"]

    story.append(
        Paragraph(
            f"Pending settlement records: {len(pending)}",
            normal_style
        )
    )

    # -----------------------------------------------------
    # REPORT FOOTER
    # -----------------------------------------------------

    story.append(Spacer(1, 25))

    story.append(
        Paragraph(
            "Generated by SettleSync | "
            "Digital Payment Settlement Reconciliation Platform",
            subtitle_style
        )
    )

    document.build(story)

    output.seek(0)

    return output.getvalue()
