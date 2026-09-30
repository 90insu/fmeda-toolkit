# Trying it

## The quick way — no install

Double-click **`docs/index.html`**. It opens in your browser and works offline:
the full analysis, the conservatism selector, the editable mechanism table, and
the Excel report. Nothing to install, nothing to configure.

Once the repo is pushed and GitHub Pages is on, the same page is live at
<https://90insu.github.io/fmeda-toolkit/>.

### What to try

- **Move the conservatism selector** between 60, 90 and 99. Watch SPFM drop and
  PMHF climb. That is the derating rules firing, and it is the best thing to
  look at first.
- **Open "Safety mechanisms"** and edit a coverage figure. Every metric
  recalculates. Change ECC from 0.99 to 0.85 and see what it costs SG1.
- **Expand "Conservatism policy changed N values"**. Every change with its
  reason — nothing moves your numbers without appearing here.
- **Switch the failure-rate source to IEC TR 62380.** It warns you the standard
  was withdrawn in 2017.
- **Generate the Excel report**, open it, and edit a `DC_SPF applied` cell on a
  goal sheet. SPFM recalculates, because those are live formulas.

## The Python way — for the library and the tests

```powershell
.\run-windows.ps1
```

Creates an isolated environment in the folder, installs the dependencies, runs
the test suite, prints the metrics, and launches the Streamlit app. Nothing is
installed system-wide; delete the folder to uninstall.

If Python is missing, the script says so. The one detail that matters: tick
**"Add python.exe to PATH"** on the first screen of the installer from
[python.org](https://www.python.org/downloads/).

If PowerShell refuses to run an unsigned script:

```powershell
powershell -ExecutionPolicy Bypass -File .\run-windows.ps1
```

### Command line

```powershell
.\.venv\Scripts\python -m fmeda compute examples\bjb\fmeda.yaml
.\.venv\Scripts\python -m fmeda compute examples\bjb\fmeda.yaml --level worst_case
.\.venv\Scripts\python -m fmeda check   examples\bjb\fmeda.yaml
.\.venv\Scripts\python -m fmeda report  examples\bjb\fmeda.yaml -o report.xlsx
```

## Editing the analysis

`examples\bjb\fmeda.yaml` is plain text — Notepad opens it. Change a `dc_spf`
value, save, re-run, and the metrics move. That is the whole point: the analysis
is text you can edit, diff and review.

Try breaking it deliberately. Set `reaction_time_ms: 500` on `CONTACTOR_FB` and
run `check`. It refuses, because a diagnostic that reacts in 500 ms cannot claim
single-point coverage against a 100 ms FTTI.

## Rebuilding the browser page

`docs/index.html` is generated from `web/`. After editing anything there:

```powershell
.\.venv\Scripts\python web\assemble.py
```

CI fails if you forget — otherwise the live demo would quietly serve old logic.
