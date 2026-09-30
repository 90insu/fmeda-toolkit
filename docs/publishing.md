# Publishing checklist

Everything here is done in a browser or a terminal. The repo is ready; this is the order to do it in.

## 1 · Create the repo

On [github.com/new](https://github.com/new): name it **fmeda-toolkit**, set it **Public**, and add nothing — no README, no .gitignore, no license. Those either exist here already or come in step 3.

Then, in `D:\fmeda-toolkit`:

```powershell
git init
git add .
git commit -m "ISO 26262-5 hardware metrics from a versioned failure-rate table"
git branch -M main
git remote add origin https://github.com/90insu/fmeda-toolkit.git
git push -u origin main
```

If git asks who you are, set it once:

```powershell
git config --global user.name "Insoo"
git config --global user.email "90insu@gmail.com"
```

> `.venv/` is already in `.gitignore`, so the several hundred megabytes of installed packages in your folder will not be uploaded. Check the commit is small — if `git add .` reports thousands of files, stop and say so.

## 2 · Turn on the live demo

This is the step that matters most and takes the least time.

**Settings → Pages →** under *Build and deployment*, set Source to **Deploy from a branch**, branch **main**, folder **/docs** → Save.

A minute later the demo is live at:

```
https://90insu.github.io/fmeda-toolkit/
```

That URL is already written into the README's hero link, so it starts working on its own. GitHub Pages is free, needs no separate account, and serves `docs/index.html` exactly as it is — no build step, no cold start.

## 3 · Add the license

`pyproject.toml` declares Apache-2.0 but there is no `LICENSE` file, because shipping a license text I had not verified would be worse than shipping none. GitHub inserts the authoritative text:

**Add file → Create new file →** type `LICENSE` as the filename → a **Choose a license template** button appears on the right → pick **Apache License 2.0** → commit.

Do this before anyone clones it. A repo whose `pyproject.toml` claims a license the tree does not contain is a real problem, not a cosmetic one.

## 4 · Repo settings

Two minutes, and this is what makes it findable.

- **Description** — `ISO 26262-5 hardware architectural metrics (SPFM, LFM, PMHF) from a versioned failure-rate table instead of a spreadsheet.`
- **Website** — `https://90insu.github.io/fmeda-toolkit/`
- **Topics** — `iso26262` `functional-safety` `fmeda` `automotive` `asil` `reliability` `safety-critical` `python`
- Turn off Wikis and Projects. Leave Issues on.

Set these from the gear icon beside **About** on the repo's front page.

## 5 · Check CI is green

The Actions tab should show three workflows passing on the first push: the test matrix (Ubuntu and Windows, Python 3.11–3.13), a check that `docs/index.html` is rebuilt from its sources, and a run of the metrics on the worked example.

The badge in the README goes live once `main` has run. **A red badge on a public repo is worse than no badge** — if something fails, fix it or remove the badge before sharing the link.

## 6 · Check the demo before you share it

Open the Pages URL on your phone as well as your laptop, and confirm:

- the metrics render and the conservatism selector moves them
- the mechanism table accepts an edit and the numbers change
- **Generate Excel report** downloads a file that opens in Excel without a repair prompt

That last one is the check that failed once already. Do it on the live URL, not just locally.

## 7 · Pin it

Profile → **Customize your pins** → select `fmeda-toolkit`. With one repo it is the whole shelf; keep it pinned as others land.

## 8 · Then swap the profile README

Phase 1 goes up now — it makes no claims that need a repo. Once this is live and CI is green, swap to phase 2 and delete the table rows for repos that do not exist yet.

---

## What's deliberately not done

State these in the README rather than hoping nobody notices. In safety tooling a limitations section builds credibility rather than costing it, and its absence is what marks a toy.

- Netlist ingest. Both front ends run against the bundled YAML.
- The PMHF dual-point term.
- IEC 61709 stress factors driven by the temperature profile.
- The AI proposal layer and its eval set — the piece that turns this from a calculator into a portfolio project.
