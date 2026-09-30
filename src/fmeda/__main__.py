"""Command line interface.

    python -m fmeda check   examples/bjb/fmeda.yaml
    python -m fmeda compute examples/bjb/fmeda.yaml
    python -m fmeda compute examples/bjb/fmeda.yaml --goal SG1 --level conservative
    python -m fmeda compute examples/bjb/fmeda.yaml --json
    python -m fmeda report  examples/bjb/fmeda.yaml -o out.xlsx

The --json output exists so metrics can be diffed in CI and a regression on
SPFM can fail a pull request. That is the whole point of keeping the analysis
in text files.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import sys
from pathlib import Path

from . import policy as P
from .metrics import compute
from .models import load_analysis, validate_analysis

# The table output uses box-drawing characters and the lambda sign. A Windows
# console on a legacy codepage (cp949, cp1252) cannot encode those and would
# raise UnicodeEncodeError mid-table. Degrade the glyphs, keep the numbers.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        with contextlib.suppress(ValueError, OSError):
            _stream.reconfigure(encoding="utf-8", errors="replace")

RULE = "─" * 69


def _print_goal(goal_id, result, analysis, level) -> bool:
    goal = analysis.safety_goals[goal_id]
    target = analysis.target_for(goal.asil)

    print(f"\n  {goal_id} · ASIL {goal.asil.value} · FTTI {goal.ftti_ms} ms"
          f"{'':>8}dc_combination: {analysis.dc_combination.value}")
    if level is not P.Level.NOMINAL:
        print(f"  conservatism: {level.label}")
    print(f"  {RULE}")
    print(f"  {'Element':<9}{'λ (FIT)':>9}{'λ_SPF':>8}{'λ_RF':>8}"
          f"{'λ_MPF,L':>10}{'λ_MPF,D':>10}{'λ_S':>8}")
    for element_id, split in result.per_element.items():
        print(f"  {element_id:<9}{split.total:>9.1f}{split.spf:>8.2f}{split.rf:>8.2f}"
              f"{split.mpf_l:>10.2f}{split.mpf_d:>10.2f}{split.safe:>8.2f}")
    print(f"  {RULE}")
    print(f"  λ_safety_related  {result.totals.safety_related:.2f} FIT"
          f"        λ_total  {result.totals.total:.2f} FIT\n")

    spfm_ok = result.spfm >= target.spfm
    lfm_ok = result.lfm >= target.lfm
    print(f"  SPFM  {result.spfm:7.2%}  (target {target.spfm:.2%})   "
          f"{'PASS' if spfm_ok else 'FAIL'}")
    print(f"  LFM   {result.lfm:7.2%}  (target {target.lfm:.2%})   "
          f"{'PASS' if lfm_ok else 'FAIL'}")
    print(f"  PMHF  {result.pmhf_fit:7.2f} FIT lower bound — dual-point term not modelled")

    ranked = result.residual_ranking()[:3]
    if ranked:
        print("\n  Top SPFM contributors")
        for i, row in enumerate(ranked, start=1):
            mechs = ", ".join(row.mechanisms) or "none"
            print(f"    {i}. {row.element:<4}{row.mode:<18}"
                  f"{row.split.spf + row.split.rf:5.2f} FIT   "
                  f"dc_spf {row.dc_applied:.2f}   {mechs}")
    return spfm_ok and lfm_ok


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="fmeda", description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)

    for name, help_text in [
        ("check", "validate an analysis without computing metrics"),
        ("compute", "validate and compute hardware architectural metrics"),
        ("report", "generate the Excel report"),
    ]:
        p = sub.add_parser(name, help=help_text)
        p.add_argument("analysis", type=Path)
        p.add_argument("--level", choices=[lv.value for lv in P.Level], default="nominal",
                       help="conservatism policy (default: nominal)")
        if name != "check":
            p.add_argument("--goal", help="restrict output to one safety goal")
        if name == "compute":
            p.add_argument("--json", action="store_true", help="machine-readable output")
        if name == "report":
            p.add_argument("-o", "--output", type=Path, default=Path("fmeda-report.xlsx"))

    args = parser.parse_args(argv)

    try:
        analysis, parts = load_analysis(args.analysis)
    except Exception as exc:  # noqa: BLE001 — a bad input file is a user error
        print(f"could not load {args.analysis}: {exc}", file=sys.stderr)
        return 2

    problems = validate_analysis(analysis, parts)
    errors = [p for p in problems if p.startswith("error:")]
    for problem in problems:
        print(f"  {problem}", file=sys.stderr)
    if errors:
        print(f"\n{len(errors)} error(s) — not computing metrics.", file=sys.stderr)
        return 1
    if args.command == "check":
        print("  validation clean" if not problems else "\n  validation passed with warnings")
        return 0

    level = P.Level(args.level)
    applied = P.apply(analysis, parts, level)
    results = compute(applied.analysis, parts)
    if args.goal:
        if args.goal not in results:
            print(f"unknown goal '{args.goal}'", file=sys.stderr)
            return 2
        results = {args.goal: results[args.goal]}

    if args.command == "report":
        from .report import write_report

        out = write_report(
            args.output, analysis, parts, applied, results,
            uploads=[{"category": "analysis", "name": str(args.analysis), "digest": ""}],
            present=set(P.DocCategory), failure_rate_source="as stated in library",
            temp_profile="as stated in mission profile",
        )
        print(f"  wrote {out}")
        return 0

    if getattr(args, "json", False):
        print(json.dumps({
            goal_id: {
                "asil": r.asil, "spfm": r.spfm, "lfm": r.lfm,
                "pmhf_fit_lower_bound": r.pmhf_fit,
                "lambda_safety_related_fit": r.totals.safety_related,
                "lambda_total_fit": r.totals.total,
                "conservatism": level.value,
            } for goal_id, r in results.items()
        }, indent=2))
        return 0

    all_met = True
    for goal_id, result in results.items():
        all_met &= _print_goal(goal_id, result, applied.analysis, level)
    if applied.review_queue:
        print(f"\n  {len(applied.review_queue)} item(s) need analyst resolution:")
        for item in applied.review_queue:
            print(f"    · {item}")
    print()
    return 0 if all_met else 3


if __name__ == "__main__":
    raise SystemExit(main())
