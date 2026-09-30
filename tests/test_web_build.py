"""The browser build must stay in step with the Python core.

Two implementations of the same metric is a real risk. The full parity check
lives in web/verify.py because it needs a browser; these are the parts that
run in plain CI.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).parent.parent
PAGE = ROOT / "docs" / "index.html"
DATA = ROOT / "web" / "data.json"


def test_page_is_built():
    assert PAGE.exists(), "run `python web/assemble.py`"
    assert PAGE.stat().st_size > 40_000


def test_page_is_self_contained():
    """It has to work from a local file with no network. Google Fonts is the
    one allowed external reference, and every face has a real fallback."""
    html = PAGE.read_text(encoding="utf-8")
    external = re.findall(r'<(?:script|link)[^>]*(?:src|href)="(https?://[^"]+)"', html)
    for url in external:
        assert "fonts.googleapis.com" in url or "fonts.gstatic.com" in url, \
            f"page depends on {url}; it must run offline"
    assert "sans-serif" in html and "monospace" in html, "font fallback stacks missing"


def test_bundled_data_matches_the_example():
    """The page's example is generated from the YAML, never hand-copied, so
    the two builds cannot end up describing different ECUs."""
    data = json.loads(DATA.read_text(encoding="utf-8"))
    analysis = yaml.safe_load((ROOT / "examples/bjb/fmeda.yaml").read_text(encoding="utf-8"))
    library = yaml.safe_load(
        (ROOT / "examples/bjb/library/generic.yaml").read_text(encoding="utf-8"))

    assert set(data["safety_goals"]) == set(analysis["safety_goals"])
    assert set(data["mechanisms"]) == set(analysis["mechanisms"])
    assert set(data["parts"]) == set(library["parts"])
    assert [e["id"] for e in data["elements"]] == [e["id"] for e in analysis["elements"]]
    assert json.dumps(data, sort_keys=True) == json.dumps(
        json.loads(DATA.read_text(encoding="utf-8")), sort_keys=True)


@pytest.mark.parametrize(
    "level,tiers",
    [("nominal", {4: 1.00, 3: 1.00, 2: 1.00, 1: 1.00}),
     ("conservative", {4: 1.00, 3: 0.95, 2: 0.90, 1: 0.60}),
     ("worst_case", {4: 1.00, 3: 0.90, 2: 0.00, 1: 0.00})],
)
def test_derating_table_is_identical_in_both_builds(level, tiers):
    """The single most drift-prone constant. If someone changes it in Python
    and not in the page, the demo and the library disagree about safety."""
    from fmeda.policy import DERATING, Level

    assert {k: round(v, 2) for k, v in DERATING[Level(level)].items()} == tiers

    js = (ROOT / "web" / "logic.js").read_text(encoding="utf-8")
    block = re.search(rf"{level}:\s*\{{([^}}]*)\}}", js).group(1)
    in_js = {int(k): float(v) for k, v in re.findall(r"(\d):\s*([\d.]+)", block)}
    assert in_js == tiers, f"web/logic.js disagrees with policy.py for {level}"


def test_generated_workbook_passes_structural_validation():
    """Guards the defect Excel caught and every other reader missed."""
    import subprocess
    import sys

    from fmeda import policy as P
    from fmeda.metrics import compute
    from fmeda.models import load_analysis
    from fmeda.report import write_report

    analysis, parts = load_analysis(ROOT / "examples/bjb/fmeda.yaml")
    result = P.apply(analysis, parts, P.Level.CONSERVATIVE, set())
    import tempfile
    out = Path(tempfile.mkdtemp()) / "r.xlsx"
    write_report(out, analysis, parts, result, compute(result.analysis, parts),
                 [], set(), "SN 29500", "40 C")
    done = subprocess.run([sys.executable, str(ROOT / "web" / "validate_ooxml.py"), str(out)],
                          capture_output=True, text=True)
    assert done.returncode == 0, done.stdout + done.stderr
