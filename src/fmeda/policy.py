"""Conservatism policy — how the analysis treats what it does not know.

This is the layer behind the dashboard's 60 / 90 / 99 selector. It is a set of
DETERMINISTIC DERATING RULES, not a statistical confidence interval and not a
model temperature. The same inputs at the same level always produce the same
numbers, and every change the policy makes is recorded as a PolicyAction so the
report can show its work.

Say this plainly wherever the level is displayed. "99% confident" is a claim
nobody can support and an assessor will take apart; "worst-case treatment of
unverified coverage" is a claim you can defend line by line.

The policy also connects document completeness to the arithmetic: coverage
evidence is only as good as the document that backs it. Run without the
supplier safety manual and every supplier_claim drops a tier, which is what
makes "more reference documents give a more precise analysis" a true statement
about this tool rather than a marketing line.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from enum import Enum

from .models import Analysis, Confidence, Part


class Level(str, Enum):
    NOMINAL = "nominal"
    CONSERVATIVE = "conservative"
    WORST_CASE = "worst_case"

    @property
    def label(self) -> str:
        return {
            Level.NOMINAL: "60 · Nominal",
            Level.CONSERVATIVE: "90 · Conservative",
            Level.WORST_CASE: "99 · Worst case",
        }[self]

    @property
    def blurb(self) -> str:
        return {
            Level.NOMINAL: (
                "Coverage claims accepted as stated. Failure modes the analysis "
                "did not classify are treated as safe. Use for early design "
                "iteration, not for a release argument."
            ),
            Level.CONSERVATIVE: (
                "Coverage derated by strength of evidence. Unclassified failure "
                "modes treated as latent. The default for a working analysis."
            ),
            Level.WORST_CASE: (
                "Only coverage you can independently evidence survives; supplier "
                "claims you have not verified go to zero. Unclassified modes "
                "become single-point faults. Use to bound the argument."
            ),
        }[self]


# Evidence strength, highest first. The tier is what the policy derates against.
EVIDENCE_TIER: dict[Confidence, int] = {
    Confidence.MEASURED: 4,
    Confidence.FIELD_DATA: 4,
    Confidence.STANDARD: 3,
    Confidence.SUPPLIER_CLAIM: 2,
    Confidence.ESTIMATED: 1,
    Confidence.EXPERT_JUDGEMENT: 1,
}

# Multiplier applied to a mechanism's dc_spf and dc_lf, by evidence tier.
DERATING: dict[Level, dict[int, float]] = {
    Level.NOMINAL: {4: 1.00, 3: 1.00, 2: 1.00, 1: 1.00},
    Level.CONSERVATIVE: {4: 1.00, 3: 0.95, 2: 0.90, 1: 0.60},
    Level.WORST_CASE: {4: 1.00, 3: 0.90, 2: 0.00, 1: 0.00},
}


class DocCategory(str, Enum):
    SCHEMATIC = "schematic"            # netlist + BOM
    TEMP_PROFILE = "temp_profile"
    COMPONENT_DATA = "component_data"  # IEC 61709 / SN 29500 / IEC 62380 (legacy)
    SAFETY_MANUAL = "safety_manual"
    SAFETY_CONCEPT = "safety_concept"
    DESIGN_DOC = "design_doc"
    HARA = "hara"


REQUIRED = {DocCategory.SCHEMATIC, DocCategory.TEMP_PROFILE, DocCategory.COMPONENT_DATA}

# What a missing document costs you, in the tool's own words. Shown in the
# completeness gate and again on the report's Inputs sheet.
MISSING_DOC_EFFECT: dict[DocCategory, str] = {
    DocCategory.SAFETY_MANUAL: (
        "Supplier diagnostic coverage claims drop one evidence tier — the "
        "document that would substantiate them is not present."
    ),
    DocCategory.SAFETY_CONCEPT: (
        "Safety goals, ASIL and FTTI cannot be confirmed against source. "
        "Goal definitions are taken on trust and flagged in the report."
    ),
    DocCategory.DESIGN_DOC: (
        "Failure effects cannot be traced to circuit function. Effect "
        "reasoning is weaker and more rows land in the review queue."
    ),
    DocCategory.HARA: (
        "ASIL assignment per goal cannot be independently checked."
    ),
}


@dataclass
class PolicyAction:
    """One change the policy made, and why. Every row of the report that the
    policy touched can point at one of these."""

    target: str
    field_name: str
    before: float | str
    after: float | str
    reason: str


@dataclass
class PolicyResult:
    analysis: Analysis
    level: Level
    actions: list[PolicyAction] = field(default_factory=list)
    review_queue: list[str] = field(default_factory=list)


def missing_documents(present: set[DocCategory]) -> tuple[set[DocCategory], set[DocCategory]]:
    """Returns (blocking, advisory). Blocking documents stop the run; advisory
    ones only degrade the result."""
    blocking = REQUIRED - present
    advisory = set(MISSING_DOC_EFFECT) - present
    return blocking, advisory


def apply(
    analysis: Analysis,
    parts: dict[str, Part],
    level: Level,
    present_docs: set[DocCategory] | None = None,
) -> PolicyResult:
    """Return a copy of the analysis with the policy applied. The original is
    never mutated — the unmodified analysis stays available so the report can
    show nominal and policy-applied results side by side."""
    # `or` would be wrong here: an empty set is falsy, so "no documents at all"
    # would silently become "every document present" and quietly credit
    # coverage the evidence does not support. Only None means "not specified".
    present_docs = set(DocCategory) if present_docs is None else present_docs
    result = PolicyResult(analysis=copy.deepcopy(analysis), level=level)
    work = result.analysis

    manual_present = DocCategory.SAFETY_MANUAL in present_docs

    # ---- 1. derate coverage by evidence strength -------------------------
    for mech_id, mech in work.mechanisms.items():
        confidence = mech.evidence.confidence if mech.evidence else Confidence.ESTIMATED
        tier = EVIDENCE_TIER[confidence]

        if not manual_present and confidence is Confidence.SUPPLIER_CLAIM:
            tier = max(1, tier - 1)
            result.actions.append(
                PolicyAction(
                    target=mech_id,
                    field_name="evidence tier",
                    before=2,
                    after=tier,
                    reason="supplier safety manual not provided — claim unsubstantiated",
                )
            )

        factor = DERATING[level][tier]
        for attr in ("dc_spf", "dc_lf"):
            before = getattr(mech, attr)
            after = round(before * factor, 6)
            if after != before:
                setattr(mech, attr, after)
                result.actions.append(
                    PolicyAction(
                        target=mech_id,
                        field_name=attr,
                        before=before,
                        after=after,
                        reason=(
                            f"{level.label}: evidence '{confidence.value}' (tier {tier}) "
                            f"derated by {factor:.2f}"
                        ),
                    )
                )

        # ---- 2. coverage that cannot demonstrate FTTI compliance ---------
        if level is Level.WORST_CASE and mech.dc_spf > 0 and mech.reaction_time_ms is None:
            result.actions.append(
                PolicyAction(
                    target=mech_id,
                    field_name="dc_spf",
                    before=mech.dc_spf,
                    after=0.0,
                    reason="no reaction time stated — FTTI compliance not demonstrable",
                )
            )
            mech.dc_spf = 0.0
            result.review_queue.append(
                f"{mech_id}: state reaction_time_ms, or the worst-case run credits no "
                f"single-point coverage for it"
            )

    # ---- 3. failure modes the analysis never classified ------------------
    for element in work.elements:
        if element.safety_related is False:
            continue
        part = parts.get(element.part)
        if part is None:
            continue

        unclassified = [m for m in part.failure_modes if m not in element.modes]
        if not unclassified:
            continue

        goals = sorted(
            {g for mode in element.modes.values() for g in (*mode.violates, *mode.latent_for)}
        )
        if not goals:
            continue

        for mode_name in unclassified:
            # Import here to keep the module's import surface small.
            from .models import ElementMode

            if level is Level.NOMINAL:
                result.review_queue.append(
                    f"{element.id}.{mode_name}: unclassified, treated as safe"
                )
                continue

            if level is Level.CONSERVATIVE:
                element.modes[mode_name] = ElementMode(
                    effect="Unclassified — treated as latent by conservatism policy",
                    latent_for=goals,
                )
                classification = "latent"
            else:
                element.modes[mode_name] = ElementMode(
                    effect="Unclassified — treated as a single-point fault by policy",
                    violates=goals,
                )
                classification = "single-point fault"

            result.actions.append(
                PolicyAction(
                    target=f"{element.id}.{mode_name}",
                    field_name="classification",
                    before="unclassified",
                    after=classification,
                    reason=f"{level.label}: no classification supplied for this failure mode",
                )
            )
            result.review_queue.append(
                f"{element.id}.{mode_name}: classify this mode — policy assumed "
                f"{classification}"
            )

    return result
