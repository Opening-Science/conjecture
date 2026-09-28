let D = {};
const $ = (s, r = document) => r.querySelector(s);
const esc = s => String(s ?? '').replace(/[&<>]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
// RFC-4180 cell + spreadsheet-formula neutralisation. A filename like
// `=cmd()` or `a","b` must not forge columns, forge rows, or execute in a
// spreadsheet. Every value written to a CSV goes through this.
const csvCell = v => {
  let s = String(v ?? '').replace(/\r\n|\r|\n/g, ' ');
  if (/^[=+\-@\t]/.test(s)) s = "'" + s;   // defuse formula triggers
  return '"' + s.replace(/"/g, '""') + '"';
};
const csvRow = arr => arr.map(csvCell).join(',');

// Everything about the pack and the adapters comes from pack.json, built
// from pack.yaml and the engine/judge manifests (panel/build_data.py):
// nothing here names a field, an engine or a question.
let P = null, ENGINES = [], JUDGES = [], CORPORA = [], SEEDS = [],
    ENGINE_COST = {}, KEYNAMES = [];

// what a row says about an adapter, and whether it can be ticked
function adapterRow(a) {
  const floor = a.backend === 'none';      // the no-model reference adapters
  let key = false;
  if (a.state === 'designed') key = 'an adapter';
  else if (a.state === 'needs') key = a.missing.join(', ');
  return {id: a.id, name: a.name, note: a.blocker ? `${a.summary} Blocked: ${a.blocker}` : a.summary,
          key, gated: a.gated, floor, handoff: a.invocation === 'handoff',
          built: a.built, requires: a.requires || {}, labels: a.labels};
}

function adoptPack(p) {
  P = p;
  ENGINES = p.engines.map(adapterRow);
  JUDGES = p.judges.filter(j => j.invocation !== 'external').map(adapterRow);
  SEEDS = p.questions;
  CORPORA = [
    {id: p.pack.name, name: p.pack.title, ready: true,
     note: `${p.pack.n_works.toLocaleString('en')} works · ${p.questions.length} questions · the active pack`},
    {id: 'new', name: 'A corpus you build', ready: false,
     note: 'Upload a seed bibliography on the Corpus page; the harness builds the universe around it.'},
  ];
  // Per-engine cost basis from each manifest: tokens per hypothesis and
  // the provider that bills them. Subscription engines carry a token
  // profile too, shown as "would cost" on that provider's API tier.
  ENGINE_COST = {};
  p.engines.forEach(e => {
    const c = e.cost || {};
    if (!c.in || !c.out) return;
    ENGINE_COST[e.id] = c.billing === 'subscription'
      ? {provider: 'subscription', inHyp: c.in, outHyp: c.out, alt: c.provider}
      : {provider: c.provider in PRICES ? c.provider : 'openai', inHyp: c.in, outHyp: c.out};
  });
  KEYNAMES = p.keys;
}


/* ================= COST MODEL =================
   Every figure traces to an assumption the reader can see and change,
   because a precise dollar number here would be fabricated confidence.
   Two anchors are real, measured on this machine:
     - theoria: 6.3M input (4.2M cached) + 165k output per arithmetic
       claim, gpt-5.5, 22-35 min (from the run records).
     - generation: run 1 produced ~6 hypotheses per seed per engine.
   Everything else is a per-hypothesis token profile times a provider
   price the user can edit. Subscription engines bill $0 at the margin
   and say so. */

// Provider list prices, $ per 1M tokens (input / output). Defaults are
// order-of-magnitude estimates as of early 2026 and are shown as editable
// inputs — the total is only as good as these, so they are not hidden.
const PRICES = {
  openai:      {label: 'OpenAI (GPT-5 class)',      in: 1.25, out: 10},
  anthropic:   {label: 'Anthropic (Opus class)',    in: 15,   out: 75},
  openrouter:  {label: 'OpenRouter (passthrough)',  in: 3,    out: 15},
  subscription:{label: 'Subscription (Codex/Claude)', in: 0,  out: 0},
};

// Depth tiers scale the whole run. Each sets hypotheses per seed, a
// reasoning-effort multiplier on tokens (higher effort = more thinking
// tokens), how many judge families audit, and whether/how much theoria
// runs. theoriaFrac is the share of certified-eligible claims sent to
// theoria; theoriaIn/Out are its measured per-claim tokens.
const DEPTH = {
  quick: {id: 'quick', label: 'Quick scan',
    note: '3 hypotheses per seed, medium reasoning, one judge family, no theoria. For a first look at what an engine surfaces.',
    hypPerSeed: 3, effort: 0.7, effortFlag: 'medium', judges: 1,
    theoriaFrac: 0, adversarial: false},
  standard: {id: 'standard', label: 'Standard',
    note: '6 per seed, high reasoning, cross-family judging, theoria on every arithmetic claim.',
    hypPerSeed: 6, effort: 1.0, effortFlag: 'high', judges: 2,
    theoriaFrac: 0.64, adversarial: false},
  deep: {id: 'deep', label: 'Deep',
    note: '10 per seed, xhigh reasoning, cross-family judging plus adversarial verification, theoria on every eligible claim.',
    hypPerSeed: 10, effort: 1.6, effortFlag: 'xhigh', judges: 2,
    theoriaFrac: 1.0, adversarial: true},
};
const THEORIA_IN = 6300000, THEORIA_OUT = 165000;   // measured, per claim
let curDepth = 'standard';

const usd = n => n >= 100 ? '$' + Math.round(n)
  : n >= 1 ? '$' + n.toFixed(2) : n > 0 ? '$' + n.toFixed(2) : '$0';

function price(provider) {
  const inp = parseFloat(($('#price-' + provider) || {}).value);
  const out = parseFloat(($('#price-' + provider + '-out') || {}).value);
  const d = PRICES[provider];
  return {in: isFinite(inp) ? inp : d.in, out: isFinite(out) ? out : d.out};
}

// Cost of one engine for the whole selected run (all chosen seeds).
function engineCost(engineId, nSeeds) {
  const c = ENGINE_COST[engineId]; if (!c) return null;
  const d = DEPTH[curDepth];
  const nHyp = d.hypPerSeed * nSeeds;
  const tin = c.inHyp * d.effort * nHyp;
  const tout = c.outHyp * d.effort * nHyp;
  const pr = price(c.provider);
  const bill = (tin * pr.in + tout * pr.out) / 1e6;
  // subscription: show what the same compute would cost on the API tier
  let alt = null;
  if (c.provider === 'subscription' && c.alt) {
    const ap = price(c.alt);
    alt = (tin * ap.in + tout * ap.out) / 1e6;
  }
  return {nHyp, tin, tout, bill, subscription: c.provider === 'subscription', alt,
          provider: c.provider};
}

function theoriaCost(nHyp) {
  const d = DEPTH[curDepth];
  const nClaims = Math.round(nHyp * 0.64 * d.theoriaFrac);   // 64% carry arithmetic
  const passes = d.adversarial ? 2 : 1;
  // gpt-5.5 runs through the Codex subscription, so the marginal bill is $0.
  // The API-equivalent (what the same tokens would cost on the OpenAI tier)
  // is the honest scale of the compute, so both are shown.
  const ap = price('openai');
  const perClaim = (THEORIA_IN * ap.in + THEORIA_OUT * ap.out) / 1e6;
  return {nClaims, passes, bill: 0, apiEquiv: nClaims * passes * perClaim,
          minutes: nClaims * passes * 28};
}

function nav(page) {
  document.querySelectorAll('main section').forEach(s => s.classList.add('hide'));
  $('#p-' + page).classList.remove('hide');
  document.querySelectorAll('nav button').forEach(b =>
    b.classList.toggle('on', b.dataset.p === page));
  window.scrollTo(0, 0);
}
document.querySelectorAll('nav button').forEach(b =>
  b.onclick = () => nav(b.dataset.p));
document.addEventListener('click', e => {
  const g = e.target.closest('[data-goto]');
  if (g) { e.preventDefault(); nav(g.dataset.goto); }
});

function card(v, l) { return `<div class="card"><b>${v}</b><span>${l}</span></div>`; }

function renderOverview() {
  // the overview is deliberately data-free: it argues the rationale, and
  // the instance-one numbers live on Results where they can be qualified
}

function renderResults() {
  const h = Object.values(D.hypotheses).reduce((a, b) => a + b, 0);
  $('#res-cards').innerHTML =
    card(h, `hypotheses from ${Object.keys(D.hypotheses).length} engines`) +
    card(D.n_candidates, 'candidates after merge') +
    card(D.cards.length, 'certified, not restatements') +
    card(D.conflicts, 'conflicts surfaced');

  let t = '<table><thead><tr><th>Engine</th><th>Hypotheses</th><th>Candidates</th>' +
    '<th>Certified</th><th>Novelty yield</th><th>Mean citations</th></tr></thead><tbody>';
  for (const [e, v] of Object.entries(D.engines)) {
    t += `<tr><td><strong>${esc(e)}</strong></td><td>${D.hypotheses[e] ?? '—'}</td>` +
      `<td>${v.candidates}</td><td>${v.certified}</td><td>${v.novel}</td>` +
      `<td>${v.mean_cites}</td></tr>`;
  }
  $('#gen-table').innerHTML = t + '</tbody></table>';

  const sp = Object.entries(D.selfpref || {});
  if (sp.length) {
    const [fam, worst] = sp.reduce((a, b) => (b[1].delta > a[1].delta ? b : a));
    $('#bias-warn').innerHTML = '<strong>Do not read that table as a quality ranking.</strong> ' +
      `Each judge family passed its own family's hypotheses at a higher rate than the other's (` +
      sp.map(([f, r]) => `${esc(f)} +${Math.round(r.delta * 100)} points`).join(', ') +
      `). Certification requires unanimity across judge families, so the ${esc(fam)} judge's ` +
      `${Math.round(worst.other_rate * 100)}% pass rate on the other family's output drives much of ` +
      `the difference. These counts measure judge composition at least as much as engine quality ` +
      `— see <a href="#" data-goto="verification">Verification</a>.`;
  } else $('#bias-warn').style.display = 'none';

  $('#conv-list').innerHTML = D.convergences.map(g =>
    `<div class="hyp"><div class="st">${esc(g.same_claim)}</div>
     <div class="meta">${g.group.map(k => `<span class="pill ok">${esc(k)}</span>`).join(' ')}</div></div>`
  ).join('') || '<p>None.</p>';

  $('#conf-list').innerHTML = D.conflict_list.map(c =>
    `<div class="hyp"><div class="meta" style="margin:0 0 .4rem">
      ${(c.pair||[]).map(k => `<span class="pill warn">${esc(k)}</span>`).join(' vs ')}</div>
     <div class="st">${esc(c.incompatibility)}</div>
     ${c.discriminating_measurement ? `<div class="meta"><strong>Decide by:</strong> ${esc(c.discriminating_measurement)}</div>` : ''}
     </div>`).join('');

  $('#cert-list').innerHTML = D.cards.map(c =>
    `<div class="hyp"><div class="meta" style="margin:0 0 .35rem">
       <span class="pill">${esc(c.id)}</span> <span class="pill">${esc(c.seed)}</span>
       <span class="pill">${esc(c.level)}</span>
       ${c.conv ? '<span class="pill ok">both engines</span>' : ''}
       <span class="pill">${esc(c.engines)}</span></div>
     <div class="st">${esc(c.statement)}</div>
     <div class="meta">${c.cites} corpus citations · nearest existing claim
       ${esc(c.near)} (similarity ${c.sim})</div>
     ${c.reason ? `<div class="meta"><strong>Audit:</strong> ${esc(c.reason.slice(0,300))}</div>` : ''}
     </div>`).join('') || '<p>None certified.</p>';

  $('#dec-list').innerHTML = '<table><thead><tr><th>Candidate</th><th>Seed</th>' +
    '<th>Claim</th><th>Why declined</th></tr></thead><tbody>' +
    D.declined.map(d => `<tr><td>${esc(d.id)}</td><td>${esc(d.seed)}</td>` +
      `<td>${esc((d.statement||'').slice(0,150))}…</td>` +
      `<td>${esc((d.reason||'not yet judged').slice(0,200))}</td></tr>`).join('') +
    '</tbody></table>';
}

function renderVerification() {
  if (!D.taskA || !D.selfpref) return;
  let t = '<table><thead><tr><th>Verifier</th><th>Accuracy</th><th>Evidential accuracy</th>' +
    '<th>Refutation recall</th><th>Called "support"</th></tr></thead><tbody>';
  for (const [v, r] of Object.entries(D.taskA)) {
    t += `<tr><td><strong>${esc(v)}</strong></td><td>${(r.accuracy*100).toFixed(1)}%</td>` +
      `<td>${r.evidential_accuracy != null ? (r.evidential_accuracy*100).toFixed(1)+'%' : '—'}</td>` +
      `<td>${r.refute_recall != null ? (r.refute_recall*100).toFixed(0)+'%' : '—'}</td>` +
      `<td>${(r.support_rate*100).toFixed(0)}%</td></tr>`;
  }
  const first = Object.values(D.taskA)[0];
  let truth = '';
  if (first && first.confusion) {
    const row = k => Object.values(first.confusion[k] || {}).reduce((a, b) => a + b, 0);
    truth = `Ground-truth support rate ${Math.round(row('support') / first.n * 100)}%, ` +
      `${row('refute')} of ${first.n} items are refutations.`;
  }
  $('#taskA').innerHTML = t + '</tbody></table>' +
    `<p style="color:var(--muted);font-size:.86rem">${truth}</p>`;

  const sp = D.selfpref;
  let s = '<table><thead><tr><th>Judge family</th><th>Judging its OWN family</th>' +
    '<th>Judging the OTHER family</th><th>Delta</th></tr></thead><tbody>';
  for (const [fam, r] of Object.entries(sp)) {
    const bar = p => `<div class="bar2"><i style="width:${(p*100).toFixed(0)}%"></i></div>`;
    s += `<tr><td><strong>${esc(fam)}</strong></td>` +
      `<td>${(r.own_rate*100).toFixed(0)}% <small>(n=${r.n_own})</small>${bar(r.own_rate)}</td>` +
      `<td>${(r.other_rate*100).toFixed(0)}% <small>(n=${r.n_other})</small>${bar(r.other_rate)}</td>` +
      `<td><strong>+${(r.delta*100).toFixed(0)} pts</strong></td></tr>`;
  }
  $('#selfpref').innerHTML = s + '</tbody></table>';
}

function renderRun() {
  const opt = (o, kind) => {
    const dis = o.key ? ' disabled' : '';
    const cls = o.key ? ' disabled' : '';
    const cost = kind === 'engine'
      ? `<span class="ecost" data-ecost="${o.id}"></span>` : '';
    // the no-model reference adapters are a floor to beat, not a default
    const on = !o.key && !o.floor;
    return `<label class="opt${cls}"><input type="checkbox" data-kind="${kind}" value="${o.id}"${dis}${on ? ' checked' : ''}>
      <span><span class="t">${esc(o.name)}</span>
      ${o.key ? `<span class="pill no">needs ${esc(o.key)}</span>` : '<span class="pill ok">ready</span>'}
      ${o.handoff ? '<span class="pill">handoff</span>' : ''}
      ${o.floor ? '<span class="pill">no model · floor</span>' : ''}
      ${o.gated ? '<span class="pill warn">licence-gated output</span>' : ''}
      ${cost}
      <span class="d">${esc(o.note)}</span></span></label>`;
  };
  $('#corpus-opts').innerHTML = CORPORA.map(c =>
    `<label class="opt${c.ready ? '' : ' disabled'}">
       <input type="radio" name="corpus" value="${c.id}"${c.ready ? ' checked' : ' disabled'}>
       <span><span class="t">${esc(c.name)}</span>
       ${c.ready ? '<span class="pill ok">built</span>' : '<span class="pill">not built yet</span>'}
       <span class="d">${esc(c.note)}</span></span></label>`).join('');
  $('#depth-opts').innerHTML = Object.values(DEPTH).map(d =>
    `<label class="opt"><input type="radio" name="depth" value="${d.id}"${d.id === curDepth ? ' checked' : ''}>
       <span><span class="t">${esc(d.label)}</span>
       <span class="d">${esc(d.note)}</span></span></label>`).join('');
  $('#price-panel').innerHTML = Object.entries(PRICES)
    .filter(([k]) => k !== 'subscription').map(([k, v]) =>
    `<div class="keyrow"><label>${esc(v.label)}<br><span class="dim">$ / 1M tokens</span></label>
       <div style="display:flex;gap:8px">
         <input id="price-${k}" type="number" step="0.25" value="${v.in}" title="input" style="width:5rem">
         <input id="price-${k}-out" type="number" step="0.25" value="${v.out}" title="output" style="width:5rem">
       </div></div>`).join('');
  $('#engine-opts').innerHTML = ENGINES.map(e => opt(e, 'engine')).join('');
  $('#judge-opts').innerHTML = JUDGES.map(j => opt(j, 'judge')).join('');
  $('#seed-opts').innerHTML = SEEDS.map(([id, t]) =>
    `<label class="opt"><input type="checkbox" data-kind="seed" value="${id}" checked>
     <span><span class="t">${id}</span> <span class="d">${esc(t)}</span></span></label>`).join('');
  document.querySelectorAll('#p-run input').forEach(i => i.onchange = updateCmd);
  document.querySelectorAll('input[name="depth"], #price-panel input').forEach(i => {
    i.oninput = updateCmd; i.onchange = updateCmd;
  });
  renderCorpusIntake();
  updateCmd();
  initRunPanel();
}

function updateCmd() {
  const picked = k => [...document.querySelectorAll(`#p-run input[data-kind="${k}"]:checked`)]
    .map(i => i.value);
  const engines = picked('engine'), judges = picked('judge'), seeds = picked('seed');
  const depthSel = document.querySelector('input[name="depth"]:checked');
  curDepth = depthSel ? depthSel.value : 'standard';
  const d = DEPTH[curDepth];
  const all = seeds.length === SEEDS.length;
  const seedArg = all ? '--all' : seeds.join(' ');
  const R = P.run, py = R.python;
  const eng = id => ENGINES.find(x => x.id === id) || {};
  const jud = id => JUDGES.find(x => x.id === id) || {};
  const lines = [`cd ${R.cd}`, `export CONJECTURE_PACK=${R.pack}`, '', '# 1. seeds',
    `${py} build_seeds.py`, '', '# 2. generation'];
  engines.forEach(id => {
    const e = eng(id);
    if (!e.built) lines.push(`# ${id}: no adapter yet`);
    else if (e.handoff)
      lines.push(`# ${id} prints each seed's task; dispatch an agent per task, then rerun to collect:`,
        `${py} run_engine.py ${id} ${all ? SEEDS.map(s => s[0]).join(' ') : seeds.join(' ')}`);
    else lines.push(`${py} run_engine.py ${id} ${seedArg}`);
  });
  lines.push('', '# 3. merge + mechanical checks', `${py} run_pipeline.py`);
  lines.push('', '# 4. certification');
  judges.forEach(id => {
    const j = jud(id);
    if (j.handoff)
      (j.labels && j.labels.length ? j.labels : [id]).forEach(l =>
        lines.push(`${py} run_judge.py ${id} --as ${l}   # prints tasks; dispatch, rerun to collect`));
    else lines.push(`${py} run_judge.py ${id}`);
  });
  lines.push(`${py} judge/collect_verdicts.py`);
  if (d.theoriaFrac > 0)
    lines.push('', '# 4b. independent verification (theoria)',
      d.adversarial
        ? `${py} judge/theoria_adapter.py --run --all   # every eligible claim, 2 passes`
        : `${py} judge/theoria_adapter.py --run --only C001,…   # the claims you name`);
  lines.push('', '# 5. score, cards, ledger',
    `${py} run_pipeline.py --score`,
    `${py} experiments/cards.py`,
    `${py} scoreboard/build_ledger.py`);
  $('#cmd').textContent = lines.join('\n');

  let w = '';
  if (!engines.length) w += '<div class="note bad">No engine selected — nothing would be generated.</div>';
  if (!judges.length) w += '<div class="note bad">No judge selected — candidates stay unjudged and nothing can be certified.</div>';
  else if (judges.length === 1) w += `<div class="note warn"><strong>Single judge family.</strong> Judges measurably prefer their own model family (see Verification). With one family judging, engines from that family will be over-certified and the scoreboard will not be comparable.</div>`;
  engines.map(eng).filter(e => e.gated).forEach(e => {
    const terms = (P.engines.find(x => x.id === e.id) || {}).output_terms;
    w += `<div class="note warn"><strong>Licence gate: ${esc(e.name)}.</strong> ${esc(terms || 'its licence restricts what may be published from its output')}.</div>`;
  });
  $('#run-warn').innerHTML = w;

  const ready = engines.filter(e => !eng(e).key);
  const nSeeds = seeds.length || 0;

  // per-engine cost tags on each row
  document.querySelectorAll('[data-ecost]').forEach(el => {
    const ec = engineCost(el.dataset.ecost, nSeeds || SEEDS.length);
    if (!ec) { el.textContent = ''; return; }
    el.innerHTML = ec.subscription
      ? `<span class="pill">$0 · subscription</span>`
        + `<span class="dim"> (${usd(ec.alt)} on API)</span>`
      : `<span class="pill">${usd(ec.bill)}</span>`;
  });

  // roll up the whole run
  let genBill = 0, genHyp = 0, apiBill = 0;
  engines.forEach(e => {
    const ec = engineCost(e, nSeeds); if (!ec) return;
    genHyp += ec.nHyp;
    if (ec.subscription) genBill += 0; else apiBill += ec.bill;
  });
  const th = theoriaCost(genHyp);
  const genMin = Math.round(genHyp * d.effort * 0.8);
  const judgeMin = judges.length * Math.round(genHyp * 0.4);
  const totalMin = genMin + judgeMin + (th.minutes || 0);
  const hrs = totalMin >= 90 ? ` (~${(totalMin / 60).toFixed(1)} h)` : '';

  $('#cost-out').innerHTML = nSeeds && engines.length ? `<table class="kv"><tbody>
      <tr><th>Depth</th><td>${esc(d.label)} · ${d.hypPerSeed}/seed · ${d.effortFlag} reasoning</td></tr>
      <tr><th>Hypotheses</th><td>~${genHyp} across ${nSeeds} seed${nSeeds === 1 ? '' : 's'}, ${engines.length} engine${engines.length === 1 ? '' : 's'}</td></tr>
      <tr><th>Generation — API engines</th><td>${apiBill > 0 ? '~' + usd(apiBill) : '$0'} <span class="dim">${apiBill > 0 ? '' : 'only subscription engines chosen'}</span></td></tr>
      <tr><th>Verification — theoria</th><td>${th.nClaims ? `$0 marginal · ${th.nClaims} claim${th.nClaims === 1 ? '' : 's'}${th.passes > 1 ? ' ×2 passes' : ''} <span class="dim">(~${usd(th.apiEquiv)} on the API tier; runs on subscription here)</span>` : 'off at this depth'}</td></tr>
      <tr><th><strong>API cost this run</strong></th><td><strong>${apiBill > 0 ? '~' + usd(apiBill) : '$0'}</strong> <span class="dim">judge families run on subscription</span></td></tr>
      <tr><th>Wall-clock</th><td>~${totalMin} min${hrs}</td></tr>
    </tbody></table>
    <p class="dim" style="margin:10px 0 0">Estimates. Generation token profiles are per-engine assumptions; theoria's are measured (6.3M in / 165k out per claim, gpt-5.5). Edit provider prices below to match your plan.</p>`
    : '<p class="dim">Pick at least one engine and one seed.</p>';

  $('#run-summary').innerHTML =
    `<table class="kv"><tbody>
      <tr><th>Seeds</th><td>${nSeeds} of ${SEEDS.length}</td></tr>
      <tr><th>Runnable now</th><td>${ready.length ? ready.map(esc).join(', ') : '<em>none</em>'}</td></tr>
      <tr><th>Judge families</th><td>${judges.length ? judges.map(esc).join(', ') : '<em>none</em>'}</td></tr>
      <tr><th>Certified-eligible for theoria</th><td>~${Math.round(genHyp * 0.64)} carry arithmetic</td></tr>
    </tbody></table>`;
}


/* ================= THE LEDGER =================
   The one table the whole pipeline exists to produce: every hypothesis,
   with every verdict against it side by side. Two of the three verifier
   columns are ours; the third is theoria, which sees only the arithmetic.
   Keeping them in separate columns rather than folding them into one
   score is deliberate — where they disagree is the interesting part, and
   an average would hide exactly that. */
let LEDGER = null, lgFilter = 'all', lgOpen = null;
// per-column filters, free-text search, and sort. lgCol maps a column key
// to a selected value ('' = any); lgSort is the active column + direction.
let lgCol = {}, lgText = '', lgSort = {key: 'default', dir: 1};

// accessors: one per sortable/filterable column
const claudeOf = r => {
  const e = Object.entries(r.judges).find(([k]) => k.startsWith('claude'));
  return e ? e[1].verdict : '';
};
const codexOf = r => (r.judges.codex ? r.judges.codex.verdict : '');
const checksOf = r => (r.mechanical.pass ? 'pass' : 'fail');

// column model: label, value accessor, whether it gets a filter select,
// and a sort key (verdicts sort by severity, not alphabetically).
const VORDER = ['certified', 'pedantic', 'declined', 'inconclusive',
                'error', 'queued', 'n/a', ''];
const vrank = v => { const i = VORDER.indexOf(v); return i < 0 ? 99 : i; };
const LCOLS = [
  {key: 'id', label: 'Hypothesis', get: r => r.id, sort: r => r.seed + r.id},
  {key: 'seed', label: 'Q', get: r => r.seed, filter: true, sort: r => r.seed + r.id},
  {key: 'level', label: 'Level', get: r => r.level || '', filter: true, sort: r => r.level || ''},
  {key: 'engine', label: 'Engine', get: r => r.engines, filter: true, sort: r => r.engines},
  {key: 'checks', label: 'Checks', get: checksOf, filter: true, sort: r => checksOf(r) === 'pass' ? 0 : 1},
  {key: 'claude', label: 'Claude judge', get: claudeOf, filter: true, sort: r => vrank(claudeOf(r))},
  {key: 'codex', label: 'Codex judge', get: codexOf, filter: true, sort: r => vrank(codexOf(r))},
  {key: 'theoria', label: 'theoria', get: r => r.theoria.verdict, filter: true, sort: r => vrank(r.theoria.verdict)},
];

const VD = {
  certified:    ['ok',   'certified'],
  declined:     ['bad',  'declined'],
  pedantic:     ['warn', 'pedantic'],
  inconclusive: ['warn', 'inconclusive'],
  error:        ['warn', 'error'],
  queued:       ['',     'queued'],
  'n/a':        ['',     'no arithmetic'],
};
const pill = v => { const [c, l] = VD[v] || ['', v || '—'];
  return `<span class="pill ${c}">${esc(l)}</span>`; };

function renderLedger() {
  const host = $('#ledger'); if (!host || !LEDGER) return;
  const T = LEDGER.tally, all = LEDGER.rows;

  // preset quick filters, still handy on top of the column filters
  const presets = {
    all:       () => true,
    certified: r => r.certified,
    declined:  r => !r.certified,
    theoria:   r => ['certified', 'declined'].includes(r.theoria.verdict),
    split:     r => r.certified && r.theoria.verdict === 'declined',
  };

  // apply: preset, then each active column value, then free text
  let rows = all.filter(presets[lgFilter] || presets.all);
  LCOLS.forEach(c => {
    const want = lgCol[c.key];
    if (want) rows = rows.filter(r => String(c.get(r)) === want);
  });
  if (lgText.trim()) {
    const q = lgText.trim().toLowerCase();
    rows = rows.filter(r => (r.id + ' ' + r.statement).toLowerCase().includes(q));
  }
  // sort: a chosen column, else the natural seed+id order
  const sc = LCOLS.find(c => c.key === lgSort.key);
  if (sc) {
    rows = [...rows].sort((a, b) => {
      const x = sc.sort(a), y = sc.sort(b);
      return (x < y ? -1 : x > y ? 1 : 0) * lgSort.dir;
    });
  } else {
    rows = [...rows].sort((a, b) => (a.seed + a.id < b.seed + b.id ? -1 : 1));
  }

  // distinct values per filterable column, from the FULL set so options
  // never vanish as you narrow
  const opts = {};
  LCOLS.filter(c => c.filter).forEach(c => {
    opts[c.key] = [...new Set(all.map(c.get).filter(v => v !== ''))].sort(
      (a, b) => c.key.match(/claude|codex|theoria/) ? vrank(a) - vrank(b)
        : (a < b ? -1 : 1));
  });
  const active = Object.values(lgCol).filter(Boolean).length + (lgText ? 1 : 0);

  const filterCols = LCOLS.filter(c => c.filter);
  const filterGrid = filterCols.map(c => {
    const sel = lgCol[c.key] || '';
    return `<label class="lgf"><span>${esc(c.label)}</span>
      <select data-col="${c.key}"><option value="">any</option>` +
      opts[c.key].map(v => `<option${sel === String(v) ? ' selected' : ''} value="${esc(v)}">${esc(v)}</option>`).join('') +
      '</select></label>';
  }).join('');
  const sortOpt = LCOLS.map(c =>
    `<option value="${c.key}"${lgSort.key === c.key ? ' selected' : ''}>${esc(c.label)}</option>`).join('');

  $('#ledger-controls').innerHTML =
    `<div class="lgbar">
       <div>` + Object.entries({
         all: `All ${T.n}`, certified: `Certified ${T.certified}`,
         declined: `Declined ${T.n - T.certified}`,
         theoria: `theoria ruled ${T.theoria_certified + T.theoria_declined}`,
         split: 'Judges vs theoria',
       }).map(([k, l]) => `<button class="lgb${lgFilter === k ? ' on' : ''}" data-f="${k}">${esc(l)}</button>`).join('') +
     `</div><div style="display:flex;gap:8px;align-items:center">
        <input id="lgtext" placeholder="search id or statement" value="${esc(lgText)}">
        <button class="lgb${active ? ' on' : ''}" id="lgclear">Clear${active ? ` (${active})` : ''}</button>
     </div></div>
     <div class="lgfilters">${filterGrid}
       <label class="lgf"><span>Sort by</span>
         <select id="lgsortsel">${sortOpt}</select></label>
       <button class="lgb" id="lgdir" title="sort direction">${lgSort.dir === 1 ? '▲ asc' : '▼ desc'}</button>
     </div>
     <p class="dim" style="margin:8px 0 6px">Showing <b>${rows.length}</b> of ${all.length}. Filter by
        any verdict above; click a column heading (or use Sort) to reorder.</p>`;

  const sortArrow = k => lgSort.key === k ? (lgSort.dir === 1 ? ' ▲' : ' ▼') : '';
  const head = LCOLS.map(c =>
    `<th class="lgsort${lgSort.key === c.key ? ' on' : ''}" data-sort="${c.key}"
        role="button" tabindex="0">${esc(c.label)}${sortArrow(c.key)}</th>`).join('');

  host.innerHTML = `<table class="ledger"><thead><tr>${head}</tr></thead><tbody>`
    + (rows.length ? rows.map(r => {
    const cj = claudeOf(r), xj = codexOf(r);
    return `<tr class="lgrow${lgOpen === r.id ? ' open' : ''}" data-id="${r.id}"
        tabindex="0" role="button" aria-expanded="${lgOpen === r.id}"
        aria-label="Hypothesis ${r.id}, expand for full audit">
        <td data-l="hypothesis"><code>${r.id}</code> ${esc(r.statement)}
            ${r.convergent ? '<span class="pill">both engines</span>' : ''}
            ${r.restatement ? '<span class="pill warn">restatement</span>' : ''}</td>
        <td data-l="question">${esc(r.seed)}</td>
        <td data-l="level">${esc(r.level || '')}</td>
        <td data-l="engine">${esc(r.engines)}</td>
        <td data-l="checks">${r.mechanical.pass ? '<span class="pill ok">pass</span>'
              : '<span class="pill bad">fail</span>'}</td>
        <td data-l="claude judge">${cj ? pill(cj) : '—'}</td>
        <td data-l="codex judge">${xj ? pill(xj) : '—'}</td>
        <td data-l="theoria">${pill(r.theoria.verdict)}</td>
      </tr>` + (lgOpen === r.id ? `<tr class="lgdet"><td colspan="8">${detail(r)}</td></tr>` : '');
  }).join('') : '<tr><td colspan="8">Nothing matches these filters.</td></tr>')
    + '</tbody></table>';

  $('#ledger-note').innerHTML =
    `theoria has ruled on <b>${T.theoria_run}</b> of the <b>${T.theoria_eligible}</b> hypotheses
     that carry arithmetic (${T.n - T.theoria_eligible} of ${T.n} propose an experiment without
     deriving a number, so there is nothing for it to re-derive). Of those it has ruled on:
     ${T.theoria_certified} correct, ${T.theoria_declined} incorrect,
     ${T.theoria_inconclusive} inconclusive${T.theoria_error ? `, ${T.theoria_error} errored (re-queued)` : ''}. The count rises as pass-2 verdicts land — pass 1 was archived after an
     environment-description defect (see the theoria section on the Verification page), so the
     column re-fills from zero.`;

  host.querySelectorAll('.lgrow').forEach(tr => {
    const toggle = () => { lgOpen = lgOpen === tr.dataset.id ? null : tr.dataset.id; renderLedger(); };
    tr.onclick = toggle;
    tr.onkeydown = e => {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggle(); }
    };
  });
  // preset buttons (Clear resets everything)
  $('#ledger-controls').querySelectorAll('.lgb[data-f]').forEach(b =>
    b.onclick = () => { lgFilter = b.dataset.f; lgOpen = null; renderLedger(); });
  const clr = $('#lgclear');
  if (clr) clr.onclick = () => {
    lgCol = {}; lgText = ''; lgFilter = 'all'; lgOpen = null; renderLedger();
  };
  // free-text search (keep focus + caret across the re-render)
  const tb = $('#lgtext');
  if (tb) tb.oninput = () => {
    lgText = tb.value; lgOpen = null; renderLedger();
    const n = $('#lgtext'); if (n) { n.focus(); n.setSelectionRange(n.value.length, n.value.length); }
  };
  // per-column filter selects (in the controls bar)
  $('#ledger-controls').querySelectorAll('.lgfilters select[data-col]').forEach(s =>
    s.onchange = () => {
      if (s.value) lgCol[s.dataset.col] = s.value; else delete lgCol[s.dataset.col];
      lgOpen = null; renderLedger();
    });
  // sort dropdown + direction toggle (mobile-friendly path)
  const ss = $('#lgsortsel');
  if (ss) ss.onchange = () => { lgSort = {key: ss.value, dir: lgSort.dir}; renderLedger(); };
  const dir = $('#lgdir');
  if (dir) dir.onclick = () => { lgSort = {key: lgSort.key, dir: -lgSort.dir}; renderLedger(); };
  // sortable headers: click toggles direction, click a new column sorts asc
  host.querySelectorAll('th.lgsort').forEach(th => {
    const doSort = () => {
      const k = th.dataset.sort;
      lgSort = lgSort.key === k ? {key: k, dir: -lgSort.dir} : {key: k, dir: 1};
      renderLedger();
    };
    th.onclick = doSort;
    th.onkeydown = e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); doSort(); } };
  });
}


// Render a cited work_id as its paper: a DOI-linked title, an author-year
// tag, or — when the work is not in the knowledgebase — the bare id marked
// so the gap is visible. Reads the works map build_ledger.py emits.
function cite(wid) {
  const w = (LEDGER && LEDGER.works && LEDGER.works[wid]) || null;
  if (!w || w.missing || !w.title) {
    return `<code title="not resolved to a paper">${esc(wid)}</code>`;
  }
  const yr = w.year ? ` (${w.year})` : '';
  const label = esc(w.title) + yr;
  return w.url
    ? `<a href="${esc(w.url)}" target="_blank" rel="noopener">${label}</a>`
    : `<span title="${esc(wid)}">${label}</span>`;
}
function citeInline(wid) {          // compact form for rationale steps
  const w = (LEDGER && LEDGER.works && LEDGER.works[wid]) || null;
  if (!w || w.missing || !w.title) return `<code>${esc(wid)}</code>`;
  const first = (w.authors || '').split(/[;,]/)[0].trim();
  const tag = (first ? first.split(/\s+/).pop() : 'ref') + (w.year ? ' ' + w.year : '');
  const inner = `<span class="citetag" title="${esc(w.title)}">${esc(tag)}</span>`;
  return w.url ? `<a href="${esc(w.url)}" target="_blank" rel="noopener">${inner}</a>` : inner;
}

function detail(r) {
  const jr = Object.entries(r.judges).map(([k, v]) =>
    `<tr><th>${esc(k)}</th><td>${pill(v.verdict)}
       ${v.failing_step ? `<span class="dim">failing step ${v.failing_step}</span>` : ''}
       <div>${esc(v.reason || '')}</div></td></tr>`).join('');
  const th = r.theoria;
  const thr = th.verdict === 'n/a'
    ? `<tr><th>theoria</th><td>${pill('n/a')}<div>${esc(th.note || '')}</div></td></tr>`
    : `<tr><th>theoria</th><td>${pill(th.verdict)}
        <span class="dim">${th.steps} computation step${th.steps === 1 ? '' : 's'} extracted</span>
        <div>${th.answer ? esc(th.answer)
          : 'Queued. theoria runs its own solver, formalizer and per-step judges over each claim, which takes minutes per hypothesis.'}</div>
        ${th.proof_verified === false ? '<div class="dim">theoria could not verify its own proof, so this is inconclusive rather than a ruling on the hypothesis.</div>' : ''}
       </td></tr>`;
  return `<div class="lgbody">
    <p><b>${esc(r.statement)}</b></p>
    <table class="kv"><tbody>
      <tr><th>Estimand</th><td>${esc(r.estimand)}</td></tr>
      <tr><th>Null</th><td>${esc(r.null)}</td></tr>
      <tr><th>Experiment</th><td>${esc(r.experiment)}</td></tr>
      <tr><th>Instrument</th><td>${esc(r.instrument)}</td></tr>
      <tr><th>Corpus citations</th><td>${r.citations.length}<ul class="cites">${
        r.citations.map(w => `<li>${cite(w)}</li>`).join('')}</ul></td></tr>
      ${r.nearest_claim ? `<tr><th>Nearest registry claim</th><td>${esc(r.nearest_claim)}
        <span class="dim">similarity ${r.nearest_similarity}</span></td></tr>` : ''}
      ${r.mechanical.fails.length ? `<tr><th>Mechanical</th><td>${esc(r.mechanical.fails.join('; '))}</td></tr>` : ''}
    </tbody></table>
    <p class="label">Reasoning as the engine stated it</p>
    <ol class="steps">${r.rationale.map(s =>
      `<li><span class="pill">${esc(s.type || '')}</span> ${esc(s.step)}
        ${s.works && s.works.length ? `<span class="citechips">${s.works.map(citeInline).join(' ')}</span>` : ''}</li>`).join('')}</ol>
    <p class="label">Verdicts</p>
    <table class="kv verd"><tbody>${jr}${thr}</tbody></table>
  </div>`;
}

const getJSON = u => fetch(u).then(r => { if (!r.ok) throw new Error(`${u}: ${r.status}`); return r.json(); });
const safe = fn => { try { fn(); } catch (e) { console.error(fn.name, e); } };

getJSON('pack.json').then(p => {
  adoptPack(p);
  [renderPack, renderStatusPills, renderRun].forEach(safe);
  if (p.has_findings)
    fetch('findings.html').then(r => r.ok ? r.text() : '').then(h => {
      const n = $('#pack-findings'); if (n && h) n.innerHTML = h;
      [renderVerification, renderFigures].forEach(safe);   // findings may hold figure slots
    });
  return getJSON('data.json').then(d => {
    D = d;
    [renderOverview, renderResults, renderVerification, renderFigures].forEach(safe);
  }).catch(e => {
    const n = $('#res-cards');
    if (n) n.outerHTML = `<div class="note warn">No results for this pack yet: run engines and
      judges, then <code>run_pipeline.py --score</code>. ${esc(e.message)}</div>`;
  });
}).catch(e => {
  document.querySelector('main').insertAdjacentHTML('afterbegin',
    `<div class="note bad">Could not load pack.json. Serve the panel with its server
     (<code>python panel/server.py</code>) or from a static export (<code>panel/export.py</code>),
     not as a file. ${esc(e.message)}</div>`);
});

// the pack's name wherever the page refers to "this pack"
function renderPack() {
  document.querySelectorAll('[data-pack="title"]').forEach(n => n.textContent = P.pack.title);
  document.querySelectorAll('[data-pack="name"]').forEach(n => n.textContent = P.pack.name);
  document.querySelectorAll('[data-pack="questions"]').forEach(n => n.textContent = P.questions.length);
  const built = P.engines.filter(e => e.built && e.backend !== 'none').length;
  const designed = P.engines.filter(e => !e.built).length;
  const ran = P.engines.filter(e => e.ran).length;
  const st = $('#hub-status');
  if (st) st.innerHTML = `<strong>Status.</strong> ${built} engine${built === 1 ? '' : 's'} built and
    conformance-tested, ${ran} of them run on this pack; ${designed} more designed, each waiting on
    an API key or an adapter. See <a href="#" data-goto="sources">Sources &amp; licences</a>.`;
}

// the status column of the engine catalogue, from manifests and runs
function renderStatusPills() {
  document.querySelectorAll('[data-status]').forEach(n => {
    const e = P.engines.find(x => x.id === n.dataset.status);
    if (!e) { n.innerHTML = ''; return; }
    n.innerHTML = e.ran ? `<span class="pill ok">ran · ${e.ran} hyp</span>`
      : e.state === 'ready' ? '<span class="pill ok">ready</span>'
      : e.state === 'needs' ? `<span class="pill no">needs ${esc(e.missing.join(', '))}</span>`
      : e.gated ? '<span class="pill warn">gated · no adapter</span>'
      : '<span class="pill no">no adapter yet</span>';
  });
}

function renderTheoria() {
  const host = $('#th-panel'); if (!host || !LEDGER) return;
  const T = LEDGER.tally, ruled = T.theoria_certified + T.theoria_declined;
  const c = $('#th-cards');
  if (c) c.innerHTML =
    card(`${T.theoria_run}/${T.theoria_eligible}`, 'claims run through theoria') +
    card(T.theoria_certified, 'arithmetic holds') +
    card(T.theoria_declined, 'arithmetic does not hold') +
    card(T.theoria_inconclusive, 'inconclusive — its own proof unverified');

  // where the two audits disagree is the whole reason for running both
  const split = LEDGER.rows.filter(r =>
    ['certified', 'declined'].includes(r.theoria.verdict) &&
    r.certified !== (r.theoria.verdict === 'certified'));

  host.innerHTML =
    (ruled < T.theoria_eligible ? `<div class="note">${T.theoria_eligible - T.theoria_run}
      claims are still running. theoria executes a full solve-and-audit per claim, minutes each, so
      the table below fills in over a run rather than all at once.</div>` : '') +
    `<p class="label">Disagreement</p>
     <h3>Where theoria and our judges part company</h3>` +
    (split.length ? `<p>${split.length} hypothes${split.length === 1 ? 'is' : 'es'} on which the two
       audits reach opposite conclusions. Neither column overrules the other: they are answering
       different questions, and a hypothesis needs both to hold.</p>
     <table><thead><tr><th>Hypothesis</th><th>Our judges</th><th>theoria</th>
       <th>What theoria found</th></tr></thead><tbody>` +
      split.map(r => `<tr><td><code>${r.id}</code> ${esc(r.statement.slice(0, 70))}…</td>
        <td>${pill(r.certified ? 'certified' : 'declined')}</td>
        <td>${pill(r.theoria.verdict)}</td>
        <td>${esc((r.theoria.answer || '').slice(0, 260))}</td></tr>`).join('') +
      '</tbody></table>'
     : `<p>No disagreement so far: on every claim theoria has ruled on, it and our judges
        agree. With ${ruled} claim${ruled === 1 ? '' : 's'} ruled on, that is not yet a
        result — it is a small sample, and the interesting cases are the ones still queued.</p>`);
}



/* ================= FIGURES =================
   Editorial SVG, derived from the diagram-design discipline mapped onto
   the OSF palette: flat, self-contained, thin strokes, mono labels, and
   the accent reserved for the single thing the reader should see first.
   Every number is read from data.json at render time — the figures
   cannot drift from the tables. */
// data marks are ink; blue is reserved for a single annotation, never a
// data surface; gridlines use the cream-dark line token, not a surface.
const FIG = {ink: '#1d1d1d', gray: '#646363', line: '#c0beb2',
             grid: '#c0beb2', mark: '#1d1d1d', accent: '#73adff'};
const figWrap = (svg, caption) =>
  `<figure class="fig">${svg}<figcaption>${caption}</figcaption></figure>`;

/* Self-preference: a dumbbell per judge family. The accent belongs to the
   one number that decides the design: the largest own-family gap. */
function figSelfPref(sp) {
  const fams = Object.entries(sp || {});
  if (!fams.length) return '';
  const top = fams.reduce((a, b) => (b[1].delta > a[1].delta ? b : a))[0];
  const W = 640, L = 210, R = 600, rowY = fams.map((_, i) => 64 + i * 68);
  const H = rowY[rowY.length - 1] + 58;
  const x = v => L + (R - L) * v;
  const rows = fams.map(([f, d]) => [`${f} judge`, d, f === top]);
  let s = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Self-preference by judge family">`;
  [0, .25, .5, .75, 1].forEach(v => {
    s += `<line x1="${x(v)}" y1="40" x2="${x(v)}" y2="${H - 38}" stroke="${FIG.grid}" stroke-width="1"/>
          <text x="${x(v)}" y="${H - 20}" text-anchor="middle" class="fmono" fill="${FIG.gray}">${v * 100}%</text>`;
  });
  rows.forEach(([name, d, focal], i) => {
    const y = rowY[i], a = x(d.other_rate), b = x(d.own_rate);
    const c = FIG.ink;   // bars are always ink; the accent is on the delta label only
    s += `<text x="0" y="${y + 4}" class="fmono" fill="${FIG.ink}">${name}</text>
      <line x1="${a}" y1="${y}" x2="${b}" y2="${y}" stroke="${c}" stroke-width="${focal ? 3 : 2}"/>
      <circle cx="${a}" cy="${y}" r="6" fill="#fff" stroke="${FIG.ink}" stroke-width="1.5"/>
      <circle cx="${b}" cy="${y}" r="6" fill="${FIG.ink}"/>
      <text x="${a}" y="${y - 14}" text-anchor="middle" class="fmono" fill="${FIG.gray}">${Math.round(d.other_rate * 100)}%</text>
      <text x="${b}" y="${y - 14}" text-anchor="middle" class="fmono" fill="${FIG.ink}">${Math.round(d.own_rate * 100)}%</text>
      <text x="${(a + b) / 2}" y="${y + 22}" text-anchor="middle" class="fmono"
        fill="${focal ? FIG.accent : FIG.gray}"${focal ? ' font-weight="700"' : ''}>+${Math.round(d.delta * 100)} pts (n=${d.n_own}/${d.n_other})</text>`;
  });
  s += `<circle cx="6" cy="14" r="5" fill="${FIG.ink}"/>
    <text x="16" y="18" class="fmono" fill="${FIG.gray}">pass rate, own family&#8195;</text>
    <circle cx="182" cy="14" r="5" fill="#fff" stroke="${FIG.ink}" stroke-width="1.5"/>
    <text x="192" y="18" class="fmono" fill="${FIG.gray}">other family</text></svg>`;
  return figWrap(s, 'Certification pass rate by who is judging whom (n shown per cell). A ' +
    'judge-by-generator interaction shows as each family passing its own family&rsquo;s output at a ' +
    `higher rate. The ${esc(top)} judge&rsquo;s ${Math.round(sp[top].delta * 100)}-point gap is the ` +
    'largest here.');
}

/* The run as attrition: generated -> merged -> judged -> certified -> novel. */
function figFunnel(D) {
  const raw = Object.values(D.hypotheses).reduce((a, b) => a + b, 0);
  const steps = [
    [raw, 'generated', `${Object.keys(D.hypotheses).length} engines, ${Object.keys(D.by_seed || {}).length} questions`],
    [D.n_candidates, 'candidates', 'after cross-engine merge'],
    [D.mechanical_pass ?? D.n_candidates, 'passed mechanical', 'citations exist, scope complete'],
    [D.certified, 'certified', 'unanimity across judge families'],
    [D.novel, 'certified & novel', 'not already on the claim register'],
  ];
  const W = 680, BX = 200, BW = 330, RH = 34, G = 14;
  let s = `<svg viewBox="0 0 ${W} ${steps.length * (RH + G) + 6}" role="img" aria-label="Attrition through the pipeline">`;
  steps.forEach(([n, label, sub], i) => {
    const y = i * (RH + G), w = BW * n / raw, last = i === steps.length - 1;
    s += `<text x="0" y="${y + 15}" class="fmono" fill="${FIG.ink}">${label}</text>
      <text x="0" y="${y + 29}" class="fmono" fill="${FIG.gray}" font-size="10">${sub}</text>
      <rect x="${BX}" y="${y}" width="${Math.max(w, 3)}" height="${RH}" rx="4"
        fill="${last ? FIG.ink : '#f8f8f4'}" stroke="${last ? FIG.ink : FIG.line}"/>
      ${last ? `<rect x="${BX}" y="${y}" width="4" height="${RH}" fill="${FIG.accent}"/>` : ''}
      <text x="${BX + Math.max(w, 3) + 10}" y="${y + RH / 2 + 4}" class="fmono"
        fill="${FIG.ink}"${last ? ' font-weight="700"' : ''}>${n}${i === 2 ? ` (${n}/${D.n_candidates} passed)` : ''}</text>`;
  });
  s += '</svg>';
  return figWrap(s, 'What survives. Certification is deliberately lossy: the declines carry ' +
    'the findings, and the audit publishes their reasons.');
}

/* Verifier benchmark: two families, three scores each, against known labels. */
function figBench(tA) {
  const fams = Object.keys(tA || {});
  if (fams.length < 2) return '';
  const [fa, fb] = fams, first = tA[fa];
  const metrics = [['accuracy', 'accuracy'], ['evidential_accuracy', 'evidential accuracy'],
                   ['refute_recall', 'refutation recall']];
  const W = 640, L = 210, R = 560, rH = 52;
  const x = v => L + (R - L) * v;
  let s = `<svg viewBox="0 0 ${W} ${metrics.length * rH + 40}" role="img" aria-label="Verifier benchmark">`;
  s += `<text x="0" y="8" class="fmono" fill="${FIG.gray}">axis starts at 50%</text>`;
  [.5, .75, 1].forEach(v => {
    s += `<line x1="${x(v)}" y1="12" x2="${x(v)}" y2="${metrics.length * rH}" stroke="${FIG.grid}"/>
          <text x="${x(v)}" y="${metrics.length * rH + 18}" text-anchor="middle" class="fmono" fill="${FIG.gray}">${v * 100}%</text>`;
  });
  metrics.forEach(([k, label], i) => {
    const y = i * rH + 26;
    const a = tA[fa][k], b = tA[fb][k];
    s += `<text x="0" y="${y + 4}" class="fmono" fill="${FIG.ink}">${label}</text>
      <line x1="${x(Math.min(a, b))}" y1="${y}" x2="${x(Math.max(a, b))}" y2="${y}" stroke="${FIG.line}"/>
      <circle cx="${x(a)}" cy="${y}" r="6" fill="${FIG.ink}"/>
      <circle cx="${x(b)}" cy="${y}" r="6" fill="#fff" stroke="${FIG.ink}" stroke-width="1.5"/>
      <text x="${x(Math.max(a, b)) + 14}" y="${y + 4}" class="fmono" fill="${FIG.gray}">${Math.round(a * 100)} / ${Math.round(b * 100)}</text>`;
  });
  s += `<circle cx="6" cy="${metrics.length * rH + 14}" r="5" fill="${FIG.ink}"/>
    <text x="16" y="${metrics.length * rH + 18}" class="fmono" fill="${FIG.gray}">${esc(fa)}&#8195;</text>
    <circle cx="80" cy="${metrics.length * rH + 14}" r="5" fill="#fff" stroke="${FIG.ink}" stroke-width="1.5"/>
    <text x="90" y="${metrics.length * rH + 18}" class="fmono" fill="${FIG.gray}">${esc(fb)}</text></svg>`;
  return figWrap(s, `${first.n} blinded items scored against the pack&rsquo;s verified stance labels. ` +
    'Axis truncated at 50% to separate the two families.');
}

function renderFigures() {
  if (!D || !D.hypotheses) return;          // results not loaded yet
  const put = (sel, html) => { const n = $(sel); if (n) n.innerHTML = html; };
  put('#fig-funnel', figFunnel(D));
  put('#fig-selfpref', figSelfPref(D.selfpref));
  put('#fig-bench', figBench(D.taskA));
}

/* ================= RUN TRIGGER =================
   Talks to server.py's four endpoints. If the site is served by a plain
   static server the fetches fail and the panel says so instead of
   pretending — a dead Run button is worse than an honest absence. */
let API = null, logTimer = null;

async function api(path, body) {
  const r = await fetch(path, body
    ? {method: 'POST', headers: {'Content-Type': 'application/json'},
       body: JSON.stringify(body)} : undefined);
  const d = await r.json();
  if (!r.ok) throw new Error(d.error || r.status);
  return d;
}

function renderKeys(keys) {
  $('#keys-panel').innerHTML = KEYNAMES.map(k => `
    <div class="keyrow">
      <label for="key-${k}"><code>${k}</code>
        ${keys[k] ? `<span class="pill ok">set ${esc(keys[k])}</span>`
                  : '<span class="pill">not set</span>'}</label>
      <div><input type="password" id="key-${k}" autocomplete="off"
        placeholder="${keys[k] ? 'replace (leave blank to keep)' : 'paste key'}">
      </div></div>`).join('') +
    `<div style="margin-top:12px;display:flex;gap:12px;align-items:center">
       <button id="keys-save">Save keys</button><span id="keys-msg" class="dim"></span></div>`;
  $('#keys-save').onclick = async () => {
    const body = {};
    KEYNAMES.forEach(k => {
      const v = $('#key-' + k).value;
      if (v.trim()) body[k] = v.trim();
    });
    if (!Object.keys(body).length) { $('#keys-msg').textContent = 'nothing entered'; return; }
    try {
      const d = await api('/api/keys', body);
      $('#keys-msg').textContent = 'saved';
      renderKeys(d.keys); refreshEngineKeyPills(d.keys);
    } catch (e) { $('#keys-msg').textContent = 'failed: ' + e.message; }
  };
}

// engines whose keys are now present, per their manifest, get an honest
// intermediate status: the key alone does not build an adapter
function refreshEngineKeyPills(keys) {
  const met = r => (r.env || []).every(k => keys[k]) &&
    (!(r.env_any || []).length || r.env_any.some(k => keys[k])) &&
    ((r.env || []).length || (r.env_any || []).length);
  document.querySelectorAll('#engine-opts .opt input[data-kind="engine"]').forEach(i => {
    const e = ENGINES.find(x => x.id === i.value);
    const pill = i.parentElement.querySelector('.pill.no, .pill.keyset');
    if (pill && e && !e.built && met(e.requires)) {
      pill.className = 'pill warn keyset';
      pill.textContent = 'key set: adapter not yet built';
    }
  });
}

function renderJobs(jobs, state) {
  $('#job-opts').innerHTML = Object.entries(jobs).map(([id, j]) => `
    <label class="opt"><input type="checkbox" data-job="${id}">
      <span><span class="t">${esc(j.label)}</span>
      ${j.warn ? `<span class="pill warn">${esc(j.warn)}</span>` : ''}
      ${(j.needs || []).length ? `<span class="pill no">needs ${esc(j.needs.join(', '))}</span>` : ''}
      ${(state.done || []).some(d => d.id === id)
        ? `<span class="pill ${state.done.find(d => d.id === id).rc === 0 ? 'ok' : 'no'}">
             exit ${state.done.find(d => d.id === id).rc}</span>` : ''}
      </span></label>
    ${j.claims ? renderClaimPicker(j.claims) : ''}`).join('');
}

// theoria never sweeps: each claim is a full solve-and-audit (~30 min,
// ~6M tokens of gpt-5.5 on the Codex subscription), so the pickable list
// starts empty and the server refuses a selection of zero.
function renderClaimPicker(claims) {
  const TERMINAL = ['certified', 'declined', 'inconclusive'];
  const open = claims.filter(c => !TERMINAL.includes(c.verdict)).length;
  return `<div class="claim-picker">
    <p class="dim">Tick the claims to verify — nothing is pre-ticked, and each one is
    ~25–35 min and ~6M tokens on the Codex subscription. ${open} of ${claims.length} still
    open; settled claims are shown with their verdict and cannot be re-queued from here.</p>
    ${claims.map(c => {
      const settled = TERMINAL.includes(c.verdict);
      return `<label class="opt claim${settled ? ' disabled' : ''}">
        <input type="checkbox" data-claim="${esc(c.id)}"${settled ? ' disabled' : ''}>
        <span><span class="t">${esc(c.id)}</span>
        <span class="d">${esc(c.seed || '')} · ${c.steps} computation step${c.steps === 1 ? '' : 's'}</span></span>
        <span class="pill ${c.verdict === 'certified' ? 'ok' : c.verdict === 'declined' ? 'no'
          : c.verdict ? 'warn' : ''}">${esc(c.verdict || 'not yet run')}</span></label>`;
    }).join('')}</div>`;
}

async function pollRun() {
  try {
    const s = await api('/api/status');
    const busy = s.busy;
    $('#run-state').textContent = busy
      ? `running ${s.current} (started ${s.started})`
      : (s.done && s.done.length
         ? `finished: ${s.done.map(d => `${d.id}→${d.rc}`).join(', ')}` : '');
    $('#run-btn').disabled = busy;
    $('#stop-btn').style.display = busy ? '' : 'none';
    if (busy || (s.done && s.done.length)) {
      const l = await api('/api/log');
      const pre = $('#run-log');
      pre.style.display = '';
      const stick = pre.scrollTop + pre.clientHeight >= pre.scrollHeight - 30;
      pre.textContent = l.log || '(no output yet)';
      if (stick) pre.scrollTop = pre.scrollHeight;
    }
    if (busy && !logTimer) logTimer = setInterval(pollRun, 4000);
    if (!busy && logTimer) { clearInterval(logTimer); logTimer = null; }
  } catch (e) { /* server gone mid-poll; next action re-reports */ }
}

async function initRunPanel() {
  try {
    const s = await api('/api/status');
    API = true;
    renderKeys(s.keys); renderJobs(s.jobs, s);
    refreshEngineKeyPills(s.keys);
    $('#run-btn').onclick = async () => {
      const jobs = [...document.querySelectorAll('#job-opts input[data-job]:checked')]
        .map(i => i.dataset.job);
      if (!jobs.length) { $('#run-state').textContent = 'nothing selected'; return; }
      const claims = [...document.querySelectorAll('#job-opts input[data-claim]:checked')]
        .map(i => i.dataset.claim);
      if (jobs.includes('theoria') && !claims.length) {
        $('#run-state').textContent =
          'theoria: tick the claim(s) to verify — it never sweeps the queue';
        return;
      }
      try { await api('/api/run', {jobs, claims}); pollRun(); }
      catch (e) { $('#run-state').textContent = e.message; }
    };
    $('#stop-btn').onclick = async () => { await api('/api/stop'); pollRun(); };
    pollRun();
  } catch (e) {
    API = false;
    $('#keys-panel').innerHTML = $('#job-opts').innerHTML = '';
    $('#job-opts').innerHTML = P && P.static
      ? `<div class="note"><strong>Read-only copy.</strong> This is a static export of the panel:
         it shows the pack's results but cannot start anything. Runs are started from a local
         checkout of the hub (<code>python panel/server.py</code>); the command list below is
         what they run.</div>`
      : `<div class="note warn"><strong>Static serving, trigger offline.</strong> This page is
         being served without its backend, so keys and the Run button are disabled. Start it from
         the hub with <code>python panel/server.py</code> and reload; the command list below works
         regardless.</div>`;
    $('#run-btn').disabled = true; $('#stop-btn').style.display = 'none';
  }
}

fetch('ledger.json').then(r => r.json()).then(d => { LEDGER = d; renderLedger(); renderTheoria(); })
  .catch(e => {
    const n = $('#ledger');
    if (n) n.innerHTML = `<div class="note bad">ledger.json is not built yet: run
      <code>python scoreboard/build_ledger.py</code> in the hub. ${esc(e.message)}</div>`;
  });

/* ================= CORPUS INTAKE =================
   Parses a seed bibliography in the browser — nothing is uploaded. We
   extract what stage A actually needs (DOIs, failing that titles), report
   honestly what could not be resolved, and emit the seed CSV plus the
   exact command sequence. The heavy lifting stays in the documented CLI;
   the page's job is to validate and to stop a malformed seed set from
   becoming a silently truncated corpus. */

const DOI_RE = /10\.\d{4,9}\/[-._;()/:A-Z0-9<>]+/gi;

function parseSeeds(text, filename) {
  const ext = (filename.split('.').pop() || '').toLowerCase();
  const entries = [];
  const seen = new Set();
  const push = (doi, title) => {
    const k = (doi || title || '').toLowerCase().trim();
    if (!k || seen.has(k)) return;
    seen.add(k);
    entries.push({doi: doi || '', title: (title || '').trim()});
  };

  if (ext === 'bib') {
    text.split(/@\w+\s*\{/).slice(1).forEach(rec => {
      const doi = (rec.match(/doi\s*=\s*[{"]([^}"]+)/i) || [])[1];
      const title = (rec.match(/title\s*=\s*[{"]([^}"]+)/i) || [])[1];
      push(doi, title);
    });
  } else if (ext === 'ris') {
    text.split(/\n(?=TY\s+-)/).forEach(rec => {
      const doi = (rec.match(/^DO\s+-\s*(.+)$/im) || [])[1];
      const title = (rec.match(/^TI\s+-\s*(.+)$/im) || [])[1];
      push(doi, title);
    });
  } else if (ext === 'json') {
    try {
      const j = JSON.parse(text);
      (Array.isArray(j) ? j : j.items || []).forEach(o =>
        push(o.DOI || o.doi, o.title));
    } catch (e) { /* fall through to the generic scan below */ }
  } else if (ext === 'csv' || ext === 'tsv') {
    const sep = ext === 'tsv' ? '\t' : ',';
    const lines = text.split(/\r?\n/).filter(l => l.trim());
    const head = (lines.shift() || '').split(sep).map(h =>
      h.replace(/^"|"$/g, '').trim().toLowerCase());
    const di = head.findIndex(h => h === 'doi' || h.endsWith(' doi'));
    const ti = head.findIndex(h => h === 'title' || h.includes('title'));
    lines.forEach(l => {
      const c = l.split(sep).map(x => x.replace(/^"|"$/g, ''));
      push(di >= 0 ? c[di] : '', ti >= 0 ? c[ti] : '');
    });
  }
  // plain text, or anything the structured parse got nothing from
  if (!entries.length) {
    (text.match(DOI_RE) || []).forEach(d => push(d, ''));
  }
  return entries.map(e => ({
    doi: (e.doi || '').replace(/^https?:\/\/(dx\.)?doi\.org\//i, '').trim(),
    title: e.title,
  }));
}

function renderCorpusIntake() {
  const f = $('#seedfile');
  if (!f) return;
  let parsed = [], chosen = '', pdfs = [];
  const redraw = () => {
    const name = ($('#cname').value || 'my-field').replace(/[^a-zA-Z0-9._-]/g, '-');
    const hops = $('#hops').value, ft = $('#ft').checked, reg = $('#reg').checked;
    const withDoi = parsed.filter(e => e.doi).length;
    const titleOnly = parsed.length - withDoi;

    if (parsed.length) {
      const pct = Math.round(withDoi / parsed.length * 100);
      $('#parse-out').innerHTML =
        `<div class="grid" style="margin:.4rem 0;grid-template-columns:1fr 1fr">
          ${card(parsed.length, 'seed references parsed')}
          ${card(pct + '%', 'carry a DOI (resolve cleanly)')}
        </div>` +
        (titleOnly ? `<div class="note warn" style="margin:.5rem 0"><strong>${titleOnly}
          entries have no DOI.</strong> Stage A will try to match them by title, and will report
          any it cannot resolve rather than dropping them silently. The biophoton pack resolved 245 of
          263 this way.</div>` : '') +
        `<button id="dl">Download ${esc(name)}_seeds.csv</button>`;
      $('#dl').onclick = () => {
        const csv = 'doi,title\n' +
          parsed.map(e => csvRow([e.doi, e.title || ''])).join('\n');
        const a = document.createElement('a');
        a.href = URL.createObjectURL(new Blob([csv], {type: 'text/csv'}));
        a.download = name + '_seeds.csv';
        a.click();
      };
    } else if (chosen) {
      $('#parse-out').innerHTML = `<div class="note bad">Nothing recognisable in
        <code>${esc(chosen)}</code>. Expected BibTeX, RIS, CSV/TSV with a doi or title column,
        CSL-JSON, or a plain list of DOIs.</div>`;
    } else {
      $('#parse-out').innerHTML =
        '<p style="color:var(--muted);font-size:.88rem">No file chosen yet.</p>';
    }

    if ($('#pdf-out')) {
      if (pdfs.length) {
        const withDoi = pdfs.filter(x => x.doi).length;
        $('#pdf-out').innerHTML =
          `<div class="grid" style="margin:4px 0;grid-template-columns:1fr 1fr">
             ${card(pdfs.length, 'PDFs staged')}
             ${card(withDoi, 'with a DOI in the filename')}
           </div>
           <table><thead><tr><th>File</th><th>MB</th><th>DOI</th></tr></thead><tbody>` +
          pdfs.slice(0, 12).map(x => `<tr><td>${esc(x.name.slice(0, 58))}</td>` +
            `<td>${x.mb}</td><td>${x.doi ? '<code>' + esc(x.doi) + '</code>'
              : '<span class="pill warn">add by hand</span>'}</td></tr>`).join('') +
          (pdfs.length > 12 ? `<tr><td colspan="3">… and ${pdfs.length - 12} more</td></tr>` : '') +
          `</tbody></table><button id="dlpdf">Download ${esc(name)}_curated.csv</button>` +
          (withDoi < pdfs.length ? `<div class="note warn">${pdfs.length - withDoi} file(s)
            carry no DOI in the filename. Fill the doi and title columns in the CSV before
            ingesting — a curated work with neither cannot be cross-referenced against the
            field map, and will be ingested as an unlinked reference.</div>` : '');
        const b = $('#dlpdf');
        if (b) b.onclick = () => {
          const csv = 'file,doi,title,year,note\n' + pdfs.map(x =>
            csvRow([x.name, x.doi, '', '', 'closed-access or hand-collected'])).join('\n');
          const a = document.createElement('a');
          a.href = URL.createObjectURL(new Blob([csv], {type: 'text/csv'}));
          a.download = name + '_curated.csv';
          a.click();
        };
      } else {
        $('#pdf-out').innerHTML =
          '<p style="color:var(--color-gray);font-size:var(--text-sm)">No PDFs staged. ' +
          'Open-access papers are fetched automatically at stage I.</p>';
      }
    }

    const L = [`# corpus: ${name}${parsed.length ? `  (${parsed.length} seeds)` : ''}`,
      `mkdir -p corpora/${name} && mv ~/Downloads/${name}_seeds.csv corpora/${name}/seeds.csv`,
      '', 'cd biophoton-fieldmap/src',
      `export CORPUS=${name}`, '',
      '# A  resolve seeds to canonical work ids',
      '../.venv/bin/python seed_resolve.py',
      '# B  citation expansion  → the publication universe',
      `../.venv/bin/python expand.py --hops ${hops}`,
      '# C  normalise into the relational store',
      '../.venv/bin/python build_db.py',
      '# D  coupling graphs + Leiden communities',
      '../.venv/bin/python networks.py',
      ];
    if ($('#openness') && $('#openness').checked) L.push(
      '# E  openness overlay (optional — analysis only, no engine reads it)',
      '../.venv/bin/python openness.py');
    if (ft) L.push('',
      '# I  harvest open-access PDFs (resumable)',
      '../.venv/bin/python harvest_oa_pdfs.py',
      '# J  full text + open-problem statement mining',
      '../.venv/bin/python extract_fulltext.py');
    if (pdfs.length) L.push('',
      `# I2 closed-access and hand-collected PDFs (${pdfs.length} file(s))`,
      `mkdir -p ../../literature/curated && cp ~/Downloads/*.pdf ../../literature/curated/`,
      `mv ~/Downloads/${name}_curated.csv ../../literature/curated/manifest.csv`,
      '../.venv/bin/python consolidate_literature.py',
      '# make them retrievable by the engines (marks outside_universe=1',
      '#     so field-map counts are unchanged)',
      '../.venv/bin/python ingest_reference_works.py');
    L.push('# K  one FTS5-searchable knowledgebase — what the corpus API serves',
      '../.venv/bin/python build_knowledgebase.py');
    if (reg) L.push('',
      '# M  claim registry + evidence linkage (enables ground-truth scoring)',
      '../.venv/bin/python hypothesis_inventory.py',
      '../.venv/bin/python hypothesis_registry_v2.py');
    L.push('', '# then configure the run',
      '../.venv/bin/python ../../hub/build_seeds.py');

    $('#corpus-cmd').innerHTML =
      `<h3>Commands for this corpus</h3><pre><code>${esc(L.join('\n'))}</code></pre>` +
      (reg ? '' : '<div class="note warn">Without a claim registry you can generate and certify ' +
        'hypotheses, but you cannot measure rediscovery or benchmark a verifier — there is no ' +
        'ground truth to score against.</div>');
  };

  const pf = $('#pdffiles');
  if (pf) pf.onchange = () => {
    pdfs = [...pf.files].map(x => ({
      name: x.name,
      mb: (x.size / 1048576).toFixed(1),
      // a DOI is often already in the filename; offer it rather than demand it
      doi: (x.name.match(/10\.\d{4,9}[._-][^\s]+/) || [''])[0]
             .replace(/[._-]pdf$/i, '').replace(/_/g, '/'),
    }));
    redraw();
  };

  f.onchange = () => {
    const file = f.files[0];
    if (!file) return;
    const r = new FileReader();
    r.onload = () => {
      chosen = file.name;
      parsed = parseSeeds(String(r.result), file.name);
      redraw();
    };
    r.readAsText(file);
  };
  ['#cname', '#hops', '#ft', '#reg', '#openness'].forEach(s => {
    const el = $(s); if (el) el.oninput = el.onchange = redraw;
  });
  redraw();
}
