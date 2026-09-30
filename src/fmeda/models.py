"""Pydantic v2 models for the fmeda-toolkit input schema.

Structural validation lives in the models. Cross-file rules that need both the
library and the analysis loaded (V2, V3, V4, V7) live in `validate_analysis`
below, because a pydantic validator can't see the other document.

    pip install "pydantic>=2.6" pyyaml
"""

from __future__ import annotations

from datetime import date as _date
from enum import Enum
from pathlib import Path
from typing import Annotated

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

Fraction = Annotated[float, Field(ge=0.0, le=1.0)]
NonNeg = Annotated[float, Field(ge=0.0)]

FRACTION_TOL = 1e-6


class Strict(BaseModel):
    """Reject unknown keys everywhere. A typo'd field must fail loudly, not
    vanish — a silently ignored `dc_lf:` misspelling is exactly the kind of
    defect this tool exists to prevent."""

    model_config = ConfigDict(extra="forbid")


class ASIL(str, Enum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"


class Confidence(str, Enum):
    MEASURED = "measured"
    FIELD_DATA = "field_data"
    SUPPLIER_CLAIM = "supplier_claim"
    STANDARD = "standard"
    ESTIMATED = "estimated"
    EXPERT_JUDGEMENT = "expert_judgement"


class Status(str, Enum):
    DRAFT = "draft"
    REVIEWED = "reviewed"
    RELEASED = "released"


class DCCombination(str, Enum):
    MAX = "max"
    INDEPENDENT = "independent"


# --------------------------------------------------------------------------
# Library
# --------------------------------------------------------------------------


class FailureMode(Strict):
    fraction: Fraction
    description: str | None = None


class Part(Strict):
    description: str
    lambda_fit: NonNeg
    failure_modes: dict[str, FailureMode]

    @model_validator(mode="after")
    def _fractions_sum_to_one(self) -> Part:
        """V1. The rule that catches lost or double-counted failure rate."""
        if not self.failure_modes:
            raise ValueError("part has no failure modes")
        total = sum(m.fraction for m in self.failure_modes.values())
        if abs(total - 1.0) > FRACTION_TOL:
            raise ValueError(
                f"failure mode fractions sum to {total:.6f}, expected 1.0 "
                f"(modes: {', '.join(self.failure_modes)})"
            )
        return self


class SourceRef(Strict):
    reference: str
    revision: str | None = None
    conditions: str | None = None


class LibraryMeta(Strict):
    id: str
    description: str | None = None
    source: SourceRef | None = None
    confidence: Confidence = Confidence.ESTIMATED


class Library(Strict):
    schema_: str = Field(alias="schema")
    library: LibraryMeta
    parts: dict[str, Part]


# --------------------------------------------------------------------------
# Analysis
# --------------------------------------------------------------------------


class AnalysisMeta(Strict):
    item: str
    variant: str | None = None
    analyst: str | None = None
    date: _date | None = None
    status: Status = Status.DRAFT
    libraries: list[str] = Field(default_factory=list)


class MissionProfile(Strict):
    lifetime_h: NonNeg
    mpf_detection_interval_h: NonNeg | None = None


class SafetyGoal(Strict):
    statement: str
    asil: ASIL
    ftti_ms: float | None = Field(default=None, gt=0)
    safe_state: str | None = None


class Target(Strict):
    spfm: Fraction
    lfm: Fraction
    pmhf_fit: NonNeg


# ISO 26262-5:2018 Tables 4, 5 and 6. These tables are informative; OEMs
# routinely set tighter values, so they are defaults, not constants. Verify
# against your own copy of the standard before relying on them.
DEFAULT_TARGETS: dict[ASIL, Target] = {
    ASIL.B: Target(spfm=0.90, lfm=0.60, pmhf_fit=100.0),
    ASIL.C: Target(spfm=0.97, lfm=0.80, pmhf_fit=100.0),
    ASIL.D: Target(spfm=0.99, lfm=0.90, pmhf_fit=10.0),
}


class Evidence(Strict):
    reference: str | None = None
    rationale: str | None = None
    confidence: Confidence = Confidence.ESTIMATED
    assumption: str | None = None  # id into `assumptions`


class Mechanism(Strict):
    name: str
    dc_spf: Fraction = 0.0
    dc_lf: Fraction = 0.0
    reaction_time_ms: float | None = Field(default=None, gt=0)
    covers_goals: list[str] = Field(default_factory=list, min_length=1)
    implemented_by: list[str] = Field(default_factory=list)
    evidence: Evidence | None = None


class ElementMode(Strict):
    effect: str | None = None
    violates: list[str] = Field(default_factory=list)
    mechanisms: list[str] = Field(default_factory=list)
    latent_for: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _coverage_needs_something_to_cover(self) -> ElementMode:
        """V6. A mechanism claimed on a mode that violates nothing and is
        latent for nothing is almost always a missed classification, not a
        deliberate statement."""
        if self.mechanisms and not self.violates and not self.latent_for:
            raise ValueError(
                "mechanisms claimed on a mode with empty `violates` and empty "
                "`latent_for` — classify the mode first"
            )
        return self


class Element(Strict):
    id: str
    description: str | None = None
    part: str
    quantity: int = Field(default=1, ge=1)
    safety_related: bool | None = None
    modes: dict[str, ElementMode]

    @model_validator(mode="after")
    def _explicit_non_safety_related(self) -> Element:
        if self.safety_related is False:
            for name, mode in self.modes.items():
                if mode.violates or mode.latent_for:
                    raise ValueError(
                        f"element marked safety_related: false but mode "
                        f"'{name}' declares violates/latent_for"
                    )
        return self


class Assumption(Strict):
    statement: str
    status: str = "open"
    owner: str | None = None


class Analysis(Strict):
    schema_: str = Field(alias="schema")
    meta: AnalysisMeta
    mission_profile: MissionProfile
    safety_goals: dict[str, SafetyGoal] = Field(min_length=1)
    targets: dict[ASIL, Target] = Field(default_factory=dict)
    mechanisms: dict[str, Mechanism] = Field(default_factory=dict)
    dc_combination: DCCombination = DCCombination.MAX
    elements: list[Element] = Field(min_length=1)
    assumptions: dict[str, Assumption] = Field(default_factory=dict)

    def target_for(self, asil: ASIL) -> Target:
        return self.targets.get(asil) or DEFAULT_TARGETS[asil]


# --------------------------------------------------------------------------
# Loading and cross-document validation
# --------------------------------------------------------------------------


# Analyses and libraries are UTF-8 — they carry lambda, degree and dash
# characters in descriptions and comments. Never let the platform's locale
# decide: Path.read_text() with no encoding uses the system default, which is
# cp949 on a Korean Windows install, cp1252 on a German one, and UTF-8 on Linux
# and macOS. That is how a file that loads on the author's machine fails on a
# colleague's, and it is exactly the class of defect a safety tool must not have.
ENCODING = "utf-8"


def load_analysis(path: str | Path) -> tuple[Analysis, dict[str, Part]]:
    """Load an analysis and the union of its libraries' parts."""
    path = Path(path)
    analysis = Analysis.model_validate(yaml.safe_load(path.read_text(encoding=ENCODING)))

    parts: dict[str, Part] = {}
    for rel in analysis.meta.libraries:
        lib_text = (path.parent / rel).read_text(encoding=ENCODING)
        lib = Library.model_validate(yaml.safe_load(lib_text))
        for part_id, part in lib.parts.items():
            if part_id in parts:
                raise ValueError(
                    f"part '{part_id}' defined in more than one library; "
                    f"qualify it as '{lib.library.id}.{part_id}'"
                )
            parts[part_id] = part
    return analysis, parts


def validate_analysis(analysis: Analysis, parts: dict[str, Part]) -> list[str]:
    """Cross-document rules V2-V9. Returns human-readable problems; an empty
    list means the analysis is structurally sound.

    Errors are prefixed 'error:', advisories 'warn:'. Both are worth printing —
    V8 in particular is an advisory that changes how a reviewer reads the
    result rather than something that should block a run.
    """
    problems: list[str] = []
    goal_ids = set(analysis.safety_goals)
    mech_ids = set(analysis.mechanisms)
    element_ids = {e.id for e in analysis.elements}

    # V3 — mechanism references
    for mid, mech in analysis.mechanisms.items():
        for gid in mech.covers_goals:
            if gid not in goal_ids:
                problems.append(f"error: mechanism '{mid}' covers unknown goal '{gid}'")
        for eid in mech.implemented_by:
            if eid not in element_ids:
                problems.append(
                    f"error: mechanism '{mid}' implemented_by unknown element '{eid}'"
                )

        # V4 — a coverage claim the mechanism cannot react fast enough to make
        if mech.dc_spf > 0 and mech.reaction_time_ms is not None:
            for gid in mech.covers_goals:
                goal = analysis.safety_goals.get(gid)
                if goal and goal.ftti_ms and mech.reaction_time_ms > goal.ftti_ms:
                    problems.append(
                        f"error: mechanism '{mid}' claims dc_spf={mech.dc_spf} for "
                        f"'{gid}' but reacts in {mech.reaction_time_ms} ms > FTTI "
                        f"{goal.ftti_ms} ms"
                    )

        # V8 — the highest-leverage number resting on the weakest evidence
        conf = mech.evidence.confidence if mech.evidence else Confidence.ESTIMATED
        if mech.dc_spf >= 0.99 and conf in (
            Confidence.ESTIMATED,
            Confidence.EXPERT_JUDGEMENT,
        ):
            problems.append(
                f"warn: mechanism '{mid}' claims dc_spf={mech.dc_spf} on "
                f"'{conf.value}' evidence"
            )

    # V2, V3 — element references
    for el in analysis.elements:
        part = parts.get(el.part)
        if part is None:
            problems.append(f"error: element '{el.id}' references unknown part '{el.part}'")
            continue
        for mode_name, mode in el.modes.items():
            if mode_name not in part.failure_modes:
                problems.append(
                    f"error: element '{el.id}' mode '{mode_name}' not in part "
                    f"'{el.part}' (has: {', '.join(part.failure_modes)})"
                )
            for gid in (*mode.violates, *mode.latent_for):
                if gid not in goal_ids:
                    problems.append(
                        f"error: element '{el.id}' mode '{mode_name}' references "
                        f"unknown goal '{gid}'"
                    )
            for mid in mode.mechanisms:
                if mid not in mech_ids:
                    problems.append(
                        f"error: element '{el.id}' mode '{mode_name}' references "
                        f"unknown mechanism '{mid}'"
                    )

        # V9 — a declared mode of the part that the analysis never classified
        missing = set(part.failure_modes) - set(el.modes)
        if missing and el.safety_related is not False:
            problems.append(
                f"warn: element '{el.id}' does not classify mode(s) "
                f"{', '.join(sorted(missing))} — silent omission"
            )

    # V7 — the independence claim must be written down somewhere
    if analysis.dc_combination is DCCombination.INDEPENDENT:
        referenced = any(
            "independen" in a.statement.lower() for a in analysis.assumptions.values()
        )
        if not referenced:
            problems.append(
                "error: dc_combination 'independent' requires an assumptions entry "
                "recording the dependent-failure argument (ISO 26262-9 Clause 7)"
            )

    return problems
