<script>
/* ---------------- rendering ---------------- */
let CURRENT = null, ACTIVE_GOAL = null;

function renderSlots(){
  document.getElementById("slots").innerHTML = SLOTS.map(s => {
    const got = state.uploads[s.id] || [];
    return `<div class="slot ${got.length ? "on" : ""}">
      <div class="name">${esc(s.name)}${s.req ? '<span class="req">REQUIRED</span>' : ""}</div>
      <div class="why">${esc(s.why)}</div>
      <input type="file" id="f_${s.id}" accept="${s.accept}" multiple>
      ${got.length ? `<div class="got">${got.map(esc).join("<br>")}</div>` : ""}
    </div>`;
  }).join("");
  for(const s of SLOTS){
    document.getElementById("f_" + s.id).addEventListener("change", e => {
      state.uploads[s.id] = [...e.target.files].map(f => f.name);
      refresh();
    });
  }
}

function renderGate(){
  const docs = present();
  const gate = document.getElementById("gate");
  const blocking = SLOTS.filter(s => s.req && !docs.has(s.id));
  const missing = SLOTS.filter(s => s.cost && !docs.has(s.id));

  if(blocking.length){
    gate.className = "gate miss";
    gate.innerHTML = `<h3>Upload the circuit schematic to analyse your own design</h3>
      <p style="margin:0;font-size:13.5px">A netlist and BOM export from your EDA tool. Until then the results below are the bundled fictional ECU, so there is something to look at.</p>`;
  } else if(missing.length){
    gate.className = "gate miss";
    gate.innerHTML = `<h3>More reference documents give a more precise analysis</h3>
      <ul>${missing.map(s => `<li><b>${esc(s.name)}</b> &mdash; ${esc(s.cost)}</li>`).join("")}</ul>
      <p style="margin:12px 0 0;font-size:13px">You can proceed. The report records what was missing and what it cost.</p>`;
  } else {
    gate.className = "gate ok";
    gate.innerHTML = `<h3>All reference documents provided</h3>
      <p style="margin:0;font-size:13.5px">No evidence tier is degraded by a missing document.</p>`;
  }
}

function bar(value, target){
  const w = Math.max(0, Math.min(1, value));
  const short = value < target;
  return `<div class="bar"><i class="${short ? "short" : ""}" style="width:${(w*100).toFixed(1)}%"></i>
    <span class="tgt" style="left:calc(${(Math.min(1,target)*100).toFixed(1)}% - 1px)"></span></div>`;
}

function renderGoals(){
  document.getElementById("goals").innerHTML = Object.values(CURRENT.goals).map(g => {
    const met = g.spfm >= g.target.spfm && g.lfm >= g.target.lfm;
    const pmhfFrac = g.target.pmhf_fit ? Math.min(1, g.pmhf / g.target.pmhf_fit) : 0;
    return `<div class="goal">
      <div class="hd"><span class="id">${esc(g.id)}</span><span class="asil">ASIL ${esc(g.asil)}</span>
        <span class="pill ${met ? "met" : "not"}">${met ? "TARGETS MET" : "NOT MET"}</span></div>
      <div class="stmt">${esc(g.statement)}</div>
      <div class="metrics">
        <div class="m"><span class="lab">SPFM</span>${bar(g.spfm, g.target.spfm)}
          <span class="val">${pct2(g.spfm)}<small>target ${pct2(g.target.spfm)}</small></span></div>
        <div class="m"><span class="lab">LFM</span>${bar(g.lfm, g.target.lfm)}
          <span class="val">${pct2(g.lfm)}<small>target ${pct2(g.target.lfm)}</small></span></div>
        <div class="m"><span class="lab">PMHF</span>
          <div class="bar"><i class="${g.pmhf > g.target.pmhf_fit ? "short" : ""}" style="width:${(pmhfFrac*100).toFixed(1)}%"></i></div>
          <span class="val">${g.pmhf.toFixed(2)}<small>lower bound &middot; target &lt;${g.target.pmhf_fit}</small></span></div>
      </div></div>`;
  }).join("");
}

function renderMechanisms(){
  const rows = Object.entries(CURRENT.policy.mechs).map(([id, m]) => {
    const spfChanged = Math.abs(m.dc_spf - m.stated_spf) > 1e-9;
    const lfChanged = Math.abs(m.dc_lf - m.stated_lf) > 1e-9;
    const ev = (m.evidence && m.evidence.confidence) || "estimated";
    return `<tr class="mechrow">
      <td class="mono">${esc(id)}</td>
      <td>${esc(m.name)}<div class="why" style="padding:3px 0 0">${esc((m.evidence && m.evidence.reference) || "")}</div></td>
      <td class="n"><input type="number" min="0" max="1" step="0.01" value="${m.stated_spf}" id="in_${esc(id)}_spf" data-m="${esc(id)}" data-k="dc_spf"></td>
      <td class="n ${spfChanged ? "changed" : ""}">${pct(m.dc_spf)}</td>
      <td class="n"><input type="number" min="0" max="1" step="0.01" value="${m.stated_lf}" id="in_${esc(id)}_lf" data-m="${esc(id)}" data-k="dc_lf"></td>
      <td class="n ${lfChanged ? "changed" : ""}">${pct(m.dc_lf)}</td>
      <td class="n">${m.reaction_time_ms == null ? "—" : m.reaction_time_ms}</td>
      <td class="mono" style="font-size:11.5px">${esc(ev)}</td></tr>`;
  }).join("");
  document.getElementById("mechtable").innerHTML =
    `<thead><tr><th>ID</th><th>Name</th><th>DC_SPF stated</th><th>applied</th>
      <th>DC_LF stated</th><th>applied</th><th>reaction ms</th><th>evidence</th></tr></thead><tbody>${rows}</tbody>`;
  for(const input of document.querySelectorAll(".mechrow input")){
    input.addEventListener("change", e => {
      const v = Math.max(0, Math.min(1, parseFloat(e.target.value) || 0));
      const id = e.target.dataset.m;
      state.dc[id] = state.dc[id] || {};
      state.dc[id][e.target.dataset.k] = v;
      refresh();
    });
  }
}

function renderPolicy(){
  const a = CURRENT.policy.actions;
  document.getElementById("polisum").textContent = a.length
    ? `Conservatism policy changed ${a.length} value${a.length > 1 ? "s" : ""}`
    : "Conservatism policy made no changes";
  document.getElementById("politable").innerHTML = a.length
    ? `<thead><tr><th>Target</th><th>Field</th><th>Before</th><th>After</th><th>Reason</th></tr></thead><tbody>${
        a.map(x => `<tr><td class="mono">${esc(x.target)}</td><td class="mono">${esc(x.field)}</td>
          <td class="n">${esc(x.before)}</td><td class="n">${esc(x.after)}</td>
          <td class="why">${esc(x.reason)}</td></tr>`).join("")}</tbody>`
    : `<tbody><tr><td class="why">No derating applied at this level.</td></tr></tbody>`;
}

function renderRows(){
  const ids = Object.keys(CURRENT.goals);
  if(!ACTIVE_GOAL || !ids.includes(ACTIVE_GOAL)) ACTIVE_GOAL = ids[0];
  document.getElementById("goaltabs").innerHTML = ids.map(id =>
    `<button class="btn ghost" data-g="${esc(id)}" style="padding:6px 14px;font-size:13px;${
      id === ACTIVE_GOAL ? "background:var(--accent);color:#fff;border-color:var(--accent);" : ""}">${esc(id)}</button>`).join("");
  for(const b of document.querySelectorAll("#goaltabs button")){
    b.addEventListener("click", () => { ACTIVE_GOAL = b.dataset.g; renderRows(); });
  }
  const g = CURRENT.goals[ACTIVE_GOAL];
  const ranked = g.rows.filter(r => r.cls === "SPF" || r.cls === "RF")
                       .sort((a, b) => (b.split.spf + b.split.rf) - (a.split.spf + a.split.rf));
  document.getElementById("rowtable").innerHTML = ranked.length
    ? `<thead><tr><th>Element</th><th>Failure mode</th><th>Class</th><th>&lambda; mode</th>
        <th>uncovered</th><th>DC</th><th>Mechanism</th><th>Rationale</th></tr></thead><tbody>${
        ranked.map(r => `<tr class="sev"><td class="mono">${esc(r.element)}</td><td class="mono">${esc(r.mode)}</td>
          <td><span class="cls ${r.cls}">${esc(r.cls)}</span></td>
          <td class="n">${r.lambdaMode.toFixed(3)}</td>
          <td class="n">${(r.split.spf + r.split.rf).toFixed(3)}</td>
          <td class="n">${pct(r.dc)}</td>
          <td class="mono" style="font-size:11.5px">${esc(r.mechanisms.join(", ") || "—")}</td>
          <td class="why">${esc(r.why)}</td></tr>`).join("")}</tbody>`
    : `<tbody><tr><td class="why">No single-point or residual faults against this goal.</td></tr></tbody>`;
}

function refresh(){
  CURRENT = compute();
  document.getElementById("levelnote").textContent = LEVEL_BLURB[state.level];
  const s = SRC_INFO[state.src];
  document.getElementById("srcnote").innerHTML = s.withdrawn
    ? `<span style="color:var(--warn);font-weight:600">${esc(s.note)}</span>` : esc(s.note);
  document.getElementById("tempnote").textContent =
    "Recorded in the report. Stress factors are not applied in this version.";
  renderGate(); renderGoals(); renderMechanisms(); renderPolicy(); renderRows();
  document.getElementById("saidxlsx").hidden = true;
}

for(const [id, key] of [["level", "level"], ["src", "src"], ["temp", "temp"]]){
  document.getElementById(id).addEventListener("change", e => { state[key] = e.target.value; refresh(); });
}
renderSlots();
refresh();
</script>
