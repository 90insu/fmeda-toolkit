"""Metric arithmetic, checked against fixtures computed by hand.

The fixtures below are deliberately small enough to verify with a calculator,
and the expected value in each assertion is written out as the arithmetic that
produced it. A test whose expected value came from running the code proves only
that the code still does what it did — which is worthless for a tool whose
whole claim is that the numbers are right.
"""

from __future__ import annotations

import pytest
import yaml

from fmeda.metrics import FaultClass, compute
from fmeda.models import Analysis, DCCombination, Part

BASE = """
schema: fmeda.analysis/v1
meta:
  item: Test item
mission_profile:
  lifetime_h: 10000
safety_goals:
  SG1:
    statement: Test goal
    asil: D
    ftti_ms: 100
mechanisms:
  M1:
    name: Test mechanism
    dc_spf: 0.90
    dc_lf: 0.80
    reaction_time_ms: 10
    covers_goals: [SG1]
    evidence: { reference: test, confidence: measured }
elements:
  - id: E1
    part: p
    quantity: 1
    modes:
      bad:    { effect: violates, violates: [SG1], mechanisms: [M1] }
      latent: { effect: disables a diagnostic, latent_for: [SG1], mechanisms: [M1] }
      benign: { effect: nothing, violates: [] }
"""

PART = Part(
    description="test part",
    lambda_fit=100.0,
    failure_modes={
        "bad": {"fraction": 0.5},
        "latent": {"fraction": 0.3},
        "benign": {"fraction": 0.2},
    },
)


@pytest.fixture
def analysis() -> Analysis:
    return Analysis.model_validate(yaml.safe_load(BASE))


@pytest.fixture
def parts() -> dict[str, Part]:
    return {"p": PART}


def test_hand_computed_split(analysis, parts):
    """λ_element = 100 FIT × qty 1.

        bad    = 100 × 0.5 = 50 FIT, violates, DC_spf 0.90
                 → RF     = 50 × 0.10 =  5.0
                 → MPF,D  = 50 × 0.90 = 45.0
        latent = 100 × 0.3 = 30 FIT, latent, DC_lf 0.80
                 → MPF,L  = 30 × 0.20 =  6.0
                 → MPF,D  = 30 × 0.80 = 24.0
        benign = 100 × 0.2 = 20 FIT  → Safe
    """
    totals = compute(analysis, parts)["SG1"].totals
    assert totals.spf == pytest.approx(0.0)
    assert totals.rf == pytest.approx(5.0)
    assert totals.mpf_l == pytest.approx(6.0)
    assert totals.mpf_d == pytest.approx(45.0 + 24.0)
    assert totals.safe == pytest.approx(20.0)
    assert totals.total == pytest.approx(100.0), "every FIT must be accounted for"


def test_hand_computed_metrics(analysis, parts):
    """λ_SR = 0 + 5 + 6 + 69 = 80 FIT

        SPFM = 1 − (0 + 5) / 80        = 0.9375
        LFM  = 1 − 6 / (80 − 0 − 5)    = 1 − 6/75 = 0.92
        PMHF = 0 + 5                   = 5.0 FIT
    """
    result = compute(analysis, parts)["SG1"]
    assert result.totals.safety_related == pytest.approx(80.0)
    assert result.spfm == pytest.approx(0.9375)
    assert result.lfm == pytest.approx(0.92)
    assert result.pmhf_fit == pytest.approx(5.0)


def test_no_mechanism_is_a_single_point_fault(analysis, parts):
    analysis.elements[0].modes["bad"].mechanisms = []
    totals = compute(analysis, parts)["SG1"].totals
    # The whole 50 FIT is now uncovered, and it is SPF rather than RF.
    assert totals.spf == pytest.approx(50.0)
    assert totals.rf == pytest.approx(0.0)


def test_mechanism_scoped_to_another_goal_gives_no_coverage(analysis, parts):
    """The subtle one. A mechanism listed on the mode but not covering this
    goal must leave the mode a single-point fault, not a residual fault with
    zero coverage — the two are different classes in the report."""
    analysis.mechanisms["M1"].covers_goals = ["SG2"]
    analysis.safety_goals["SG2"] = analysis.safety_goals["SG1"]
    result = compute(analysis, parts)["SG1"]
    bad = next(r for r in result.rows if r.mode == "bad")
    assert bad.fault_class == FaultClass.SPF
    assert "scoped to other goals" in bad.rationale


def test_quantity_multiplies_lambda(analysis, parts):
    analysis.elements[0].quantity = 4
    totals = compute(analysis, parts)["SG1"].totals
    assert totals.total == pytest.approx(400.0)
    assert totals.rf == pytest.approx(20.0)  # 4 × 5.0


def test_dc_combination_max_vs_independent(analysis, parts):
    analysis.mechanisms["M2"] = analysis.mechanisms["M1"].model_copy(
        update={"dc_spf": 0.50, "name": "Second mechanism"}
    )
    analysis.elements[0].modes["bad"].mechanisms = ["M1", "M2"]

    analysis.dc_combination = DCCombination.MAX
    # max(0.90, 0.50) = 0.90 → RF = 50 × 0.10 = 5.0
    assert compute(analysis, parts)["SG1"].totals.rf == pytest.approx(5.0)

    analysis.dc_combination = DCCombination.INDEPENDENT
    # 1 − (1−0.90)(1−0.50) = 0.95 → RF = 50 × 0.05 = 2.5
    assert compute(analysis, parts)["SG1"].totals.rf == pytest.approx(2.5)


def test_rationale_is_generated_for_every_row(analysis, parts):
    """The report's comment column is generated from the classification, so it
    can never drift away from the number beside it. Every row must have one."""
    for row in compute(analysis, parts)["SG1"].rows:
        assert row.rationale
        assert row.fault_class in vars(FaultClass).values()


def test_residual_ranking_orders_by_uncovered_rate(analysis, parts):
    analysis.elements.append(
        analysis.elements[0].model_copy(update={"id": "E2", "quantity": 3})
    )
    ranked = compute(analysis, parts)["SG1"].residual_ranking()
    assert [r.element for r in ranked] == ["E2", "E1"]
    assert all(r.fault_class in (FaultClass.SPF, FaultClass.RF) for r in ranked)
