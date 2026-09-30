"""XLSX report writer.

One sheet per safety goal, because that is the unit the argument is made in.
The metric cells are live Excel formulas over the rows beneath them, not values
computed in Python and pasted — so an engineer can change a diagnostic coverage
in the sheet and watch SPFM move, which is how these documents actually get
used in a design review.

Provenance is a first-class sheet. An FMEDA that cannot say which documents,
which failure-rate source and which conservatism level produced it is not
reviewable, and that is the sheet an assessor opens first.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from openpyxl import Workbook
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from .metrics import FaultClass, GoalResult
from .models import Analysis, Part
from .policy import MISSING_DOC_EFFECT, DocCategory, PolicyResult

FONT = "Arial"
INK = Font(name=FONT, size=10)
BOLD = Font(name=FONT, size=10, bold=True)
TITLE = Font(name=FONT, size=13, bold=True)
HEAD = Font(name=FONT, size=10, bold=True, color="FFFFFF")

HEAD_FILL = PatternFill("solid", fgColor="1F3A40")
PASS_FILL = PatternFill("solid", fgColor="DDEEDD")
FAIL_FILL = PatternFill("solid", fgColor="F6DDDA")
NOTE_FILL = PatternFill("solid", fgColor="F4F1E4")

THIN = Side(style="thin", color="C8D2D0")
BOX = Border(bottom=THIN)

FIT = "0.000"
PCT = "0.00%"

GOAL_COLUMNS = [
    ("Element", 11), ("Part", 20), ("Failure mode", 20), ("Effect", 40),
    ("λ element (FIT)", 14), ("Mode fraction", 13), ("λ mode (FIT)", 13),
    ("Class", 9), ("Safety mechanism", 26), ("DC applied", 11),
    ("λ_SPF", 10), ("λ_RF", 10), ("λ_MPF,L", 11), ("λ_MPF,D", 11), ("λ_S", 10),
    ("Rationale", 80),
]


def _header(ws, row: int, columns) -> None:
    for i, (name, width) in enumerate(columns, start=1):
        cell = ws.cell(row=row, column=i, value=name)
        cell.font = HEAD
        cell.fill = HEAD_FILL
        cell.alignment = Alignment(vertical="center", wrap_text=True)
        ws.column_dimensions[get_column_letter(i)].width = width
    ws.freeze_panes = ws.cell(row=row + 1, column=1)


def _goal_sheet(wb: Workbook, result: GoalResult, analysis: Analysis) -> tuple[str, int]:
    """Write one goal's full FMEDA. Returns (sheet name, totals row)."""
    goal = analysis.safety_goals[result.goal]
    ws = wb.create_sheet(result.goal)

    ws["A1"] = f"{result.goal} — ASIL {result.asil}"
    ws["A1"].font = TITLE
    ws["A2"] = goal.statement
    ws["A2"].font = INK
    ws["A3"] = (
        f"FTTI {goal.ftti_ms} ms · safe state: {goal.safe_state} · "
        f"DC combination: {analysis.dc_combination.value}"
    )
    ws["A3"].font = Font(name=FONT, size=9, italic=True)

    head_row = 5
    _header(ws, head_row, GOAL_COLUMNS)

    row = head_row + 1
    for r in sorted(result.rows, key=lambda x: (x.element, x.mode)):
        values = [
            r.element, r.part, r.mode, r.effect,
            r.lambda_element, r.fraction, r.lambda_mode,
            r.fault_class, ", ".join(r.mechanisms) or "—", r.dc_applied,
            r.split.spf, r.split.rf, r.split.mpf_l, r.split.mpf_d, r.split.safe,
            r.rationale,
        ]
        for col, value in enumerate(values, start=1):
            cell = ws.cell(row=row, column=col, value=value)
            cell.font = INK
            cell.border = BOX
            if col in (5, 7, 11, 12, 13, 14, 15):
                cell.number_format = FIT
            if col in (6, 10):
                cell.number_format = PCT
            if col == 16:
                cell.alignment = Alignment(wrap_text=True, vertical="top")
        if r.fault_class in (FaultClass.SPF, FaultClass.RF):
            for col in range(1, 17):
                ws.cell(row=row, column=col).fill = FAIL_FILL
        row += 1

    first, last = head_row + 1, row - 1
    totals = row
    ws.cell(row=totals, column=1, value="TOTAL").font = BOLD
    for col in (7, 11, 12, 13, 14, 15):
        letter = get_column_letter(col)
        cell = ws.cell(row=totals, column=col, value=f"=SUM({letter}{first}:{letter}{last})")
        cell.font = BOLD
        cell.number_format = FIT

    # Metrics computed in-sheet, so editing a DC above moves them.
    m = totals + 2
    sr = f"(K{totals}+L{totals}+M{totals}+N{totals})"
    target = analysis.target_for(goal.asil)

    ws.cell(row=m, column=1, value="λ safety-related (FIT)").font = BOLD
    ws.cell(row=m, column=5, value=f"={sr}").number_format = FIT
    ws.cell(row=m + 1, column=1, value="SPFM").font = BOLD
    ws.cell(row=m + 1, column=5, value=f"=1-(K{totals}+L{totals})/{sr}").number_format = PCT
    ws.cell(row=m + 1, column=6, value=target.spfm).number_format = PCT
    ws.cell(row=m + 2, column=1, value="LFM").font = BOLD
    ws.cell(
        row=m + 2, column=5,
        value=f"=IF(({sr}-K{totals}-L{totals})=0,1,1-M{totals}/({sr}-K{totals}-L{totals}))",
    ).number_format = PCT
    ws.cell(row=m + 2, column=6, value=target.lfm).number_format = PCT
    ws.cell(row=m + 3, column=1, value="PMHF (FIT)").font = BOLD
    ws.cell(row=m + 3, column=5, value=f"=K{totals}+L{totals}").number_format = FIT
    ws.cell(row=m + 3, column=6, value=target.pmhf_fit).number_format = FIT

    for r_ in range(m, m + 4):
        ws.cell(row=r_, column=5).font = BOLD
        ws.cell(row=r_, column=6).font = INK
    ws.cell(row=m + 1, column=6).comment = Comment(
        "Target from ISO 26262-5:2018 Table 4 unless overridden in the analysis. "
        "The table is informative; confirm against your own copy.", "fmeda-toolkit",
    )
    ws.cell(row=m + 3, column=5).comment = Comment(
        "LOWER BOUND. Single-point and residual terms only. The dual-point "
        "failure term is not modelled in this version.", "fmeda-toolkit",
    )
    ws.cell(row=m + 3, column=1).fill = NOTE_FILL

    return result.goal, m


def _summary(wb: Workbook, results: dict[str, GoalResult], analysis: Analysis,
             metric_rows: dict[str, int], policy: PolicyResult) -> None:
    ws = wb.create_sheet("Summary", 0)
    ws["A1"] = f"FMEDA — {analysis.meta.item}"
    ws["A1"].font = TITLE
    ws["A2"] = (
        f"{analysis.meta.variant or ''} · conservatism: {policy.level.label} · "
        f"generated {datetime.now():%Y-%m-%d %H:%M}"
    )
    ws["A2"].font = Font(name=FONT, size=9, italic=True)

    cols = [("Safety goal", 12), ("ASIL", 7), ("SPFM", 10), ("target", 10),
            ("LFM", 10), ("target", 10), ("PMHF (FIT)", 12), ("target", 10),
            ("Verdict", 12)]
    _header(ws, 4, cols)

    row = 5
    for goal_id, result in results.items():
        m = metric_rows[goal_id]
        target = analysis.target_for(analysis.safety_goals[goal_id].asil)
        ws.cell(row=row, column=1, value=goal_id).font = BOLD
        ws.cell(row=row, column=2, value=result.asil).font = INK
        ws.cell(row=row, column=3, value=f"='{goal_id}'!E{m + 1}").number_format = PCT
        ws.cell(row=row, column=4, value=target.spfm).number_format = PCT
        ws.cell(row=row, column=5, value=f"='{goal_id}'!E{m + 2}").number_format = PCT
        ws.cell(row=row, column=6, value=target.lfm).number_format = PCT
        ws.cell(row=row, column=7, value=f"='{goal_id}'!E{m + 3}").number_format = FIT
        ws.cell(row=row, column=8, value=target.pmhf_fit).number_format = FIT
        ws.cell(
            row=row, column=9,
            value=f'=IF(AND(C{row}>=D{row},E{row}>=F{row},G{row}<=H{row}),"MET","NOT MET")',
        ).font = BOLD
        ws.cell(row=row, column=9).fill = (
            PASS_FILL if result.spfm >= target.spfm and result.lfm >= target.lfm else FAIL_FILL
        )
        for col in range(1, 10):
            ws.cell(row=row, column=col).border = BOX
        row += 1

    note = row + 2
    ws.cell(row=note, column=1, value="Read this before quoting any figure above").font = BOLD
    for i, line in enumerate(
        [
            "PMHF is a LOWER BOUND — single-point and residual terms only. The dual-point "
            "failure term is not modelled in this version.",
            f"Conservatism level '{policy.level.label}' applied "
            f"{len(policy.actions)} derating actions. See the Policy sheet for every one.",
            "The conservatism level is a set of deterministic derating rules, not a "
            "statistical confidence interval. It does not mean the result is 60/90/99% likely.",
            f"{len(policy.review_queue)} item(s) need analyst resolution. See Review queue.",
            "Machine-generated classifications are proposals. No row here is a released "
            "FMEDA until an analyst has ratified it.",
        ],
        start=1,
    ):
        cell = ws.cell(row=note + i, column=1, value=f"• {line}")
        cell.font = INK
        cell.alignment = Alignment(wrap_text=True, vertical="top")
        ws.merge_cells(start_row=note + i, start_column=1, end_row=note + i, end_column=9)
        ws.row_dimensions[note + i].height = 26
        cell.fill = NOTE_FILL


def _mechanisms(wb: Workbook, original: Analysis, policy: PolicyResult) -> None:
    ws = wb.create_sheet("Mechanisms")
    ws["A1"] = "Safety mechanism register"
    ws["A1"].font = TITLE
    cols = [("ID", 16), ("Name", 34), ("DC_SPF stated", 13), ("DC_SPF applied", 14),
            ("DC_LF stated", 13), ("DC_LF applied", 14), ("Reaction (ms)", 13),
            ("Goals", 14), ("Evidence", 16), ("Reference", 30), ("Rationale", 50)]
    _header(ws, 3, cols)
    row = 4
    for mid, mech in original.mechanisms.items():
        applied = policy.analysis.mechanisms[mid]
        ev = mech.evidence
        for col, value in enumerate(
            [mid, mech.name, mech.dc_spf, applied.dc_spf, mech.dc_lf, applied.dc_lf,
             mech.reaction_time_ms, ", ".join(mech.covers_goals),
             ev.confidence.value if ev else "estimated",
             ev.reference if ev else "", ev.rationale if ev else ""],
            start=1,
        ):
            cell = ws.cell(row=row, column=col, value=value)
            cell.font = INK
            cell.border = BOX
            if col in (3, 4, 5, 6):
                cell.number_format = PCT
            if col == 11:
                cell.alignment = Alignment(wrap_text=True, vertical="top")
        if applied.dc_spf != mech.dc_spf:
            ws.cell(row=row, column=4).fill = FAIL_FILL
        row += 1


def _policy_sheet(wb: Workbook, policy: PolicyResult, present: set[DocCategory]) -> None:
    ws = wb.create_sheet("Policy")
    ws["A1"] = f"Conservatism policy — {policy.level.label}"
    ws["A1"].font = TITLE
    ws["A2"] = policy.level.blurb
    ws["A2"].font = INK
    ws["A2"].alignment = Alignment(wrap_text=True, vertical="top")
    ws.merge_cells("A2:E2")
    ws.row_dimensions[2].height = 30
    ws["A3"] = (
        "These are deterministic derating rules. The same inputs at the same level always "
        "produce the same numbers. The level is not a probability."
    )
    ws["A3"].font = Font(name=FONT, size=9, italic=True)

    _header(ws, 5, [("Target", 24), ("Field", 16), ("Before", 12), ("After", 12),
                    ("Reason", 70)])
    row = 6
    for action in policy.actions:
        for col, value in enumerate(
            [action.target, action.field_name, action.before, action.after, action.reason],
            start=1,
        ):
            cell = ws.cell(row=row, column=col, value=value)
            cell.font = INK
            cell.border = BOX
            if col == 5:
                cell.alignment = Alignment(wrap_text=True, vertical="top")
        row += 1
    if not policy.actions:
        ws.cell(row=6, column=1, value="No derating applied at this level.").font = INK


def _review_queue(wb: Workbook, policy: PolicyResult) -> None:
    ws = wb.create_sheet("Review queue")
    ws["A1"] = "Open items for the analyst"
    ws["A1"].font = TITLE
    ws["A2"] = (
        "Each line is something the tool could not decide. Until these are resolved the "
        "analysis is a draft, whatever the metrics say."
    )
    ws["A2"].font = Font(name=FONT, size=9, italic=True)
    _header(ws, 4, [("#", 5), ("Item", 100), ("Resolved by", 20), ("Date", 14)])
    for i, item in enumerate(policy.review_queue, start=1):
        ws.cell(row=4 + i, column=1, value=i).font = INK
        cell = ws.cell(row=4 + i, column=2, value=item)
        cell.font = INK
        cell.alignment = Alignment(wrap_text=True, vertical="top")
        for col in (3, 4):
            ws.cell(row=4 + i, column=col).fill = NOTE_FILL


def _inputs(wb: Workbook, analysis: Analysis, policy: PolicyResult,
            uploads: list[dict], present: set[DocCategory], failure_rate_source: str,
            temp_profile: str) -> None:
    ws = wb.create_sheet("Inputs")
    ws["A1"] = "Provenance"
    ws["A1"].font = TITLE
    ws["A2"] = "What went in, so this run can be reproduced and challenged."
    ws["A2"].font = Font(name=FONT, size=9, italic=True)

    row = 4
    for label, value in [
        ("Item", analysis.meta.item),
        ("Variant", analysis.meta.variant or "—"),
        ("Analyst", analysis.meta.analyst or "—"),
        ("Generated", f"{datetime.now():%Y-%m-%d %H:%M}"),
        ("Failure rate source", failure_rate_source),
        ("Temperature profile", temp_profile),
        ("Mission lifetime (h)", analysis.mission_profile.lifetime_h),
        ("Conservatism level", policy.level.label),
        ("DC combination", analysis.dc_combination.value),
    ]:
        ws.cell(row=row, column=1, value=label).font = BOLD
        ws.cell(row=row, column=2, value=value).font = INK
        row += 1
    ws.column_dimensions["A"].width = 24
    ws.column_dimensions["B"].width = 46
    ws.column_dimensions["C"].width = 60

    row += 1
    ws.cell(row=row, column=1, value="Documents provided").font = BOLD
    row += 1
    _header(ws, row, [("Category", 22), ("File", 40), ("SHA-256 (first 16)", 22)])
    row += 1
    for upload in uploads:
        for col, value in enumerate(
            [upload["category"], upload["name"], upload["digest"][:16]], start=1
        ):
            ws.cell(row=row, column=col, value=value).font = INK
        row += 1

    missing = set(MISSING_DOC_EFFECT) - present
    if missing:
        row += 1
        ws.cell(row=row, column=1, value="Documents NOT provided, and what it cost").font = BOLD
        row += 1
        for category in sorted(missing, key=lambda c: c.value):
            ws.cell(row=row, column=1, value=category.value).font = INK
            cell = ws.cell(row=row, column=2, value=MISSING_DOC_EFFECT[category])
            cell.font = INK
            cell.alignment = Alignment(wrap_text=True, vertical="top")
            ws.merge_cells(start_row=row, start_column=2, end_row=row, end_column=3)
            ws.row_dimensions[row].height = 28
            cell.fill = NOTE_FILL
            row += 1


def _assumptions(wb: Workbook, analysis: Analysis) -> None:
    ws = wb.create_sheet("Assumptions")
    ws["A1"] = "Assumption register"
    ws["A1"].font = TITLE
    _header(ws, 3, [("ID", 8), ("Statement", 90), ("Status", 12), ("Owner", 20)])
    for i, (aid, a) in enumerate(analysis.assumptions.items(), start=4):
        ws.cell(row=i, column=1, value=aid).font = BOLD
        cell = ws.cell(row=i, column=2, value=a.statement)
        cell.font = INK
        cell.alignment = Alignment(wrap_text=True, vertical="top")
        ws.cell(row=i, column=3, value=a.status).font = INK
        ws.cell(row=i, column=4, value=a.owner or "—").font = INK


def write_report(
    path: str | Path,
    original: Analysis,
    parts: dict[str, Part],
    policy: PolicyResult,
    results: dict[str, GoalResult],
    uploads: list[dict],
    present: set[DocCategory],
    failure_rate_source: str,
    temp_profile: str,
) -> Path:
    wb = Workbook()
    wb.remove(wb.active)

    metric_rows: dict[str, int] = {}
    for goal_id, result in results.items():
        _, m = _goal_sheet(wb, result, policy.analysis)
        metric_rows[goal_id] = m

    _summary(wb, results, policy.analysis, metric_rows, policy)
    _mechanisms(wb, original, policy)
    _policy_sheet(wb, policy, present)
    _review_queue(wb, policy)
    _assumptions(wb, policy.analysis)
    _inputs(wb, policy.analysis, policy, uploads, present, failure_rate_source, temp_profile)

    path = Path(path)
    wb.save(path)
    return path
