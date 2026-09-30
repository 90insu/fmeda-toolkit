"""Command line interface.

The exit codes matter: `compute` returning 3 when a target is missed is what
lets a metric regression fail a build.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fmeda.__main__ import main

EXAMPLE = str(Path(__file__).parent.parent / "examples" / "bjb" / "fmeda.yaml")


def test_check_returns_zero_on_a_clean_analysis(capsys):
    assert main(["check", EXAMPLE]) == 0
    assert "validation clean" in capsys.readouterr().out


def test_compute_exits_three_when_a_target_is_missed(capsys):
    # The worked example deliberately misses its ASIL D SPFM target.
    assert main(["compute", EXAMPLE, "--goal", "SG1"]) == 3
    out = capsys.readouterr().out
    assert "SPFM" in out and "FAIL" in out
    assert "lower bound" in out, "the PMHF caveat must travel with the number"


def test_json_output_is_machine_readable(capsys):
    assert main(["compute", EXAMPLE, "--json"]) in (0, 3)
    payload = json.loads(capsys.readouterr().out)
    assert set(payload) == {"SG1", "SG2"}
    assert payload["SG1"]["asil"] == "D"
    assert "pmhf_fit_lower_bound" in payload["SG1"], "never call it 'pmhf'"


@pytest.mark.parametrize("level", ["nominal", "conservative", "worst_case"])
def test_every_level_runs_from_the_cli(capsys, level):
    assert main(["compute", EXAMPLE, "--json", "--level", level]) in (0, 3)
    payload = json.loads(capsys.readouterr().out)
    assert payload["SG1"]["conservatism"] == level


def test_unknown_goal_is_a_usage_error(capsys):
    assert main(["compute", EXAMPLE, "--goal", "SG9"]) == 2


def test_missing_file_is_a_usage_error(capsys):
    assert main(["check", "does-not-exist.yaml"]) == 2
