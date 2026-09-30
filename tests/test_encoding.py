"""Text I/O must never depend on the platform's locale.

Found the hard way: on a Korean Windows install the default encoding is cp949,
so `Path.read_text()` with no encoding tried to decode UTF-8 YAML as cp949 and
died on the first em dash. Every test in the suite failed, on a machine where
nothing was wrong with the analysis.

A file that loads on the author's laptop and fails on a colleague's is exactly
the defect class a safety tool cannot have, so this is guarded at the source
level rather than trusted to review.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from fmeda.models import load_analysis

SRC = Path(__file__).parent.parent / "src" / "fmeda"

# read_text / write_text / open, where the call does not name an encoding.
UNSAFE = re.compile(r"\.(?:read_text|write_text)\((?![^)]*encoding)|(?<![.\w])open\((?![^)]*encoding)")


@pytest.mark.parametrize("module", sorted(SRC.glob("*.py")), ids=lambda p: p.name)
def test_no_text_io_without_an_explicit_encoding(module: Path):
    source = module.read_text(encoding="utf-8")
    offenders = [
        f"{module.name}:{i}: {line.strip()}"
        for i, line in enumerate(source.splitlines(), start=1)
        # Scan code only. A comment discussing the hazard is not the hazard.
        if UNSAFE.search(line.split("#", 1)[0])
    ]
    assert not offenders, (
        "text I/O without an explicit encoding falls back to the system locale "
        "(cp949 on Korean Windows, cp1252 on German, UTF-8 on Linux):\n  "
        + "\n  ".join(offenders)
    )


def test_analysis_with_non_ascii_content_loads(tmp_path: Path):
    """The example files carry λ, °C and em dashes. So must any user's."""
    (tmp_path / "lib.yaml").write_text(
        "schema: fmeda.library/v1\n"
        "library: { id: t, description: 'λ at 40 °C — derated' }\n"
        "parts:\n"
        "  p:\n"
        "    description: 'Widerstand — 0603, ±1%'\n"
        "    lambda_fit: 10\n"
        "    failure_modes:\n"
        "      a: { fraction: 1.0, description: '개방 — open circuit' }\n",
        encoding="utf-8",
    )
    (tmp_path / "a.yaml").write_text(
        "schema: fmeda.analysis/v1\n"
        "meta: { item: 'Steuergerät — 제어기', libraries: ['lib.yaml'] }\n"
        "mission_profile: { lifetime_h: 10000 }\n"
        "safety_goals:\n"
        "  SG1: { statement: 'λ ≤ target — 안전 목표', asil: D, ftti_ms: 100 }\n"
        "elements:\n"
        "  - id: E1\n"
        "    part: p\n"
        "    modes:\n"
        "      a: { effect: 'Ausfall — 고장', violates: [SG1] }\n",
        encoding="utf-8",
    )

    analysis, parts = load_analysis(tmp_path / "a.yaml")
    assert analysis.meta.item == "Steuergerät — 제어기"
    assert "개방" in parts["p"].failure_modes["a"].description


def test_every_shipped_yaml_file_is_utf8():
    root = Path(__file__).parent.parent
    for path in sorted(root.glob("examples/**/*.yaml")):
        path.read_text(encoding="utf-8")  # raises if it is not
