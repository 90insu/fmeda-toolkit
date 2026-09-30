"""Conservatism policy, and a regression lock on the worked example.

The policy's whole claim is that it is deterministic — same inputs, same level,
same numbers, every time. These tests are what make that claim checkable.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from fmeda import policy as P
from fmeda.metrics import compute
from fmeda.models import Analysis, Library, load_analysis

EXAMPLE = Path(__file__).parent.parent / "examples" / "bjb" / "fmeda.yaml"

LIB = """
schema: fmeda.library/v1
library: { id: t }
parts:
  p:
    description: test
    lambda_fit: 100
    failure_modes:
      a: { fraction: 0.5 }
      b: { fraction: 0.5 }
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
    dc_spf: 1.0
    dc_lf: 1.0
    reaction_time_ms: 10
    covers_goals: [SG1]
    evidence: { reference: r, confidence: supplier_claim }
elements:
  - id: E1
    part: p
    modes:
      a: { effect: x, violates: [SG1], mechanisms: [M1] }
      b: { effect: y, violates: [] }
"""

ALL_DOCS = set(P.DocCategory)


def load():
    return (Analysis.model_validate(yaml.safe_load(ANALYSIS)),
            Library.model_validate(yaml.safe_load(LIB)).parts)


@pytest.mark.parametrize(
    "level,expected_dc",
    [
        (P.Level.NOMINAL, 1.00),        # supplier_claim tier 2 × 1.00
        (P.Level.CONSERVATIVE, 0.90),   # tier 2 × 0.90
        (P.Level.WORST_CASE, 0.00),     # tier 2 × 0.00 — unverified claims die
    ],
)
def test_supplier_claim_derating_by_level(level, expected_dc):
    analysis, parts = load()
    result = P.apply(analysis, parts, level, ALL_DOCS)
    assert result.analysis.mechanisms["M1"].dc_spf == pytest.approx(expected_dc)


def test_measured_evidence_is_never_derated():
    analysis, parts = load()
    analysis.mechanisms["M1"].evidence.confidence = "measured"
    for level in P.Level:
        result = P.apply(analysis, parts, level, ALL_DOCS)
        assert result.analysis.mechanisms["M1"].dc_spf == pytest.approx(1.0)


def test_missing_safety_manual_costs_an_evidence_tier():
    """This is what makes 'more reference documents give a more precise
    analysis' a true statement about the tool rather than a marketing line."""
    analysis, parts = load()
    without = ALL_DOCS - {P.DocCategory.SAFETY_MANUAL}

    with_manual = P.apply(analysis, parts, P.Level.CONSERVATIVE, ALL_DOCS)
    no_manual = P.apply(analysis, parts, P.Level.CONSERVATIVE, without)

    # supplier_claim (tier 2, ×0.90) drops to tier 1 (×0.60).
    assert with_manual.analysis.mechanisms["M1"].dc_spf == pytest.approx(0.90)
    assert no_manual.analysis.mechanisms["M1"].dc_spf == pytest.approx(0.60)
    assert any("safety manual not provided" in a.reason for a in no_manual.actions)


def test_policy_never_mutates_the_original():
    """The report shows stated vs. applied coverage side by side, which only
    works if the input survives the transform untouched."""
    analysis, parts = load()
    before = analysis.mechanisms["M1"].dc_spf
    P.apply(analysis, parts, P.Level.WORST_CASE, ALL_DOCS)
    assert analysis.mechanisms["M1"].dc_spf == before


def test_every_change_is_recorded_with_a_reason():
    analysis, parts = load()
    result = P.apply(analysis, parts, P.Level.CONSERVATIVE, ALL_DOCS)
    assert result.actions
    for action in result.actions:
        assert action.reason and action.target and action.before != action.after


def test_policy_is_deterministic():
    analysis, parts = load()
    runs = [
        [(a.target, a.field_name, a.after)
         for a in P.apply(analysis, parts, P.Level.CONSERVATIVE, ALL_DOCS).actions]
        for _ in range(3)
    ]
    assert runs[0] == runs[1] == runs[2]


def test_unclassified_mode_hardens_with_the_level():
    analysis, parts = load()
    del analysis.elements[0].modes["b"]  # leave 'b' unclassified

    nominal = P.apply(analysis, parts, P.Level.NOMINAL, ALL_DOCS)
    assert "b" not in nominal.analysis.elements[0].modes  # treated as safe

    conservative = P.apply(analysis, parts, P.Level.CONSERVATIVE, ALL_DOCS)
    assert conservative.analysis.elements[0].modes["b"].latent_for == ["SG1"]

    worst = P.apply(analysis, parts, P.Level.WORST_CASE, ALL_DOCS)
    assert worst.analysis.elements[0].modes["b"].violates == ["SG1"]
    assert worst.review_queue


def test_levels_are_monotonically_conservative():
    """A selector that barely moves the result is decoration. Each step up must
    weaken SPFM and raise PMHF, or the control is lying to the user."""
    analysis, parts = load_analysis(EXAMPLE)
    docs = ALL_DOCS - {P.DocCategory.SAFETY_MANUAL}
    spfm, pmhf = [], []
    for level in (P.Level.NOMINAL, P.Level.CONSERVATIVE, P.Level.WORST_CASE):
        result = compute(P.apply(analysis, parts, level, docs).analysis, parts)["SG1"]
        spfm.append(result.spfm)
        pmhf.append(result.pmhf_fit)
    assert spfm[0] > spfm[1] > spfm[2]
    assert pmhf[0] < pmhf[1] < pmhf[2]


@pytest.mark.parametrize(
    "goal,spfm,lfm,pmhf",
    [
        ("SG1", 0.96077563, 0.98091610, 6.50340),
        ("SG2", 0.91704121, 0.97618121, 8.69740),
    ],
)
def test_worked_example_regression(goal, spfm, lfm, pmhf):
    """Locks the published figures in docs/schema.md. If a refactor moves these,
    either the refactor is wrong or the documentation needs updating — and
    either way somebody has to look."""
    analysis, parts = load_analysis(EXAMPLE)
    result = compute(analysis, parts)[goal]
    assert result.spfm == pytest.approx(spfm, abs=1e-6)
    assert result.lfm == pytest.approx(lfm, abs=1e-6)
    assert result.pmhf_fit == pytest.approx(pmhf, abs=1e-4)


def test_worked_example_validates_clean():
    from fmeda.models import validate_analysis

    analysis, parts = load_analysis(EXAMPLE)
    assert validate_analysis(analysis, parts) == []


def test_empty_document_set_is_not_treated_as_all_documents():
    """Caught by the browser-parity check. `present_docs or set(DocCategory)`
    treats an empty set as falsy, so a run with nothing uploaded silently
    claimed every document was present and credited coverage the evidence did
    not support. Only None may mean 'unspecified'."""
    analysis, parts = load()
    none_at_all = P.apply(analysis, parts, P.Level.CONSERVATIVE, set())
    everything = P.apply(analysis, parts, P.Level.CONSERVATIVE, ALL_DOCS)

    assert none_at_all.analysis.mechanisms["M1"].dc_spf == pytest.approx(0.60)
    assert everything.analysis.mechanisms["M1"].dc_spf == pytest.approx(0.90)
    assert any("safety manual not provided" in a.reason for a in none_at_all.actions)


def test_unspecified_documents_still_means_all_present():
    analysis, parts = load()
    assert (P.apply(analysis, parts, P.Level.CONSERVATIVE).analysis.mechanisms["M1"].dc_spf
            == pytest.approx(0.90))
