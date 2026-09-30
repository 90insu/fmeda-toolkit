<script>
const DATA = __DATA__;

/* ------------------------------------------------------------------ *
 * Reference data. Mirrors src/fmeda/policy.py and metrics.py; the
 * Python suite and this page must agree, and tests/test_web_parity.py
 * is what keeps them honest.
 * ------------------------------------------------------------------ */
const TIER = {measured:4, field_data:4, standard:3, supplier_claim:2, estimated:1, expert_judgement:1};
const DERATE = {
  nominal:      {4:1.00, 3:1.00, 2:1.00, 1:1.00},
  conservative: {4:1.00, 3:0.95, 2:0.90, 1:0.60},
  worst_case:   {4:1.00, 3:0.90, 2:0.00, 1:0.00}
};
const LEVEL_BLURB = {
  nominal: "Coverage accepted as stated. Unclassified failure modes treated as safe. For early design iteration, not a release argument.",
  conservative: "Coverage derated by strength of evidence. Unclassified failure modes treated as latent. The default for a working analysis.",
  worst_case: "Only coverage you can independently evidence survives. Unverified supplier claims go to zero and unclassified modes become single-point faults."
};
const DEFAULT_TARGETS = {A:{spfm:0,lfm:0,pmhf_fit:1000}, B:{spfm:.90,lfm:.60,pmhf_fit:100},
                         C:{spfm:.97,lfm:.80,pmhf_fit:100}, D:{spfm:.99,lfm:.90,pmhf_fit:10}};

const SLOTS = [
  {id:"schematic", name:"Circuit schematic", req:true, accept:".net,.cir,.csv,.xml,.kicad_sch",
   why:"Netlist and bill of materials exported from your EDA tool. A PDF drawing is not enough — connectivity has to be machine readable.",
   cost:null},
  {id:"safety_manual", name:"Supplier safety manual", req:false, accept:".pdf,.docx,.md,.txt",
   why:"Substantiates supplier coverage claims.",
   cost:"Supplier diagnostic coverage claims drop one evidence tier — the document that would substantiate them is not present."},
  {id:"safety_concept", name:"Technical safety concept", req:false, accept:".pdf,.docx,.md,.txt",
   why:"Source for safety goals, ASIL and FTTI.",
   cost:"Safety goals, ASIL and FTTI cannot be confirmed against source. Goal definitions are taken on trust and flagged in the report."},
  {id:"design_doc", name:"Detailed design document", req:false, accept:".pdf,.docx,.md,.txt",
   why:"Lets failure effects be traced to circuit function.",
   cost:"Failure effects cannot be traced to circuit function. Effect reasoning is weaker and more rows land in the review queue."},
  {id:"hara", name:"HARA", req:false, accept:".pdf,.docx,.xlsx,.csv",
   why:"Independent check on ASIL assignment per goal.",
   cost:"ASIL assignment per goal cannot be independently checked."}
];

const SRC_INFO = {
  iec61709:{label:"IEC 61709:2017", note:"Current. Reference conditions and stress models.", withdrawn:false},
  sn29500:{label:"SN 29500 (Siemens Norm)", note:"Component failure rate data, per part family.", withdrawn:false},
  iec62380:{label:"IEC TR 62380:2004 (withdrawn)",
            note:"Withdrawn 2017-02-17, replaced by IEC 61709:2017. For comparison with legacy analyses only.", withdrawn:true}
};

/* ---------------- state ---------------- */
const state = {
  level: "conservative",
  src: "sn29500",
  temp: "40",
  uploads: {},                 // slot id -> [file names]
  dc: {}                       // mechId -> {dc_spf, dc_lf} user overrides
};

const targetFor = asil => (DATA.targets && DATA.targets[asil]) || DEFAULT_TARGETS[asil];
const present = () => new Set(Object.keys(state.uploads).filter(k => state.uploads[k].length));

/* ---------------- conservatism policy ---------------- */
function applyPolicy(){
  const level = state.level, docs = present();
  const mechs = {}, actions = [], queue = [];
  const manual = docs.has("safety_manual");

  for(const [id, m] of Object.entries(DATA.mechanisms)){
    const ov = state.dc[id] || {};
    const statedSpf = ov.dc_spf !== undefined ? ov.dc_spf : (m.dc_spf ?? 0);
    const statedLf  = ov.dc_lf  !== undefined ? ov.dc_lf  : (m.dc_lf  ?? 0);
    const conf = (m.evidence && m.evidence.confidence) || "estimated";
    let tier = TIER[conf];

    if(!manual && conf === "supplier_claim"){
      tier = Math.max(1, tier - 1);
      actions.push({target:id, field:"evidence tier", before:2, after:tier,
        reason:"supplier safety manual not provided — claim unsubstantiated"});
    }

    const f = DERATE[level][tier];
    let spf = round6(statedSpf * f), lf = round6(statedLf * f);
    if(spf !== statedSpf) actions.push({target:id, field:"dc_spf", before:statedSpf, after:spf,
      reason:`${levelLabel(level)}: evidence '${conf}' (tier ${tier}) derated by ${f.toFixed(2)}`});
    if(lf !== statedLf) actions.push({target:id, field:"dc_lf", before:statedLf, after:lf,
      reason:`${levelLabel(level)}: evidence '${conf}' (tier ${tier}) derated by ${f.toFixed(2)}`});

    if(level === "worst_case" && spf > 0 && m.reaction_time_ms == null){
      actions.push({target:id, field:"dc_spf", before:spf, after:0,
        reason:"no reaction time stated — FTTI compliance not demonstrable"});
      queue.push(`${id}: state a reaction time, or the worst-case run credits no single-point coverage for it`);
      spf = 0;
    }
    mechs[id] = Object.assign({}, m, {dc_spf:spf, dc_lf:lf, stated_spf:statedSpf, stated_lf:statedLf});
  }

  // Failure modes the analysis never classified.
  const elements = DATA.elements.map(el => {
    const modes = Object.assign({}, el.modes);
    if(el.safety_related === false) return Object.assign({}, el, {modes});
    const part = DATA.parts[el.part];
    if(!part) return Object.assign({}, el, {modes});
    const unclassified = Object.keys(part.failure_modes).filter(m => !(m in modes));
    if(!unclassified.length) return Object.assign({}, el, {modes});

    const goals = [...new Set(Object.values(el.modes).flatMap(m => [...(m.violates||[]), ...(m.latent_for||[])]))].sort();
    if(!goals.length) return Object.assign({}, el, {modes});

    for(const name of unclassified){
      if(level === "nominal"){ queue.push(`${el.id}.${name}: unclassified, treated as safe`); continue; }
      const latent = level === "conservative";
      modes[name] = latent
        ? {effect:"Unclassified — treated as latent by conservatism policy", latent_for:goals, mechanisms:[]}
        : {effect:"Unclassified — treated as a single-point fault by policy", violates:goals, mechanisms:[]};
      const what = latent ? "latent" : "single-point fault";
      actions.push({target:`${el.id}.${name}`, field:"classification", before:"unclassified", after:what,
        reason:`${levelLabel(level)}: no classification supplied for this failure mode`});
      queue.push(`${el.id}.${name}: classify this mode — policy assumed ${what}`);
    }
    return Object.assign({}, el, {modes});
  });

  return {mechs, elements, actions, queue};
}

const round6 = x => Math.round(x * 1e6) / 1e6;
const levelLabel = l => ({nominal:"60 · Nominal", conservative:"90 · Conservative", worst_case:"99 · Worst case"})[l];

/* ---------------- classification + metrics ---------------- */
function combineDC(values){
  if(!values.length) return 0;
  if((DATA.dc_combination || "max") === "max") return Math.max(...values);
  return 1 - values.reduce((acc, v) => acc * (1 - v), 1);
}

function classifyMode(policy, el, part, modeName, mode, goalId){
  const lambdaEl = part.lambda_fit * (el.quantity || 1);
  const fraction = part.failure_modes[modeName].fraction;
  const lam = lambdaEl * fraction;
  const goal = DATA.safety_goals[goalId];
  const split = {spf:0, rf:0, mpf_l:0, mpf_d:0, safe:0};
  const listed = (mode.mechanisms || []);
  const named = listed.map(id => policy.mechs[id]).filter(Boolean);
  const scoped = named.filter(m => (m.covers_goals || []).includes(goalId));
  const outOfScope = listed.filter(id => policy.mechs[id] && !(policy.mechs[id].covers_goals || []).includes(goalId));
  const base = {element:el.id, part:el.part, mode:modeName, effect:mode.effect || "",
                lambdaEl, fraction, lambdaMode:lam, mechanisms:listed};

  if((mode.violates || []).includes(goalId)){
    if(!scoped.length){
      split.spf = lam;
      const why = outOfScope.length
        ? `Single-point fault. The effect '${mode.effect}' violates ${goalId} (${goal.statement}). Mechanism(s) ${outOfScope.join(", ")} are listed but scoped to other goals, so no coverage applies here.`
        : `Single-point fault. The effect '${mode.effect}' violates ${goalId} (${goal.statement}) and no safety mechanism is claimed against it.`;
      return Object.assign(base, {cls:"SPF", dc:0, split, why});
    }
    const dc = combineDC(scoped.map(m => m.dc_spf));
    split.rf = lam * (1 - dc); split.mpf_d = lam * dc;
    const why = `Residual fault. The effect '${mode.effect}' violates ${goalId}; ${scoped.map(m=>m.name).join(", ")} claims ${pct(dc)} coverage (${DATA.dc_combination||"max"} combination), leaving ${(lam*(1-dc)).toFixed(3)} FIT uncovered.`;
    return Object.assign(base, {cls:"RF", dc, split, why});
  }

  if((mode.latent_for || []).includes(goalId)){
    const dc = combineDC(scoped.map(m => m.dc_lf));
    split.mpf_l = lam * (1 - dc); split.mpf_d = lam * dc;
    const det = scoped.map(m=>m.name).join(", ") || "nothing";
    const why = `Latent multiple-point fault. Does not violate ${goalId} alone, but '${mode.effect}' disables or degrades a diagnostic. Detected by ${det} at ${pct(dc)}; ${(lam*(1-dc)).toFixed(3)} FIT remains latent.`;
    return Object.assign(base, {cls:"MPF,L", dc, split, why});
  }

  split.safe = lam;
  return Object.assign(base, {cls:"Safe", dc:0, split,
    why:`Safe fault with respect to ${goalId}. '${mode.effect}' neither violates the goal nor disables a diagnostic that protects it.`});
}

function compute(){
  const policy = applyPolicy();
  const goals = {};
  for(const [goalId, goal] of Object.entries(DATA.safety_goals)){
    const totals = {spf:0, rf:0, mpf_l:0, mpf_d:0, safe:0};
    const perElement = {}, rows = [];
    for(const el of policy.elements){
      const part = DATA.parts[el.part];
      if(!part) continue;
      const es = {spf:0, rf:0, mpf_l:0, mpf_d:0, safe:0};
      for(const [name, mode] of Object.entries(el.modes)){
        if(!part.failure_modes[name]) continue;
        const row = classifyMode(policy, el, part, name, mode, goalId);
        rows.push(row);
        for(const k in es){ es[k] += row.split[k]; totals[k] += row.split[k]; }
      }
      perElement[el.id] = es;
    }
    const sr = totals.spf + totals.rf + totals.mpf_l + totals.mpf_d;
    const den = sr - totals.spf - totals.rf;
    goals[goalId] = {
      id:goalId, asil:goal.asil, statement:goal.statement, ftti:goal.ftti_ms,
      safe_state:goal.safe_state, totals, perElement, rows,
      total: sr + totals.safe,
      spfm: sr === 0 ? 1 : 1 - (totals.spf + totals.rf) / sr,
      lfm: den === 0 ? 1 : 1 - totals.mpf_l / den,
      pmhf: totals.spf + totals.rf,
      target: targetFor(goal.asil)
    };
  }
  return {policy, goals};
}

const pct = x => (x * 100).toFixed(1) + "%";
const pct2 = x => (x * 100).toFixed(2) + "%";
const esc = s => String(s).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c]));
</script>
