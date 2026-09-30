"""Classification and ISO 26262-5 hardware architectural metrics.

Reference implementation, verified against the worked example in
examples/bjb/. PMHF here is the SPF + RF term only — a lower bound. The
dual-point term needs explicit DPF pair enumeration and is not modelled;
`GoalResult.pmhf_is_lower_bound` carries that fact into the report so the
caller cannot present it as complete by accident.

Everything flows from `classify_mode`. The per-goal totals and the per-row
report detail are two views of the same call, so the spreadsheet can never
disagree with the metric.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .models import Analysis, DCCombination, Element, ElementMode, Part


class FaultClass:
    SPF = "SPF"
    RF = "RF"
    MPF_L = "MPF,L"
    MPF_D = "MPF,D"
    SAFE = "Safe"


@dataclass
class Split:
    """Failure rate of one scope, split by ISO 26262-5 fault class (FIT)."""

    spf: float = 0.0
    rf: float = 0.0
    mpf_l: float = 0.0
    mpf_d: float = 0.0
    safe: float = 0.0

    @property
    def safety_related(self) -> float:
        return self.spf + self.rf + self.mpf_l + self.mpf_d

    @property
    def total(self) -> float:
        return self.safety_related + self.safe

    def __iadd__(self, other: Split) -> Split:
        self.spf += other.spf
        self.rf += other.rf
        self.mpf_l += other.mpf_l
        self.mpf_d += other.mpf_d
        self.safe += other.safe
        return self


@dataclass
class ModeRow:
    """One failure mode against one safety goal — the unit of the report."""

    element: str
    part: str
    mode: str
    effect: str
    lambda_element: float
    fraction: float
    lambda_mode: float
    fault_class: str
    mechanisms: list[str]
    dc_applied: float
    split: Split
    rationale: str


@dataclass
class GoalResult:
    goal: str
    asil: str
    totals: Split
    per_element: dict[str, Split] = field(default_factory=dict)
    rows: list[ModeRow] = field(default_factory=list)
    pmhf_is_lower_bound: bool = True

    @property
    def spfm(self) -> float:
        sr = self.totals.safety_related
        return 1.0 if sr == 0 else 1.0 - (self.totals.spf + self.totals.rf) / sr

    @property
    def lfm(self) -> float:
        den = self.totals.safety_related - self.totals.spf - self.totals.rf
        return 1.0 if den == 0 else 1.0 - self.totals.mpf_l / den

    @property
    def pmhf_fit(self) -> float:
        return self.totals.spf + self.totals.rf

    def residual_ranking(self) -> list[ModeRow]:
        return sorted(
            (r for r in self.rows if r.fault_class in (FaultClass.SPF, FaultClass.RF)),
            key=lambda r: r.split.spf + r.split.rf,
            reverse=True,
        )


def combine_dc(values: list[float], policy: DCCombination) -> float:
    """`max` is the claim most assessors accept without argument. `independent`
    assumes the mechanisms share no failure cause and needs a dependent-failure
    analysis behind it (ISO 26262-9 Clause 7); validate_analysis enforces that
    an assumption records the argument."""
    if not values:
        return 0.0
    if policy is DCCombination.MAX:
        return max(values)
    residual = 1.0
    for v in values:
        residual *= 1.0 - v
    return 1.0 - residual


def classify_mode(
    analysis: Analysis,
    element: Element,
    part: Part,
    mode_name: str,
    mode: ElementMode,
    goal_id: str,
) -> ModeRow:
    """Classify one failure mode against one goal, with the rationale that put
    it in that class. The rationale is the report's comment column — it is
    generated from the classification, so it can never drift away from the
    number beside it."""
    lambda_element = part.lambda_fit * element.quantity
    fraction = part.failure_modes[mode_name].fraction
    lam = lambda_element * fraction
    goal = analysis.safety_goals[goal_id]
    split = Split()

    # Only mechanisms scoped to THIS goal count. One listed on the mode but
    # scoped elsewhere contributes nothing, which correctly leaves the mode a
    # single-point fault here.
    named = [analysis.mechanisms[m] for m in mode.mechanisms if m in analysis.mechanisms]
    scoped = [m for m in named if goal_id in m.covers_goals]
    out_of_scope = [
        mid
        for mid, m in zip(mode.mechanisms, named, strict=False)
        if goal_id not in m.covers_goals
    ]

    if goal_id in mode.violates:
        if not scoped:
            split.spf = lam
            if out_of_scope:
                rationale = (
                    f"Single-point fault. The effect '{mode.effect}' violates {goal_id} "
                    f"({goal.statement}). Mechanism(s) {', '.join(out_of_scope)} are "
                    f"listed but scoped to other goals, so no coverage applies here."
                )
            else:
                rationale = (
                    f"Single-point fault. The effect '{mode.effect}' violates {goal_id} "
                    f"({goal.statement}) and no safety mechanism is claimed against it."
                )
            return ModeRow(
                element.id, element.part, mode_name, mode.effect or "", lambda_element,
                fraction, lam, FaultClass.SPF, list(mode.mechanisms), 0.0, split, rationale,
            )

        dc = combine_dc([m.dc_spf for m in scoped], analysis.dc_combination)
        split.rf = lam * (1.0 - dc)
        split.mpf_d = lam * dc
        names = ", ".join(m.name for m in scoped)
        rationale = (
            f"Residual fault. The effect '{mode.effect}' violates {goal_id}; "
            f"{names} claims {dc:.1%} coverage "
            f"({analysis.dc_combination.value} combination), leaving "
            f"{lam * (1 - dc):.3f} FIT uncovered."
        )
        return ModeRow(
            element.id, element.part, mode_name, mode.effect or "", lambda_element,
            fraction, lam, FaultClass.RF, list(mode.mechanisms), dc, split, rationale,
        )

    if goal_id in mode.latent_for:
        dc = combine_dc([m.dc_lf for m in scoped], analysis.dc_combination)
        split.mpf_l = lam * (1.0 - dc)
        split.mpf_d = lam * dc
        detector = ", ".join(m.name for m in scoped) or "nothing"
        rationale = (
            f"Latent multiple-point fault. Does not violate {goal_id} alone, but "
            f"'{mode.effect}' disables or degrades a diagnostic. Detected by "
            f"{detector} at {dc:.1%}; {lam * (1 - dc):.3f} FIT remains latent."
        )
        return ModeRow(
            element.id, element.part, mode_name, mode.effect or "", lambda_element,
            fraction, lam, FaultClass.MPF_L, list(mode.mechanisms), dc, split, rationale,
        )

    split.safe = lam
    rationale = (
        f"Safe fault with respect to {goal_id}. '{mode.effect}' neither violates the "
        f"goal nor disables a diagnostic that protects it."
    )
    return ModeRow(
        element.id, element.part, mode_name, mode.effect or "", lambda_element,
        fraction, lam, FaultClass.SAFE, list(mode.mechanisms), 0.0, split, rationale,
    )


def compute(analysis: Analysis, parts: dict[str, Part]) -> dict[str, GoalResult]:
    results: dict[str, GoalResult] = {}
    for goal_id, goal in analysis.safety_goals.items():
        result = GoalResult(goal=goal_id, asil=goal.asil.value, totals=Split())
        for element in analysis.elements:
            part = parts[element.part]
            element_split = Split()
            for mode_name, mode in element.modes.items():
                row = classify_mode(analysis, element, part, mode_name, mode, goal_id)
                result.rows.append(row)
                element_split += row.split
            result.per_element[element.id] = element_split
            result.totals += element_split
        results[goal_id] = result
    return results
