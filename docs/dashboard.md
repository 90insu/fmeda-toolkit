# Dashboard architecture

The upload-to-report flow, and the line between what the tool computes and what it proposes.

---

## 1. Layering

```
  app.py                     Streamlit. Presentation only. Owns no arithmetic.
    │
    ├── fmeda.ingest         netlist + BOM → elements (deterministic)
    ├── fmeda.propose        LLM layer → CANDIDATE classifications + rationale
    ├── fmeda.policy         conservatism derating (deterministic)
    ├── fmeda.metrics        classification + SPFM / LFM / PMHF (deterministic)
    └── fmeda.report         XLSX writer
```

The rule that makes this defensible: **`metrics` and `policy` never import an LLM client and never import the UI.** They take a validated `Analysis` and return numbers. That means the same engine runs under pytest, in CI against a repository of analyses, and from the CLI — and it means "did the AI change my numbers" has an auditable answer, because the AI cannot reach them except through a ratified `Analysis`.

A dashboard that owns the arithmetic can't be unit tested and can't be trusted. This is also the story that makes the project interesting to an AV safety organization: it demonstrates you know where to put the model.

---

## 2. Pipeline

| Stage | Input | Output | Nature |
|---|---|---|---|
| 1 Ingest | Netlist + BOM | Element list with refdes, part number, quantity | Deterministic |
| 2 Match | Part numbers | Library entries: λ, failure-mode distribution | Deterministic + fuzzy fallback |
| 3 Topology | Netlist | Net graph, which elements sit in which signal path | Deterministic |
| 4 Propose | Topology + reference docs | Candidate `effect`, `violates`, `latent_for`, mechanism assignment, **rationale** | **LLM — proposals only** |
| 5 Ratify | Candidates | Analyst accepts, edits or rejects each row | Human |
| 6 Policy | Ratified analysis | Derated analysis + action log | Deterministic |
| 7 Compute | Derated analysis | SPFM / LFM / PMHF per goal | Deterministic |
| 8 Report | Everything above | XLSX | Deterministic |

Stage 5 is not optional and not a formality. **No AI-proposed row enters a released FMEDA without a human ratifying it**, and the report marks the origin of every row. Ship this from v0.1 — retrofitting a review gate onto a tool that already auto-writes numbers never happens.

### Why netlist + BOM, and not a PDF

Recovering connectivity from a PDF schematic means symbol recognition plus net tracing plus junction-dot disambiguation. It is a research problem, the failure modes are silent, and a wrong net is worse than no net because it produces a confident wrong propagation. Every EDA tool exports a netlist. Requiring one is a real constraint that makes the rest of the tool honest — say so in the UI rather than apologising for it.

### What the LLM is actually good for here

Not computing metrics — that is arithmetic and it should never touch it. What it is genuinely good at:

- Reading a technical safety concept and extracting goals, ASIL and FTTI into structured fields.
- Given a net topology and a design document, proposing what a given failure mode *does* — "R7 open makes the feedback divider read low, so the plausibility check sees a closed contactor regardless of true state."
- Drafting the rationale text. The classification is a rule; the explanation of why the effect violates the goal is language work.
- Flagging elements the analyst has not classified but that sit in a safety-related signal path.

Every one of those is a proposal with a citation to the document that supported it, landing in the review queue.

---

## 3. Conservatism policy

The 60 / 90 / 99 selector. Implemented in `fmeda/policy.py`.

**It is a set of deterministic derating rules, not a statistical confidence interval.** Same inputs at the same level always produce the same numbers. Say this in the UI, in the report, and in the README — "99% confident" is a claim nobody can support and it is the first thing an assessor will take apart. What the levels express is *how much unverified coverage you are willing to credit*.

Coverage multiplier by evidence tier:

| Evidence | Tier | 60 Nominal | 90 Conservative | 99 Worst case |
|---|---|---|---|---|
| measured / field_data | 4 | 1.00 | 1.00 | 1.00 |
| standard | 3 | 1.00 | 0.95 | 0.90 |
| supplier_claim | 2 | 1.00 | 0.90 | 0.00 |
| estimated / expert_judgement | 1 | 1.00 | 0.60 | 0.00 |

Plus:

- **Unclassified failure modes** — nominal treats them as safe; conservative as latent; worst case as single-point faults.
- **Mechanism with no stated reaction time** — worst case credits zero single-point coverage, because FTTI compliance cannot be demonstrated.
- **Missing supplier safety manual** — every `supplier_claim` drops one evidence tier. This is what makes "more reference documents give a more precise analysis" a true statement about the tool rather than a marketing line: the completeness gate feeds the arithmetic through a rule you can point at.

On the worked example the levels separate cleanly, which is the point — a selector that barely moves the result is decoration:

| Level | SG1 SPFM | SG1 PMHF | SG2 SPFM | SG2 PMHF |
|---|---|---|---|---|
| 60 Nominal | 96.08% | 6.50 FIT | 91.70% | 8.70 FIT |
| 90 Conservative | 91.81% | 13.58 FIT | 79.53% | 21.46 FIT |
| 99 Worst case | 86.92% | 21.68 FIT | 61.26% | 40.62 FIT |

---

## 4. Report

One workbook. Excel formulas, not pasted values — change a DC in the sheet and the metrics move, which is how these documents get used in a design review.

| Sheet | Holds |
|---|---|
| **Summary** | Metrics per goal against target, verdict, and the caveats a reader must see before quoting a figure |
| **SG1, SG2, …** | Full FMEDA per goal: every element × failure mode, λ split by fault class, and the **rationale** column |
| **Mechanisms** | DC register — stated vs. applied, evidence tier, reference, reaction time |
| **Policy** | Every value the conservatism level changed, with the reason |
| **Review queue** | What the tool could not decide, with columns for who resolved it and when |
| **Assumptions** | The assumption register |
| **Inputs** | Provenance: documents with SHA-256, failure-rate source, temperature profile, level, timestamp — and what each *missing* document cost |

The rationale column is generated from the classification, not written alongside it, so the comment can never drift away from the number beside it. A residual fault row reads:

> Residual fault. The effect 'Corrupted state variable, possible spurious open command' violates SG1; SECDED ECC on data SRAM with background scrub claims 59.4% coverage (max combination), leaving 5.538 FIT uncovered.

**Provenance is the sheet an assessor opens first.** An FMEDA that cannot say which documents, which failure-rate source and which conservatism level produced it is not reviewable.

---

## 5. Component data sources

| Source | Status |
|---|---|
| IEC 61709:2017 | Current |
| SN 29500 | Current, widely used |
| IEC TR 62380:2004 | **Withdrawn 2017-02-17, replaced by IEC 61709:2017** |

Keep IEC 62380 selectable — analyses built on it still exist and comparing against them is legitimate — but label it as withdrawn wherever it appears and flag any report generated from it. Offering it as a peer option is the first thing a reliability engineer would flag.

Note also that IEC 61709 and SN 29500 are not interchangeable: 61709 gives reference conditions and stress models, SN 29500 gives failure rate values per part family. A real implementation applies 61709 stress factors *to* a base rate, and the temperature profile selection is what drives those factors. v0.1 can use flat rates at the profile temperature and say so.

---

## 6. Build sequence

Realistically this is six to ten weekends, not one. Ordered so each step ships something that works.

1. **Core + report** — `models`, `metrics`, `policy`, `report`, bundled example. *Done.*
2. **Dashboard shell** — uploads, completeness gate, policy selector, metrics, download. *Done.*
3. **Netlist ingest** — start with KiCad; it's the only format you can ship a public example with. Parse to elements, match BOM to library, report unmatched parts as a first-class result rather than a crash.
4. **Topology** — net graph, reachability from each element to the elements named in the safety concept.
5. **Proposal layer** — LLM proposes effect and classification with citations; everything lands in the review queue; ratification UI.
6. **Eval** — score the proposal layer against your own expert labels on the fictional ECU. Publish the failure taxonomy. This is the part that makes it a portfolio piece rather than a demo.
7. **Stress models** — IEC 61709 factors driven by the temperature profile.
8. **DPF pairs** — complete the PMHF term.

Steps 1 and 2 already run. Step 3 is the next real work, and step 6 is the one worth the most.

---

## 7. Known limitations, to state plainly in the README

- PMHF is a lower bound; the dual-point term is not modelled.
- Failure rates are flat at the profile temperature; IEC 61709 stress factors are not yet applied.
- Part matching is exact-match with a fuzzy fallback; an unmatched part is reported, never silently dropped.
- The proposal layer has not been evaluated against expert labels yet — until step 6, treat every proposal as unvalidated.
- The bundled example is fictional throughout.

A limitations section is what separates a credible safety tool from a toy, and in this field it builds trust rather than costing it.
