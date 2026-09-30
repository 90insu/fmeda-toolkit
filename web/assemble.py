"""Build the single-file browser app from its parts.

    python web/assemble.py

Writes two files from one source:

    docs/index.html      served by GitHub Pages, and the file you can
                         double-click to run the tool with nothing installed
    web/data.json        the bundled example, regenerated from examples/bjb/

Keeping the page in pieces makes it reviewable; shipping it as one file makes
it work offline with no build step for whoever opens it.
"""

import json
import pathlib

import yaml

WEB = pathlib.Path(__file__).parent
ROOT = WEB.parent
DOCS = ROOT / "docs"


def build_data() -> str:
    """The page's example data is generated from the YAML, never hand-copied,
    so the browser build and the Python core can't describe different ECUs."""
    analysis = yaml.safe_load((ROOT / "examples/bjb/fmeda.yaml").read_text(encoding="utf-8"))
    library = yaml.safe_load(
        (ROOT / "examples/bjb/library/generic.yaml").read_text(encoding="utf-8")
    )
    data = {
        "meta": {k: (str(v) if k == "date" else v)
                 for k, v in analysis["meta"].items() if k != "libraries"},
        "mission_profile": analysis["mission_profile"],
        "safety_goals": analysis["safety_goals"],
        "targets": analysis.get("targets", {}),
        "mechanisms": analysis["mechanisms"],
        "dc_combination": analysis.get("dc_combination", "max"),
        "elements": analysis["elements"],
        "assumptions": analysis.get("assumptions", {}),
        "parts": library["parts"],
    }
    text = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    (WEB / "data.json").write_text(text, encoding="utf-8")
    return text


def main() -> None:
    data = build_data()
    head = (WEB / "head.html").read_text(encoding="utf-8")
    body = (WEB / "body.html").read_text(encoding="utf-8")

    # Script order matters: zip and xlsx helpers, then the data and metric
    # logic, then the renderers, then the button wiring that needs all of it.
    scripts = "\n".join(
        (WEB / name).read_text(encoding="utf-8").replace("__DATA__", data)
        for name in ("xlsx.js", "logic.js", "render.js", "report.js")
    )
    inner = body + "\n" + scripts

    page = (
        '<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        + head
        + '\n</head>\n<body style="margin:0">\n'
        + inner
        + "\n</body>\n</html>\n"
    )

    DOCS.mkdir(exist_ok=True)
    (DOCS / "index.html").write_text(page, encoding="utf-8")
    (DOCS / ".nojekyll").write_text("", encoding="utf-8")  # serve files as-is
    print(f"docs/index.html  {len(page):,} bytes")


if __name__ == "__main__":
    main()
