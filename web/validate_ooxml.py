"""Structural validation of a generated .xlsx against the OOXML schema rules
that Excel enforces and other readers do not.

Written after Excel refused a workbook that openpyxl and LibreOffice both read
without complaint. The defect was `<calcPr>` placed before `<sheets>`: OOXML
fixes the order of child elements, and Excel rejects the file outright while
lenient readers reorder it silently. Checking with a reader that tolerates the
mistake is not checking.
"""

from __future__ import annotations

import re
import sys
import zipfile
from pathlib import Path

# ECMA-376 CT_Workbook and CT_Worksheet child sequences, in schema order.
WORKBOOK_ORDER = [
    "fileVersion", "fileSharing", "workbookPr", "workbookProtection", "bookViews",
    "sheets", "functionGroups", "externalReferences", "definedNames", "calcPr",
    "oleSize", "customWorkbookViews", "pivotCaches", "smartTagPr", "smartTagTypes",
    "webPublishing", "fileRecoveryPr", "webPublishObjects", "extLst",
]
WORKSHEET_ORDER = [
    "sheetPr", "dimension", "sheetViews", "sheetFormatPr", "cols", "sheetData",
    "sheetCalcPr", "sheetProtection", "protectedRanges", "scenarios", "autoFilter",
    "sortState", "dataConsolidate", "customSheetViews", "mergeCells", "phoneticPr",
    "conditionalFormatting", "dataValidations", "hyperlinks", "printOptions",
    "pageMargins", "pageSetup", "headerFooter", "rowBreaks", "colBreaks",
    "customProperties", "cellWatches", "ignoredErrors", "smartTags", "drawing",
    "legacyDrawing", "picture", "oleObjects", "controls", "tableParts", "extLst",
]
STYLESHEET_ORDER = [
    "numFmts", "fonts", "fills", "borders", "cellStyleXfs", "cellXfs", "cellStyles",
    "dxfs", "tableStyles", "colors", "extLst",
]


def children(xml: str, root: str) -> list[str]:
    inner = xml.split(f"<{root}", 1)[1].split(">", 1)[1]
    inner = inner.rsplit(f"</{root}>", 1)[0]
    depth, names = 0, []
    for m in re.finditer(r"<(/?)([A-Za-z:]+)([^>]*?)(/?)>", inner):
        closing, name, attrs, self_closing = m.groups()
        if name.startswith("?") or name.startswith("!"):
            continue
        if closing:
            depth -= 1
            continue
        if depth == 0:
            names.append(name)
        if not self_closing:
            depth += 1
    return names


def check_order(names: list[str], schema: list[str], where: str) -> list[str]:
    problems, last = [], -1
    for n in names:
        if n not in schema:
            problems.append(f"{where}: unknown element <{n}>")
            continue
        i = schema.index(n)
        if i < last:
            problems.append(
                f"{where}: <{n}> appears after an element that must follow it "
                f"(schema order: {', '.join(schema[:schema.index(n)+3])}...)"
            )
        last = max(last, i)
    return problems


def validate(path: Path) -> list[str]:
    problems: list[str] = []
    with zipfile.ZipFile(path) as z:
        names = set(z.namelist())
        for required in ("[Content_Types].xml", "_rels/.rels", "xl/workbook.xml",
                         "xl/_rels/workbook.xml.rels", "xl/styles.xml"):
            if required not in names:
                problems.append(f"missing part {required}")

        bad = z.testzip()
        if bad:
            problems.append(f"corrupt zip entry: {bad}")

        wb = z.read("xl/workbook.xml").decode()
        problems += check_order(children(wb, "workbook"), WORKBOOK_ORDER, "workbook.xml")

        styles = z.read("xl/styles.xml").decode()
        problems += check_order(children(styles, "styleSheet"), STYLESHEET_ORDER, "styles.xml")

        # Declared counts must match what is actually there, or Excel repairs.
        for tag, child in [("fonts", "font"), ("fills", "fill"), ("borders", "border"),
                           ("cellStyleXfs", "xf"), ("cellXfs", "xf"), ("numFmts", "numFmt")]:
            m = re.search(rf'<{tag} count="(\d+)"', styles)
            if not m:
                continue
            block = styles.split(f"<{tag}", 1)[1].split(f"</{tag}>", 1)[0]
            actual = len(re.findall(rf"<{child}[ />]", block))
            if int(m.group(1)) != actual:
                problems.append(f"styles.xml: {tag} count={m.group(1)} but {actual} present")

        max_xf = int(re.search(r'cellXfs count="(\d+)"', styles).group(1)) - 1
        rels = z.read("xl/_rels/workbook.xml.rels").decode()
        # OPC allows a relationship target to be relative to the part's folder
        # ("worksheets/sheet1.xml") or absolute from the package root
        # ("/xl/worksheets/sheet1.xml"). openpyxl writes the second form.
        sheet_targets = [
            t.lstrip("/") if t.startswith("/") else "xl/" + t
            for t in re.findall(
                r'Type="[^"]*/worksheet"\s+Target="([^"]+)"'
                r'|Target="([^"]+)"\s+Id="[^"]*"', rels)
            for t in [t[0] or t[1]]
            if "worksheets/" in t
        ]
        if len(sheet_targets) != len(re.findall(r"<sheet ", wb)):
            problems.append(
                f"workbook.xml.rels: {len(sheet_targets)} worksheet relationship(s) "
                f"but {len(re.findall(r'<sheet ', wb))} <sheet> entries")

        for part in sheet_targets:
            if part not in names:
                problems.append(f"missing {part} referenced by rels")
                continue
            target = part.split("/")[-1]
            xml = z.read(part).decode()
            problems += check_order(children(xml, "worksheet"), WORKSHEET_ORDER, target)

            rows = [int(r) for r in re.findall(r'<row r="(\d+)"', xml)]
            if rows != sorted(rows):
                problems.append(f"{target}: rows are not in ascending order")
            if len(rows) != len(set(rows)):
                problems.append(f"{target}: duplicate row numbers")

            for row_xml in re.findall(r"<row [^>]*>(.*?)</row>", xml, re.S):
                refs = re.findall(r'<c r="([A-Z]+)(\d+)"', row_xml)
                cols = [sum((ord(ch) - 64) * 26 ** i for i, ch in enumerate(reversed(c)))
                        for c, _ in refs]
                if cols != sorted(cols):
                    problems.append(f"{target}: cells out of column order in a row")
                    break

            for s in re.findall(r'\ss="(\d+)"', xml):
                if int(s) > max_xf:
                    problems.append(f"{target}: style index {s} exceeds cellXfs ({max_xf})")
                    break

            for f in re.findall(r"<f>(.*?)</f>", xml, re.S):
                if f.startswith("="):
                    problems.append(f"{target}: formula stored with a leading '=' ({f[:24]})")
                    break
    return problems


if __name__ == "__main__":
    target = Path(sys.argv[1])
    found = validate(target)
    if found:
        print(f"INVALID: {target.name}")
        for p in found:
            print("  -", p)
        sys.exit(1)
    print(f"valid: {target.name}")
