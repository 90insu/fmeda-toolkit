# fmeda-toolkit input schema

Two file kinds, both YAML.

| Kind | `schema:` | Holds | Reused across projects |
|---|---|---|---|
| Library | `fmeda.library/v1` | Failure rates and failure-mode distributions | Yes |
| Analysis | `fmeda.analysis/v1` | Goals, architecture, mechanisms, classification | No |

The split is the most important decision in the schema. A library answers *what does this part do when it breaks, and how often*. An analysis answers *in this design, does that matter, and what catches it*. Keeping them in one file is what makes FMEDA spreadsheets unmaintainable — the same MCU gets re-entered per project and the numbers drift apart.

---

## 1. Library

```yaml
schema: fmeda.library/v1

library:
  id: <str>                      # referenced as <id>.<part_id> when disambiguating
  description: <str>
  source:
    reference: <str>             # cite a standard or document. Never paste its text.
    revision: <str>
    conditions: <str>            # temperature, derating, mission — lambda is meaningless without it
  confidence: measured | field_data | supplier_claim | standard | estimated

parts:
  <part_id>:
    description: <str>
    lambda_fit: <float>          # failures per 1e9 h, for ONE instance
    failure_modes:
      <mode_id>:
        fraction: <float>        # 0..1, must sum to 1.0 across the part
        description: <str>       # optional
```

`lambda_fit` is always per instance. Multiplicity lives in the analysis (`quantity`), so a library entry never has to be duplicated for an 8-up resistor array.

---

## 2. Analysis

### 2.1 `meta`

```yaml
meta:
  item: <str>
  variant: <str>
  analyst: <str>
  date: <date>
  status: draft | reviewed | released
  libraries: [<path>, ...]       # relative to this file
```

### 2.2 `mission_profile`

```yaml
mission_profile:
  lifetime_h: <float>                  # PMHF integration horizon
  mpf_detection_interval_h: <float>    # opportunity to clear a latent fault
```

SPFM and LFM do not depend on either value. PMHF depends on both. Keeping them out of the element data means a lifetime change is one edit, not a column rewrite.

### 2.3 `safety_goals`

```yaml
safety_goals:
  <goal_id>:
    statement: <str>
    asil: A | B | C | D
    ftti_ms: <float>
    safe_state: <str>
```

`ftti_ms` is load-bearing, not documentation — see validation rule V4.

### 2.4 `targets`

```yaml
targets:
  <ASIL>: { spfm: <float>, lfm: <float>, pmhf_fit: <float> }
```

Optional. Defaults follow ISO 26262-5:2018 Tables 4, 5 and 6:

| ASIL | SPFM | LFM | PMHF |
|---|---|---|---|
| B | ≥ 90% | ≥ 60% | < 100 FIT |
| C | ≥ 97% | ≥ 80% | < 100 FIT |
| D | ≥ 99% | ≥ 90% | < 10 FIT |

Those tables are informative and OEMs routinely run tighter, so make the defaults overridable and print which set was used in every report. Verify them against your own copy before shipping — don't take them from a README.

### 2.5 `mechanisms`

```yaml
mechanisms:
  <mech_id>:
    name: <str>
    dc_spf: <float>              # 0..1, coverage w.r.t. single-point/residual faults
    dc_lf: <float>               # 0..1, coverage w.r.t. latent faults
    reaction_time_ms: <float>    # detection + reaction, optional
    covers_goals: [<goal_id>, ...]
    implemented_by: [<element_id>, ...]
    evidence:
      reference: <str>
      rationale: <str>
      confidence: measured | field_data | supplier_claim | standard | estimated | expert_judgement
```

Three decisions worth defending:

**Coverage is named, not inlined.** One ECC claim serves fifteen failure modes. Raising it from 0.99 to 0.999 should be one edit and one diff line, with everything that depends on it moving together. This is the single biggest ergonomic win over a spreadsheet and the reason a reviewer can actually review a change.

**`dc_spf` and `dc_lf` are separate.** They are genuinely different quantities and conflating them is the most common error in hand-built FMEDAs. A power-up self test has `dc_spf: 0.0` against a 100 ms FTTI — it cannot react in time — and `dc_lf: 0.90`, because clearing latent faults is exactly what it is for. One number cannot express that.

**Mechanisms have `implemented_by`.** A mechanism is hardware and can itself fail. Linking it to the elements that realise it is what lets the tool reason about latent faults in the diagnostic rather than making you assert LFM by hand.

### 2.6 `dc_combination`

```yaml
dc_combination: max | independent
```

`max` takes the best single claim on a failure mode. `independent` computes `1 - Π(1 - dc)`, which is only defensible with a dependent-failure analysis showing no shared failure cause (ISO 26262-9 Clause 7). Default to `max`, and print the chosen policy in every report — it surfaces an argument that spreadsheets bury inside a formula bar.

### 2.7 `elements`

```yaml
elements:
  - id: <str>
    description: <str>
    part: <part_id>              # resolved against loaded libraries
    quantity: <int>              # default 1
    safety_related: <bool>       # optional shorthand; false forces every mode safe
    modes:
      <mode_id>:                 # must exist in the part's failure_modes
        effect: <str>
        violates: [<goal_id>, ...]
        mechanisms: [<mech_id>, ...]
        latent_for: [<goal_id>, ...]
```

`violates` is the classification that drives everything:

- `violates: []` — the fault does not by itself lead to a goal violation.
- `violates: [SG1]` — safety-related with respect to SG1. The covered fraction becomes a multiple-point fault; the uncovered fraction becomes SPF (no mechanism claimed) or RF (a mechanism is claimed but incomplete).

`latent_for` marks a fault that violates nothing alone but disables a diagnostic — a dead watchdog, an open feedback divider. It is the numerator of LFM and the reason LFM can't be inferred from `violates` alone.

An element may be safety-related for one goal and not another. Per-goal classification is the case hand-built FMEDAs get wrong most often, because a single "safety related Y/N" column can't hold it.

### 2.8 `assumptions`

```yaml
assumptions:
  <id>:
    statement: <str>
    status: open | agreed | closed
    owner: <str>
```

Cheap to implement, and an assumption register is the artifact assessors ask for and nobody has.

---

## 3. Classification and metrics

Per element, per safety goal, with `λ_e = lambda_fit × quantity` and mode fraction `f_m`:

```
λ_m = λ_e × f_m
DC_spf(m) = combine({mech.dc_spf : mech in m.mechanisms, goal in mech.covers_goals})
DC_lf(m)  = combine({mech.dc_lf  : mech in m.mechanisms, goal in mech.covers_goals})
```

Mechanisms that do not list the goal in `covers_goals` contribute nothing. Then:

| Condition | Classification |
|---|---|
| `goal not in violates` and `goal not in latent_for` | `λ_S` (safe) |
| `goal in violates`, no mechanism | `λ_SPF = λ_m` |
| `goal in violates`, mechanism present | `λ_RF = λ_m × (1 − DC_spf)`, `λ_MPF,D = λ_m × DC_spf` |
| `goal in latent_for` | `λ_MPF,L = λ_m × (1 − DC_lf)`, `λ_MPF,D = λ_m × DC_lf` |

Metrics:

```
SPFM = 1 − Σ(λ_SPF + λ_RF) / Σλ_safety_related

LFM  = 1 − Σλ_MPF,L / (Σλ_safety_related − Σλ_SPF − Σλ_RF)
```

`Σλ_safety_related` excludes `λ_S`. Getting the denominators right is most of the work; they are also the part reviewers check first.

**PMHF.** Ship v0.1 computing `Σλ_SPF + Σλ_RF` only, print it as a **lower bound**, and say so in the output and the README. The dual-point term needs explicit DPF pair enumeration, which is a v0.2 feature (`dpf_pairs:`). A tool that reports a conservative bound and names what it omits is credible; one that reports a confident wrong PMHF is worse than the spreadsheet it replaced.

---

## 4. Validation rules

Structural rules the parser enforces before any arithmetic. These are what make the tool worth using — each one is a real defect that survives in spreadsheets.

| | Rule | Why |
|---|---|---|
| V1 | `failure_modes` fractions sum to 1.0 ± 1e-6 per part | Lost or double-counted failure rate |
| V2 | Every `modes` key exists in the referenced part | Renamed mode silently drops from the analysis |
| V3 | Every referenced `goal_id`, `mech_id`, `part_id`, element in `implemented_by` resolves | Typo'd reference reads as "no coverage" and skews the result |
| V4 | If `dc_spf > 0`, `reaction_time_ms ≤ ftti_ms` for every goal in `covers_goals` | The classic unjustifiable claim: coverage that can't react in time |
| V5 | `0 ≤ dc_spf, dc_lf ≤ 1`; `lambda_fit ≥ 0`; `quantity ≥ 1` | — |
| V6 | A mode with `mechanisms` but empty `violates` is an error | Coverage claimed on a fault that violates nothing — usually a missed classification |
| V7 | `dc_combination: independent` requires an `assumptions` entry referencing it | Forces the DFA argument to exist in writing |
| V8 | Warn when any `dc_spf ≥ 0.99` has `confidence: estimated` or `expert_judgement` | Highest-leverage number in the file resting on the weakest evidence |
| V9 | Warn on any element with no `modes` entry for a goal it could affect | Silent omission, the failure mode of FMEDA itself |

V4, V7 and V8 are the ones a practising engineer will notice. They are checks nobody can run on a spreadsheet, and they're cheap — implement them in v0.1.

---

## 5. Output

```
fmeda compute examples/bjb/fmeda.yaml --goal SG1
```

```
  SG1 · ASIL D · FTTI 100 ms                     dc_combination: max
  ─────────────────────────────────────────────────────────────────────
  Element   λ (FIT)   λ_SPF    λ_RF   λ_MPF,L   λ_MPF,D     λ_S
  U1           62.0    0.00    2.68      0.31     59.01    0.00
  U3           48.0    0.00    0.72      2.16     33.12   12.00
  U4            8.0    0.00    0.18      0.44      7.38    0.00
  R7            2.0    0.00    0.00      0.13      1.17    0.70
  K1           90.0    0.00    2.93      0.00     55.57   31.50
  C12          14.4    0.00    0.00      0.00      0.00   14.40
  ─────────────────────────────────────────────────────────────────────
  λ_safety_related  165.80 FIT        λ_total  224.40 FIT

  SPFM  96.08%  (target 99.00%)   FAIL
  LFM   98.09%  (target 90.00%)   PASS
  PMHF   6.50 FIT lower bound — dual-point term not modelled (v0.1)

  Top SPFM contributors
    1. K1  fails_open        1.80 FIT   dc_spf 0.95   CONTACTOR_FB
    2. K1  coil_short        1.13 FIT   dc_spf 0.95   CONTACTOR_FB
    3. U1  core_halt         0.93 FIT   dc_spf 0.90   WDG_EXT
```

Those are the real figures from `examples/bjb/`, not illustrative ones. The example deliberately misses its ASIL D SPFM target — a first-pass architecture that doesn't close is more useful as a fixture than one that does, because it gives the contributor ranking something to rank and the `--target` mode something to solve.

The contributor ranking is the feature that earns repeat use. `--target D` should answer *which element is costing me the metric and what would it take* — that's the question people open the spreadsheet to answer, and answering it directly is what makes this a tool rather than a calculator.

Emit machine-readable output too (`--json`), so results are diffable in CI and a regression on a metric fails a pull request.
