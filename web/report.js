<script>
/* ------------------------------------------------------------------ *
 * Report assembly. Metric cells are written as live formulas over the
 * rows beneath them, so changing a coverage figure inside the
 * spreadsheet recalculates SPFM there too.
 * ------------------------------------------------------------------ */
const GOAL_COLS = [
  ["Element", 11], ["Part", 20], ["Failure mode", 20], ["Effect", 40],
  ["λ element (FIT)", 14], ["Mode fraction", 13], ["λ mode (FIT)", 13],
  ["Class", 9], ["Safety mechanism", 26], ["DC applied", 11],
  ["λ_SPF", 10], ["λ_RF", 10], ["λ_MPF,L", 11], ["λ_MPF,D", 11], ["λ_S", 10],
  ["Rationale", 80]
];

function goalSheet(g){
  const rows = [];
  rows[0] = [{v: `${g.id} — ASIL ${g.asil}`, s: 3}];
  rows[1] = [g.statement];
  rows[2] = [{v: `FTTI ${g.ftti} ms · safe state: ${g.safe_state || "—"} · DC combination: ${DATA.dc_combination || "max"}`, s: 9}];
  rows[4] = GOAL_COLS.map(c => ({v: c[0], s: 2}));

  const sorted = [...g.rows].sort((a, b) => a.element.localeCompare(b.element) || a.mode.localeCompare(b.mode));
  let r = 5;
  for(const row of sorted){
    const crit = row.cls === "SPF" || row.cls === "RF";
    const txt = crit ? 10 : 12;
    rows[r] = [
      {v: row.element, s: txt}, {v: row.part, s: txt}, {v: row.mode, s: txt}, {v: row.effect, s: txt},
      {v: row.lambdaEl, s: 4}, {v: row.fraction, s: 5}, {v: row.lambdaMode, s: 4},
      {v: row.cls, s: txt}, {v: row.mechanisms.join(", ") || "—", s: txt}, {v: row.dc, s: 5},
      {v: row.split.spf, s: 4}, {v: row.split.rf, s: 4}, {v: row.split.mpf_l, s: 4},
      {v: row.split.mpf_d, s: 4}, {v: row.split.safe, s: 4},
      {v: row.why, s: 8}
    ];
    r++;
  }
  const first = 6, last = r, totals = r + 1;   // 1-based spreadsheet rows
  const tRow = [{v: "TOTAL", s: 1}];
  for(const col of [7, 11, 12, 13, 14, 15]){
    tRow[col - 1] = {f: `SUM(${colName(col)}${first}:${colName(col)}${last})`, s: 6};
  }
  rows[totals - 1] = tRow;

  const m = totals + 2;                          // 1-based row of the first metric
  const sr = `(K${totals}+L${totals}+M${totals}+N${totals})`;
  rows[m - 1] = [{v: "λ safety-related (FIT)", s: 1}, null, null, null, {f: sr, s: 6}];
  rows[m]     = [{v: "SPFM", s: 1}, null, null, null,
                 {f: `1-(K${totals}+L${totals})/${sr}`, s: 7}, {v: g.target.spfm, s: 5}];
  rows[m + 1] = [{v: "LFM", s: 1}, null, null, null,
                 {f: `IF((${sr}-K${totals}-L${totals})=0,1,1-M${totals}/(${sr}-K${totals}-L${totals}))`, s: 7},
                 {v: g.target.lfm, s: 5}];
  rows[m + 2] = [{v: "PMHF (FIT) — lower bound", s: 1}, null, null, null,
                 {f: `K${totals}+L${totals}`, s: 6}, {v: g.target.pmhf_fit, s: 4}];
  rows[m + 3] = [{v: "Dual-point failure term is not modelled in this version.", s: 9}];

  return {name: g.id, rows, widths: GOAL_COLS.map(c => c[1]), freeze: 5, metricRow: m};
}

function buildReport(){
  const goals = Object.values(CURRENT.goals);
  const sheets = [];
  const metricRow = {};

  const summary = {name: "Summary", rows: [], widths: [26, 8, 11, 11, 11, 11, 13, 11, 13], freeze: 4};
  sheets.push(summary);
  for(const g of goals){
    const s = goalSheet(g);
    metricRow[g.id] = s.metricRow;
    sheets.push(s);
  }

  /* ---- Summary ---- */
  const S = summary.rows;
  S[0] = [{v: `FMEDA — ${DATA.meta.item}`, s: 3}];
  S[1] = [{v: `${DATA.meta.variant || ""} · conservatism: ${levelLabel(state.level)} · source: ${SRC_INFO[state.src].label} · generated ${new Date().toISOString().slice(0, 16).replace("T", " ")}`, s: 9}];
  S[3] = ["Safety goal", "ASIL", "SPFM", "target", "LFM", "target", "PMHF (FIT)", "target", "Verdict"]
           .map(v => ({v, s: 2}));
  goals.forEach((g, i) => {
    const row = 5 + i, m = metricRow[g.id];
    const met = g.spfm >= g.target.spfm && g.lfm >= g.target.lfm && g.pmhf <= g.target.pmhf_fit;
    S[row - 1] = [
      {v: g.id, s: 1}, {v: g.asil, s: 12},
      {f: `'${g.id}'!E${m + 1}`, s: 5}, {v: g.target.spfm, s: 5},
      {f: `'${g.id}'!E${m + 2}`, s: 5}, {v: g.target.lfm, s: 5},
      {f: `'${g.id}'!E${m + 3}`, s: 4}, {v: g.target.pmhf_fit, s: 4},
      {f: `IF(AND(C${row}>=D${row},E${row}>=F${row},G${row}<=H${row}),"MET","NOT MET")`, s: met ? 13 : 14}
    ];
  });
  let n = 5 + goals.length + 2;
  S[n - 1] = [{v: "Read this before quoting any figure above", s: 1}];
  [
    "PMHF is a LOWER BOUND — single-point and residual terms only. The dual-point failure term is not modelled in this version.",
    `Conservatism level '${levelLabel(state.level)}' applied ${CURRENT.policy.actions.length} derating action(s). See the Policy sheet for every one.`,
    "The conservatism level is a set of deterministic derating rules, not a statistical confidence interval. It does not mean the result is 60/90/99% likely.",
    `${CURRENT.policy.queue.length} item(s) need analyst resolution. See the Review queue sheet.`,
    "Targets come from ISO 26262-5:2018 Tables 4, 5 and 6, which are informative. Confirm against your own copy of the standard.",
    "This analysis is a draft until an analyst has ratified every row."
  ].forEach((t, i) => { S[n + i] = [{v: "• " + t, s: 11}]; });

  /* ---- Mechanisms ---- */
  const mech = {name: "Mechanisms", rows: [], widths: [16, 34, 14, 14, 14, 14, 13, 16, 30, 50], freeze: 3};
  mech.rows[0] = [{v: "Safety mechanism register", s: 3}];
  mech.rows[2] = ["ID", "Name", "DC_SPF stated", "DC_SPF applied", "DC_LF stated", "DC_LF applied",
                  "Reaction (ms)", "Evidence", "Reference", "Rationale"].map(v => ({v, s: 2}));
  Object.entries(CURRENT.policy.mechs).forEach(([id, m], i) => {
    const ev = m.evidence || {};
    const changed = Math.abs(m.dc_spf - m.stated_spf) > 1e-9;
    mech.rows[3 + i] = [
      {v: id, s: 12}, {v: m.name, s: 12},
      {v: m.stated_spf, s: 5}, {v: m.dc_spf, s: changed ? 10 : 5},
      {v: m.stated_lf, s: 5}, {v: m.dc_lf, s: 5},
      m.reaction_time_ms == null ? {v: "—", s: 12} : {v: m.reaction_time_ms, s: 12},
      {v: ev.confidence || "estimated", s: 12}, {v: ev.reference || "", s: 12},
      {v: ev.rationale || "", s: 8}
    ];
  });
  sheets.push(mech);

  /* ---- Policy ---- */
  const pol = {name: "Policy", rows: [], widths: [24, 16, 12, 12, 70], freeze: 5};
  pol.rows[0] = [{v: `Conservatism policy — ${levelLabel(state.level)}`, s: 3}];
  pol.rows[1] = [{v: LEVEL_BLURB[state.level], s: 11}];
  pol.rows[2] = [{v: "Deterministic derating rules. The same inputs at the same level always produce the same numbers. The level is not a probability.", s: 9}];
  pol.rows[4] = ["Target", "Field", "Before", "After", "Reason"].map(v => ({v, s: 2}));
  if(CURRENT.policy.actions.length){
    CURRENT.policy.actions.forEach((a, i) => {
      pol.rows[5 + i] = [{v: a.target, s: 12}, {v: a.field, s: 12},
                         {v: a.before, s: 12}, {v: a.after, s: 12}, {v: a.reason, s: 8}];
    });
  } else {
    pol.rows[5] = [{v: "No derating applied at this level.", s: 12}];
  }
  sheets.push(pol);

  /* ---- Review queue ---- */
  const rev = {name: "Review queue", rows: [], widths: [5, 100, 20, 14], freeze: 4};
  rev.rows[0] = [{v: "Open items for the analyst", s: 3}];
  rev.rows[1] = [{v: "Each line is something the tool could not decide. Until these are resolved the analysis is a draft, whatever the metrics say.", s: 9}];
  rev.rows[3] = ["#", "Item", "Resolved by", "Date"].map(v => ({v, s: 2}));
  if(CURRENT.policy.queue.length){
    CURRENT.policy.queue.forEach((q, i) => {
      rev.rows[4 + i] = [{v: i + 1, s: 12}, {v: q, s: 8}, {v: "", s: 11}, {v: "", s: 11}];
    });
  } else {
    rev.rows[4] = [null, {v: "Nothing outstanding at this conservatism level.", s: 12}];
  }
  sheets.push(rev);

  /* ---- Assumptions ---- */
  const asm = {name: "Assumptions", rows: [], widths: [8, 90, 12, 20], freeze: 3};
  asm.rows[0] = [{v: "Assumption register", s: 3}];
  asm.rows[2] = ["ID", "Statement", "Status", "Owner"].map(v => ({v, s: 2}));
  Object.entries(DATA.assumptions || {}).forEach(([id, a], i) => {
    asm.rows[3 + i] = [{v: id, s: 1}, {v: a.statement, s: 8}, {v: a.status || "open", s: 12}, {v: a.owner || "—", s: 12}];
  });
  sheets.push(asm);

  /* ---- Inputs / provenance ---- */
  const inp = {name: "Inputs", rows: [], widths: [26, 46, 60]};
  inp.rows[0] = [{v: "Provenance", s: 3}];
  inp.rows[1] = [{v: "What went in, so this run can be reproduced and challenged.", s: 9}];
  const src = SRC_INFO[state.src];
  const facts = [
    ["Item", DATA.meta.item], ["Variant", DATA.meta.variant || "—"],
    ["Generated", new Date().toISOString().slice(0, 16).replace("T", " ")],
    ["Failure rate source", src.label + (src.withdrawn ? "  — WITHDRAWN STANDARD" : "")],
    ["Temperature profile", document.getElementById("temp").selectedOptions[0].textContent.trim()],
    ["Mission lifetime (h)", DATA.mission_profile.lifetime_h],
    ["Conservatism level", levelLabel(state.level)],
    ["DC combination", DATA.dc_combination || "max"],
    ["Produced by", "FMEDA Bench (browser build) — metrics identical to the fmeda-toolkit Python core"]
  ];
  facts.forEach((f, i) => { inp.rows[3 + i] = [{v: f[0], s: 1}, {v: f[1], s: 12}]; });

  let k = 3 + facts.length + 1;
  inp.rows[k] = [{v: "Documents provided", s: 1}]; k += 1;
  inp.rows[k] = ["Category", "File"].map(v => ({v, s: 2})); k += 1;
  const docs = present();
  if(docs.size){
    for(const slot of SLOTS){
      for(const name of (state.uploads[slot.id] || [])){
        inp.rows[k] = [{v: slot.name, s: 12}, {v: name, s: 12}]; k += 1;
      }
    }
  } else {
    inp.rows[k] = [{v: "—", s: 12}, {v: "None. Results are from the bundled fictional example.", s: 12}]; k += 1;
  }

  const missing = SLOTS.filter(s => s.cost && !docs.has(s.id));
  if(missing.length){
    k += 1;
    inp.rows[k] = [{v: "Documents NOT provided, and what it cost", s: 1}]; k += 1;
    for(const s of missing){ inp.rows[k] = [{v: s.name, s: 12}, {v: s.cost, s: 11}]; k += 1; }
  }
  sheets.push(inp);

  return buildWorkbook(sheets);
}

document.getElementById("xlsx").addEventListener("click", () => {
  const bytes = buildReport();
  const stamp = new Date().toISOString().slice(0, 10);
  const name = `FMEDA_${(DATA.meta.variant || "report").replace(/[^A-Za-z0-9._-]/g, "_")}_${state.level}_${stamp}.xlsx`;
  const blob = new Blob([bytes], {type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"});
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url; a.download = name;
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 4000);
  const said = document.getElementById("saidxlsx");
  said.textContent = `Saved ${name} — check your Downloads folder`;
  said.hidden = false;
});
</script>
