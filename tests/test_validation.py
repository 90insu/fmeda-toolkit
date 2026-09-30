"""Validation rules V1-V9.

Each test is a defect that survives happily in a spreadsheet. That is the point
of the rule, so each test names it.
"""

from __future__ import annotations

import pytest
import yaml
from pydantic import ValidationError

from fmeda.models import Analysis, DCCombination, Library, Part, validate_analysis

LIB = """
schema: fmeda.library/v1
library: { id: t }
parts:
  p:
    description: test
    lambda_fit: 100
    failure_modes:
      a: { fraction: 0.6 }
      b: { fraction: 0.4 }
"""

ANALYSIS = """
schema: fmeda.analysis/v1
meta: { item: Test }
mission_profile: { lifetime_h: 10000 }
safety_goals:
  SG1: { statement: g, asil: D, ftti_ms: 100 }
mechanisms:
  M1:
    name: M
    dc_spf: 0.9
    dc_lf: 0.8
    reaction_time_ms: 10
    covers_goals: [SG1]
    evidence: { reference: r, confidence: measured }
elements:
  - id: E1
    part: p
    modes:
      a: { effect: x, violates: [SG1], mechanisms: [M1] }
      b: { effect: y, violates: [] }
"""


def load(analysis_yaml: str = ANALYSIS, lib_yaml: str = LIB):
    analysis = Analysis.model_validate(yaml.safe_load(analysis_yaml))
    lib = Library.model_validate(yaml.safe_load(lib_yaml))
    return analysis, lib.parts


def test_baseline_is_clean():
    analysis, parts = load()
    assert validate_analysis(analysis, parts) == []


def test_v1_fractions_must_sum_to_one():
    """Lost or double-counted failure rate — the commonest spreadsheet defect,
    and invisible once the column scrolls off screen."""
    with pytest.raises(ValidationError, match="sum to 0.9"):
        Part(description="x", lambda_fit=1.0,
             failure_modes={"a": {"fraction": 0.5}, "b": {"fraction": 0.4}})


def test_v2_mode_must_exist_in_the_part():
    """A renamed failure mode silently drops out of the analysis otherwise."""
    analysis, parts = load(ANALYSIS.replace("      a: { effect: x",
                                            "      typo: { effect: x"))
    problems = validate_analysis(analysis, parts)
    assert any("mode 'typo' not in part" in p for p in problems)


def test_v3_unknown_references_are_errors():
    analysis, parts = load(ANALYSIS.replace("mechanisms: [M1]", "mechanisms: [M9]"))
    assert any("unknown mechanism 'M9'" in p for p in validate_analysis(analysis, parts))


def test_v4_coverage_cannot_outlive_the_ftti():
    """The classic unjustifiable claim: a diagnostic that reacts in 500 ms
    claiming single-point coverage against a 100 ms fault-tolerant time
    interval. No spreadsheet can check this."""
    analysis, parts = load(ANALYSIS.replace("reaction_time_ms: 10",
                                            "reaction_time_ms: 500"))
    problems = validate_analysis(analysis, parts)
    assert any("> FTTI" in p and p.startswith("error:") for p in problems)


def test_v4_passes_when_reaction_fits():
    analysis, parts = load(ANALYSIS.replace("reaction_time_ms: 10",
                                            "reaction_time_ms: 99"))
    assert not any("> FTTI" in p for p in validate_analysis(analysis, parts))


def test_v5_coverage_outside_zero_to_one_is_rejected():
    with pytest.raises(ValidationError):
        Analysis.model_validate(yaml.safe_load(ANALYSIS.replace("dc_spf: 0.9",
                                                                "dc_spf: 1.4")))


def test_v6_coverage_needs_something_to_cover():
    """A mechanism claimed on a mode that violates nothing is nearly always a
    missed classification rather than a deliberate statement."""
    with pytest.raises(ValidationError, match="classify the mode first"):
        Analysis.model_validate(yaml.safe_load(
            ANALYSIS.replace("b: { effect: y, violates: [] }",
                             "b: { effect: y, violates: [], mechanisms: [M1] }")))


def test_v7_independent_combination_needs_a_written_argument():
    """Independence is a claim about dependent failures (ISO 26262-9 Clause 7),
    not a checkbox. The rule forces the argument to exist in writing."""
    analysis, parts = load()
    analysis.dc_combination = DCCombination.INDEPENDENT
    problems = validate_analysis(analysis, parts)
    assert any("dependent-failure argument" in p for p in problems)

    from fmeda.models import Assumption

    analysis.assumptions["A1"] = Assumption(
        statement="M1 and M2 are independent; no shared failure cause identified."
    )
    assert not any("dependent-failure argument" in p
                   for p in validate_analysis(analysis, parts))


def test_v8_warns_when_a_high_claim_rests_on_weak_evidence():
    analysis, parts = load(ANALYSIS.replace("confidence: measured",
                                            "confidence: estimated")
                                   .replace("dc_spf: 0.9", "dc_spf: 0.99"))
    problems = validate_analysis(analysis, parts)
    assert any(p.startswith("warn:") and "estimated" in p for p in problems)


def test_v9_warns_on_an_unclassified_mode():
    """Silent omission — the failure mode of FMEDA itself."""
    analysis, parts = load(ANALYSIS.replace("      b: { effect: y, violates: [] }\n", ""))
    problems = validate_analysis(analysis, parts)
    assert any(p.startswith("warn:") and "silent omission" in p for p in problems)


def test_unknown_field_is_rejected_not_ignored():
    """A misspelled `dc_lf:` that is silently ignored is exactly the defect
    class this tool exists to prevent, so extra keys must be fatal."""
    with pytest.raises(ValidationError):
        Analysis.model_validate(yaml.safe_load(
            ANALYSIS.replace("    dc_lf: 0.8", "    dc_If: 0.8")))
