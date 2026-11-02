'use strict';
/* VAYORA AI - main application logic. */
const S = {
  cfg: { features: {} }, map: null, origin: null, dest: null, mode: 'walk',
  weights: LS.get('weights', { safety: 50, pollution: 35, time: 15 }),
  result: null, sel: null, best: null, pick: null, analyzing: false, reanalyzeT: null,
  contacts: LS.get('contacts', []), name: LS.get('name', ''), saved: LS.get('saved', []),
  showSafe: true, repPos: null, repCat: 'poor_lighting', repSev: 2, myPos: null, intel: null,
  live: { on: false, sim: false, watch: null, timer: null, P: null, trip: null, offN: 0, asking: false, askLeft: 0, askTimer: null, alerts: [], passed: {}, high: false, pm: false, simM: 0, detour: false, detAmt: 0, pingAt: 0, pos: null, last: null }
};
const CAT = { poor_lighting: 'Poor lighting', harassment: 'Harassment', unsafe_crowd: 'Unsafe crowd', isolated: 'Isolated stretch', road_hazard: 'Road hazard', pollution_source: 'Smoke or dust', other: 'Other' };
const TRAVEL = { walk: 'walking', cycle: 'bicycling', scooter: 'two-wheeler', drive: 'driving' };

/* ------------------------------------------------------------ navigation */
function go(v) {
  $('#home').hidden = v === 'app'; $('#app').hidden = v !== 'app';
  $$('.links [data-go]').forEach(b => b.classList.toggle('on', b.dataset.go === v));
  if (v === 'app') setTimeout(() => S.map && S.map.resize(), 60);
  else if (v === 'how') $('#how').scrollIntoView({ behavior: 'smooth' });
  else window.scrollTo({ top: 0, behavior: 'smooth' });
}
function showTab(t) {
  $$('#tabs button').forEach(b => b.classList.toggle('on', b.dataset.tab === t));
  $$('.pane').forEach(p => p.hidden = p.id !== 'pane-' + t);
  if (t === 'live') renderLiveShell();
  if (t === 'intel' && S.result && S.result.intel && !S.intel) { S.intel = S.result.intel; renderIntel(); }
}

/* ------------------------------------------------------------ map */
async function initMap() {
  const key = LS.get('gkey', '') || S.cfg.google_js_key || '';
  let ad = null;
  if (key) {
    try { await loadGoogle(key); ad = new GoogleMapAdapter(); await ad.init($('#map')); $('#b3d').hidden = false; }
    catch (e) { toast('Google Maps could not load, using the free OpenStreetMap map.'); ad = null; resetMapEl(); }
  }
  if (!ad) { ad = new LeafletMapAdapter(); await ad.init($('#map')); }
  S.map = ad; ad.onClick(onMapClick); $('#mapProv').textContent = ad.name;
  window.gm_authFailure = () => { toast('Google rejected the Maps key. Switching to OpenStreetMap.'); resetMapEl(); initLeafletFallback(); };
}
function resetMapEl() { const el = $('#map'), n = el.cloneNode(false); el.replaceWith(n); }
async function initLeafletFallback() {
  const ad = new LeafletMapAdapter(); await ad.init($('#map')); S.map = ad; ad.onClick(onMapClick); $('#mapProv').textContent = ad.name; $('#b3d').hidden = true;
  drawEndpoints(); if (S.result) drawMap();
}
function drawEndpoints() {
  if (!S.map) return;
  S.origin ? S.map.setMarker('o', { lat: S.origin.lat, lng: S.origin.lng, color: '#17c3a0', text: 'A' }) : S.map.removeMarker('o');
  S.dest ? S.map.setMarker('d', { lat: S.dest.lat, lng: S.dest.lng, color: '#6c4cf5', text: 'B' }) : S.map.removeMarker('d');
}
async function onMapClick(lat, lng) {
  if (!S.pick) return;
  const what = S.pick; S.pick = null;
  if (what === 'rep') { S.repPos = { lat, lng }; $('#repWhere').textContent = 'Pin set at ' + lat.toFixed(5) + ', ' + lng.toFixed(5); S.map.setMarker('rep', { lat, lng, color: '#f2546f', text: '!' }); return; }
  let label = lat.toFixed(5) + ', ' + lng.toFixed(5);
  try { label = (await api('/api/reverse?lat=' + lat + '&lng=' + lng, { timeout: 12000 })).label || label; } catch (e) {}
  setPoint(what, { lat, lng, label });
}
function setPoint(which, pt) {
  if (which === 'o') { S.origin = pt; $('#from').value = pt.label; } else { S.dest = pt; $('#to').value = pt.label; }
  S.result = null; S.sel = null; $('#results').innerHTML = ''; if (S.map) { S.map.clearRoutes(); S.map.setPoints('safe', [], '#17c3a0'); }
  drawEndpoints(); updateGo();
  if (S.origin && S.dest) S.map.fit([[S.origin.lat, S.origin.lng], [S.dest.lat, S.dest.lng]]); else S.map.panTo(pt.lat, pt.lng, 15);
}
function updateGo() { $('#analyze').disabled = !(S.origin && S.dest) || S.analyzing; }
function getPos(timeout = 9000) {
  return new Promise((res, rej) => {
    if (!navigator.geolocation) return rej(new Error('This device does not support location.'));
    navigator.geolocation.getCurrentPosition(p => { S.myPos = { lat: p.coords.latitude, lng: p.coords.longitude }; res(S.myPos); },
      e => rej(new Error(e.code === 1 ? 'Location permission was denied.' : 'Could not get your location.')), { enableHighAccuracy: true, timeout, maximumAge: 10000 });
  });
}

/* ------------------------------------------------------------ place search */
function bindSuggest(which) {
  const inp = $(which === 'o' ? '#from' : '#to'), list = $(which === 'o' ? '#fromList' : '#toList'); let t, seq = 0;
  inp.addEventListener('input', () => {
    clearTimeout(t); if (which === 'o') S.origin = null; else S.dest = null; updateGo();
    const q = inp.value.trim(); if (q.length < 3) { list.hidden = true; return; }
    t = setTimeout(async () => {
      const my = ++seq;
      try {
        const c = S.map ? S.map.center() : null;
        const r = await api('/api/suggest?q=' + encodeURIComponent(q) + (c ? '&lat=' + c.lat + '&lng=' + c.lng : ''), { timeout: 15000 });
        if (my !== seq) return;
        list._items = r.results;
        list.innerHTML = r.results.map((x, i) => '<button data-i="' + i + '">' + esc(x.label) + '</button>').join('') || '<button disabled>No places found. Try more words.</button>';
        list.hidden = false;
      } catch (e) { list.innerHTML = '<button disabled>' + esc(e.message) + '</button>'; list.hidden = false; }
    }, 350);
  });
  inp.addEventListener('keydown', e => { if (e.key === 'Enter' && !list.hidden) { const b = list.querySelector('button[data-i]'); if (b) b.click(); } });
  list.addEventListener('click', async e => {
    const b = e.target.closest('button[data-i]'); if (!b) return;
    let it = list._items[+b.dataset.i]; list.hidden = true;
    try { if (it.lat == null) it = await api('/api/place?id=' + encodeURIComponent(it.place_id)); setPoint(which, { lat: it.lat, lng: it.lng, label: it.label }); }
    catch (err) { toast(err.message); }
  });
  document.addEventListener('click', e => { if (!list.contains(e.target) && e.target !== inp) list.hidden = true; });
}
function renderSaved() {
  const el = $('#saved');
  el.innerHTML = S.saved.map((p, i) => '<button data-sv="' + i + '">★ ' + esc(p.name) + '</button>').join('') +
    '<button data-save="o">+ Save start</button><button data-save="d">+ Save destination</button>';
}

/* ------------------------------------------------------------ analysis */
const STEPS = ['Finding routes…', 'Scanning street lighting, open places, police and hospitals…', 'Reading the air quality forecast…', 'Checking live local news with TinyFish…', 'Scoring and comparing routes…'];
async function analyze() {
  if (S.analyzing) return;
  if (!S.origin || !S.dest) { toast('Choose a start and a destination first.'); return; }
  S.analyzing = true; $('#analyze').disabled = true; $('#loading').hidden = false; $('#results').innerHTML = '';
  let si = 0; $('#stepline').textContent = STEPS[0];
  const stepT = setInterval(() => { si = Math.min(si + 1, STEPS.length - 1); $('#stepline').textContent = STEPS[si]; }, 2500);
  try {
    const dep = $('#departMode').value === 'later' && $('#departAt').value ? new Date($('#departAt').value).toISOString() : null;
    const res = await api('/api/analyze', { method: 'POST', body: { origin: S.origin, destination: S.dest, mode: S.mode, depart_at: dep, weights: S.weights, use_intel: $('#useIntel').checked } });
    S.result = res; S.sel = res.recommended; rank(); renderResults(); drawMap(); loadReports();
    if (res.intel) { S.intel = res.intel; renderIntel(); }
  } catch (e) {
    $('#results').innerHTML = '<div class="hint" style="border:1px solid var(--bad)"><b>Could not compare routes.</b><br>' + esc(e.message) + '</div>';
  } finally { clearInterval(stepT); S.analyzing = false; $('#loading').hidden = true; updateGo(); }
}
function rank() {
  const R = S.result; if (!R) return; const w = S.weights, t = (w.safety + w.pollution + w.time) || 1;
  R.routes.forEach(r => { r.scores.combined = Math.round((w.safety * r.scores.safety + w.pollution * r.scores.pollution + w.time * r.scores.time) / t * 10) / 10; });
  S.best = R.routes.reduce((a, b) => b.scores.combined < a.scores.combined ? b : a).id;
}
const bar = (label, v) => '<div class="mb"><span>' + label + '</span><span class="track"><span class="fill" style="width:' + clamp(v, 0, 100) + '%;background:' + riskColor(v) + '"></span></span><b>' + Math.round(v) + '</b></div>';
const accBar = (label, v, max) => '<div class="mb"><span style="grid-column:1">' + esc(label) + '</span><span class="track"><span class="fill" style="width:' + clamp(v / max * 100, 0, 100) + '%;background:#6c4cf5"></span></span><b>' + v.toFixed(0) + '</b></div>';
const localTime = (iso, tz) => { const d = new Date(Date.parse(iso) + tz * 1000); return String(d.getUTCHours()).padStart(2, '0') + ':' + String(d.getUTCMinutes()).padStart(2, '0'); };
function mapsLink(r) {
  return 'https://www.google.com/maps/dir/?api=1&origin=' + S.origin.lat + ',' + S.origin.lng + '&destination=' + S.dest.lat + ',' + S.dest.lng + '&travelmode=' + (TRAVEL[S.mode] === 'two-wheeler' ? 'two-wheeler' : TRAVEL[S.mode]);
}
function renderResults() {
  const R = S.result; if (!R) return;
  const best = R.routes.find(r => r.id === S.best), sel = R.routes.find(r => r.id === S.sel) || best, wx = R.weather;
  const ordered = [...R.routes].sort((a, b) => a.scores.combined - b.scores.combined);
  const why = S.best === R.recommended ? R.why.map(w => '<li class="' + (w.ok ? '' : 'warn') + '">' + esc(w.text) + '</li>').join('') : '<li>Updating the explanation for your new priorities…</li>';
  const cards = ordered.map(r => {
    const b = band(r.scores.combined);
    return '<button class="rcard' + (r.id === S.sel ? ' on' : '') + '" data-r="' + r.id + '" style="--rc:' + ROUTE_COL[r.id] + '"><div class="rtop"><span class="rid">' + r.id + '</span><b>' + esc(r.name) + '</b>' +
      r.badges.map(x => '<span class="tag' + (x === 'Recommended' && r.id !== S.best ? ' alt' : x === 'Recommended' ? '' : ' alt') + '">' + (x === 'Recommended' ? (r.id === S.best ? 'Recommended' : 'Server pick') : x) + '</span>').join('') +
      '<span class="rtime">' + fmtDur(r.duration_s) + ' · ' + fmtDist(r.distance_m) + '</span></div>' +
      bar('Safety risk', r.scores.safety) + bar('Air pollution', r.scores.pollution) + bar('Time', r.scores.time) +
      '<div class="rcomb"><span>Combined risk</span><span class="chip ' + b.c + '">' + b.l + '</span><b>' + Math.round(r.scores.combined) + '</b></div></button>';
  }).join('');
  const st = sel.stats, bt = R.best_time, off = bt.best_offset_h;
  const factors = sel.factors.length ? sel.factors.map(f => accBar(f.name, f.points, Math.max(...sel.factors.map(x => x.points)))).join('') : '<div class="muted sm">No notable safety concerns found on this route.</div>';
  const notes = R.status.map(s => '<div><i class="' + (s.ok ? '' : 'no') + '"></i><span><b>' + esc(s.name) + ':</b> ' + esc(s.text) + '</span></div>').join('');
  const btText = off === 0 || bt.saving < 2 ? 'Leaving around ' + localTime(R.depart_at, R.tz_offset_s) + ' is already close to the best time in the next 12 hours.' :
    'Leaving in ' + off + ' h (around ' + localTime(bt.series[off].t, R.tz_offset_s) + ') lowers the combined risk by about ' + bt.saving + ' points.';
  $('#results').innerHTML =
    '<div class="reco"><div class="rtop"><span class="tag">Recommended</span><h3>' + esc(best.name) + '</h3></div>' +
    '<div class="muted sm">Confidence ' + R.confidence + '%' + (wx && wx.temp_c != null ? ' · ' + Math.round(wx.temp_c) + '°C, wind ' + Math.round(wx.wind_kmh) + ' km/h' : '') + ' · leaving ' + localTime(R.depart_at, R.tz_offset_s) + '</div>' +
    '<ul class="why">' + why + '</ul>' +
    '<div class="row2">' + (S.cfg.features.claude ? '<button class="btn sm" id="explainBtn">Explain in simple words</button>' : '') + '<button class="btn sm" id="shareRoute">Share this comparison</button></div><div id="explainOut" class="sm"></div></div>' +
    cards +
    '<div class="detail"><h3 style="font-size:15px">Route ' + sel.id + ' in detail</h3><div class="kpis" style="margin-top:8px">' +
      '<div class="kpi"><b>' + (sel.pm25 == null ? 'n/a' : Math.round(sel.pm25)) + '</b><span>PM2.5 µg/m³ · ' + esc(sel.aqi_label) + '</span></div>' +
      '<div class="kpi"><b>' + st.well_lit_pct + '%</b><span>Path with street lighting</span></div>' +
      '<div class="kpi"><b>' + st.active_pct + '%</b><span>Path near open places</span></div>' +
      '<div class="kpi"><b>' + sel.help_near + '</b><span>Police or hospital within 250 m</span></div>' +
      '<div class="kpi"><b>' + st.dark_pct + '%</b><span>Journey in darkness</span></div>' +
      '<div class="kpi"><b>' + (st.isolated_stretch_m ? fmtDist(st.isolated_stretch_m) : 'None') + '</b><span>Longest dark, empty stretch</span></div></div>' +
    '<h4>What drives the safety risk</h4>' + factors +
    '<h4>Risk along the route</h4><canvas class="chart" id="pfChart" aria-label="Risk along the selected route"></canvas>' +
    '<div class="row2"><button class="btn primary" id="startLive">Start live journey</button><a class="btn" target="_blank" rel="noopener" href="' + mapsLink(sel) + '">Open in Google Maps</a></div></div>' +
    '<div class="detail"><h3 style="font-size:15px">Best time to leave</h3><p class="sm muted" style="margin:4px 0 6px">' + btText + '</p><canvas class="chart" id="btChart" aria-label="Combined risk by departure time"></canvas></div>' +
    '<div class="notes">' + notes + '</div>';
  drawProfile($('#pfChart'), sel);
  drawBestTime($('#btChart'), bt.series, R.tz_offset_s, off, ROUTE_COL);
}
function drawMap() {
  const R = S.result; if (!R || !S.map) return;
  drawEndpoints(); S.map.drawRoutes(R.routes, S.sel, id => { S.sel = id; renderResults(); drawMap(); });
  const sel = R.routes.find(r => r.id === S.sel);
  S.map.setPoints('safe', S.showSafe ? sel.safe_points.map(p => ({ lat: p.lat, lng: p.lng, title: (p.type === 'police' ? 'Police' : p.type === 'hospital' ? 'Hospital' : p.type === 'pharmacy' ? 'Pharmacy' : p.type === 'fuel' ? 'Fuel station' : 'Help point') + (p.name ? ': ' + p.name : '') })) : [], '#17c3a0');
}
function fitResult() { const R = S.result; if (R) S.map.fit(R.routes.flatMap(r => r.polyline)); }
async function loadReports() {
  const R = S.result; if (!R) return;
  const pts = R.routes.flatMap(r => r.polyline), la = pts.map(p => p[0]), lo = pts.map(p => p[1]);
  try {
    const r = await api('/api/reports?south=' + (Math.min(...la) - .003) + '&west=' + (Math.min(...lo) - .003) + '&north=' + (Math.max(...la) + .003) + '&east=' + (Math.max(...lo) + .003), { timeout: 15000 });
    S.map.setPoints('reports', r.reports.map(x => ({ lat: x.lat, lng: x.lng, html: '<b>' + esc(CAT[x.category] || x.category) + '</b><br>Severity ' + x.severity + '/3' + (x.note ? '<br>' + esc(x.note) : '') + '<br><span style="color:#888">' + Math.max(0, Math.round((Date.now() / 1000 - x.created_at) / 86400)) + ' days ago</span>' })), '#f2546f');
  } catch (e) {}
}

/* ------------------------------------------------------------ live journey */
function prepPath(route) {
  const pl = route.polyline, cum = [0]; for (let i = 1; i < pl.length; i++) cum.push(cum[i - 1] + hav(pl[i - 1], pl[i]));
  return { pl, cum, total: cum[cum.length - 1] || 1, prof: route.profile, km: route.profile[route.profile.length - 1].d_km || 1 };
}
function nearestOnPath(P, lat, lng) {
  const kx = 111320 * Math.cos(lat * Math.PI / 180), ky = 110540; let best = { d: 1e12, m: 0 };
  for (let i = 0; i < P.pl.length - 1; i++) {
    const ax = (P.pl[i][1] - lng) * kx, ay = (P.pl[i][0] - lat) * ky, bx = (P.pl[i + 1][1] - lng) * kx, by = (P.pl[i + 1][0] - lat) * ky;
    const dx = bx - ax, dy = by - ay, L2 = dx * dx + dy * dy || 1e-9; let t = -(ax * dx + ay * dy) / L2; t = Math.max(0, Math.min(1, t));
    const d = Math.hypot(ax + t * dx, ay + t * dy); if (d < best.d) best = { d, m: P.cum[i] + t * Math.sqrt(L2) };
  }
  return best;
}
function pointAt(P, m) {
  m = clamp(m, 0, P.total); let i = 1; while (i < P.cum.length - 1 && P.cum[i] < m) i++;
  const t = (m - P.cum[i - 1]) / ((P.cum[i] - P.cum[i - 1]) || 1);
  return [P.pl[i - 1][0] + (P.pl[i][0] - P.pl[i - 1][0]) * t, P.pl[i - 1][1] + (P.pl[i][1] - P.pl[i - 1][1]) * t];
}
function liveRoute() { return S.result && S.result.routes.find(r => r.id === S.sel); }
function renderLiveShell() {
  const r = liveRoute(); $('#liveEmpty').hidden = !!r; $('#liveBox').hidden = !r; if (!r) return;
  $('#lvRoute').textContent = r.name; $('#lvSub').textContent = fmtDist(r.distance_m) + ' · ' + fmtDur(r.duration_s) + ' · ' + S.mode;
  drawProfile($('#lvChart'), r, S.live.last ? S.live.last.km : null); renderAlerts();
}
function liveAlert(text, cls) { S.live.alerts.unshift({ t: new Date().toTimeString().slice(0, 5), text, cls: cls || '' }); S.live.alerts = S.live.alerts.slice(0, 8); renderAlerts(); }
function renderAlerts() { const e = $('#lvAlerts'); if (e) e.innerHTML = S.live.alerts.length ? S.live.alerts.map(a => '<li class="' + a.cls + '"><b>' + a.t + '</b> ' + esc(a.text) + '</li>').join('') : '<li class="muted">Alerts appear here while you travel.</li>'; }
function startLive(sim) {
  const r = liveRoute(); if (!r) { toast('Compare routes first.'); return; }
  stopLive(true); const L = S.live; L.on = true; L.sim = sim; L.P = prepPath(r); L.offN = 0; L.passed = {}; L.high = false; L.pm = false; L.simM = 0; L.detour = false; L.detAmt = 0; L.alerts = [];
  $('#lvMode').textContent = sim ? 'Simulating' : 'GPS live'; $('#lvStart').hidden = $('#lvSim').hidden = true; $('#lvStop').hidden = false; $('#lvDetour').hidden = !sim; $('#lvDetour').textContent = 'Simulate detour';
  liveAlert(sim ? 'Simulation started. No GPS used.' : 'Live tracking started.', 'ok');
  if (sim) { L.timer = setInterval(simTick, 600); }
  else if (navigator.geolocation) { L.watch = navigator.geolocation.watchPosition(p => onPos(p.coords.latitude, p.coords.longitude), e => { liveAlert(e.code === 1 ? 'Location permission denied. Try Simulate walk.' : 'GPS signal lost.', 'bad'); }, { enableHighAccuracy: true, maximumAge: 2000, timeout: 20000 }); }
  else { liveAlert('This device has no GPS. Use Simulate walk.', 'bad'); }
  S.map.panTo(r.polyline[0][0], r.polyline[0][1], 16);
}
function simTick() {
  const L = S.live; L.simM += L.P.total / 100; if (L.detour) L.detAmt = Math.min(1, L.detAmt + .25); else L.detAmt = Math.max(0, L.detAmt - .25);
  const [la, lo] = pointAt(L.P, L.simM); onPos(la + .0016 * L.detAmt, lo + .0011 * L.detAmt);
}
function stopLive(quiet) {
  const L = S.live; clearInterval(L.timer); if (L.watch != null && navigator.geolocation) navigator.geolocation.clearWatch(L.watch);
  L.timer = null; L.watch = null; L.on = false; clearInterval(L.askTimer); L.asking = false; $('#lvAsk').hidden = true;
  $('#lvStart').hidden = $('#lvSim').hidden = false; $('#lvStop').hidden = true; $('#lvDetour').hidden = true; $('#lvMode').textContent = 'Idle';
  if (!quiet) liveAlert('Live tracking stopped.');
}
function onPos(lat, lng) {
  const L = S.live, r = liveRoute(); if (!L.on || !r) return;
  S.myPos = { lat, lng }; L.pos = { lat, lng }; S.map.setMarker('me', { lat, lng, color: '#2d7ff9', text: '' }); S.map.panTo(lat, lng);
  const n = nearestOnPath(L.P, lat, lng), frac = clamp(n.m / L.P.total), km = frac * L.P.km;
  let j = 0; while (j < r.profile.length - 1 && r.profile[j + 1].d_km <= km) j++;
  const p = r.profile[j]; L.last = { km, p };
  const set = (id, tile, v, shown) => { $(id).textContent = shown != null ? shown : Math.round(v); if (tile) $(tile).style.setProperty('--c', riskColor(v)); };
  set('#lvSafety', '#tSafety', p.safety); set('#lvAir', '#tAir', p.pollution, p.pm25 == null ? 'n/a' : Math.round(p.pm25)); set('#lvRisk', '#tRisk', p.combined);
  $('#lvEta').textContent = fmtDur(r.duration_s * (1 - frac)); $('#lvProg').style.width = frac * 100 + '%';
  drawProfile($('#lvChart'), r, km);
  if (p.safety > 70 && !L.high) { L.high = true; liveAlert('High-risk stretch ahead. Stay on busy, lit streets and keep your phone ready.', 'bad'); } else if (p.safety < 58) L.high = false;
  if (p.pm25 != null && p.pm25 > 100 && !L.pm) { L.pm = true; liveAlert('Air is poor here (PM2.5 about ' + Math.round(p.pm25) + '). Consider a mask.', 'mid'); } else if (p.pm25 != null && p.pm25 < 80) L.pm = false;
  r.safe_points.forEach(s => { const k = s.lat.toFixed(5) + s.lng.toFixed(5); if (!L.passed[k] && hav([lat, lng], [s.lat, s.lng]) < 90) { L.passed[k] = 1; liveAlert('Passing a safe point: ' + (s.name || s.type) + '.', 'ok'); } });
  if (n.d > 80) L.offN++; else L.offN = 0;
  if (L.offN >= 3 && !L.asking) askSafe();
  if (L.pingAt < Date.now() && L.trip) { L.pingAt = Date.now() + 5000; api('/api/trips/' + L.trip + '/ping', { method: 'POST', body: { lat, lng, status: L.asking ? 'check' : 'active' } }).catch(() => {}); }
  if (frac > .985 || L.P.total - n.m < 35) { liveAlert('You have arrived at your destination.', 'ok'); stopLive(true); $('#lvMode').textContent = 'Arrived'; if (L.trip) api('/api/trips/' + L.trip + '/ping', { method: 'POST', body: { lat, lng, status: 'arrived' } }).catch(() => {}); }
}
function askSafe() {
  const L = S.live; L.asking = true; L.askLeft = 10; $('#lvAsk').hidden = false; $('#askN').textContent = 10; liveAlert('You left the planned route. Safety check sent.', 'bad');
  L.askTimer = setInterval(() => { L.askLeft--; $('#askN').textContent = Math.max(0, L.askLeft); if (L.askLeft <= 0) { clearInterval(L.askTimer); L.asking = false; $('#lvAsk').hidden = true; openSOS('No response to the safety check after leaving the route', true); } }, 1000);
}
async function shareTrip() {
  const r = liveRoute(); if (!r) { toast('Compare routes first.'); return; }
  try {
    if (!S.live.trip) S.live.trip = (await api('/api/trips', { method: 'POST', body: { name: S.name || 'Traveller', route: { name: r.name, polyline: r.polyline, origin: S.origin.label, destination: S.dest.label } } })).id;
  } catch (e) { toast(e.message); return; }
  const url = location.origin + '/track.html?id=' + S.live.trip, text = (S.name || 'I') + ' is travelling to ' + S.dest.label.split(',')[0] + '. Follow my trip live: ' + url;
  showModal('<div class="mcard plain"><h2 style="font-size:20px">Share your live trip</h2><p class="muted sm">Anyone with this link can see your route and live position until you stop sharing. Share it only with people you trust.</p><div class="summary" id="shareUrl">' + esc(url) + '</div>' +
    '<div class="row2"><button class="btn primary" id="shCopy">Copy link</button><a class="btn" target="_blank" rel="noopener" href="https://wa.me/?text=' + encodeURIComponent(text) + '">WhatsApp</a><a class="btn" href="sms:' + smsNums() + smsSep() + 'body=' + encodeURIComponent(text) + '">Text</a>' + (navigator.share ? '<button class="btn" id="shNative">Share…</button>' : '') + '</div><button class="btn block" id="mClose" style="margin-top:6px">Done</button></div>');
  $('#shCopy').onclick = () => copyText(url); if ($('#shNative')) $('#shNative').onclick = () => navigator.share({ title: 'VAYORA live trip', text, url }).catch(() => {});
  if (!S.live.on) toast('Start the live journey so your position updates on the link.');
}
const smsNums = () => S.contacts.map(c => c.phone).filter(Boolean).join(',');
const smsSep = () => /iPhone|iPad|iPod/.test(navigator.userAgent) ? '&' : '?';
function copyText(t) { try { navigator.clipboard.writeText(t).then(() => toast('Copied'), () => toast('Copy was blocked by the browser')); } catch (e) { toast('Copy was blocked by the browser'); } }

/* ------------------------------------------------------------ SOS */
function showModal(html) { const m = $('#modal'); m.innerHTML = html; m.hidden = false; const c = $('#mClose'); if (c) c.onclick = closeModal; }
function closeModal() { $('#modal').hidden = true; $('#modal').innerHTML = ''; }
let sosTimer = null;
function openSOS(reason, auto) {
  clearInterval(sosTimer); let n = auto ? 3 : 5;
  showModal('<div class="mcard" role="alertdialog" aria-modal="true"><h2 style="color:var(--bad)">Sending SOS</h2><div class="count" id="sosN">' + n + '</div><p class="muted sm" style="text-align:center">' + esc(reason) + '. Your location and trip details go to your trusted contacts.</p><div class="row2" style="justify-content:center"><button class="btn primary" id="sosCancel">I am safe, cancel</button><button class="btn danger" id="sosNow">Send now</button></div></div>');
  $('#sosCancel').onclick = () => { clearInterval(sosTimer); closeModal(); liveAlert('SOS cancelled by you.', 'ok'); };
  $('#sosNow').onclick = () => { clearInterval(sosTimer); sendSOS(reason); };
  sosTimer = setInterval(() => { n--; const e = $('#sosN'); if (e) e.textContent = n; if (n <= 0) { clearInterval(sosTimer); sendSOS(reason); } }, 1000);
}
async function currentPos() {
  if (S.live.pos) return S.live.pos; if (S.myPos) return S.myPos;
  try { return await getPos(4000); } catch (e) { return S.origin ? { lat: S.origin.lat, lng: S.origin.lng } : { lat: 0, lng: 0 }; }
}
async function sendSOS(reason) {
  showModal('<div class="mcard"><h2>Sending…</h2><p class="muted">Getting your location and preparing the message.</p></div>');
  const pos = await currentPos(), r = liveRoute(), p = S.live.last && S.live.last.p;
  const body = { name: S.name || 'Traveller', lat: pos.lat, lng: pos.lng, reason, route_label: r ? r.name : '', destination: S.dest ? S.dest.label.split(',')[0] : '', risk: p ? p.combined : null,
    nearest_safe: nearestSafeText(pos), tracking_url: S.live.trip ? location.origin + '/track.html?id=' + S.live.trip : '', contacts: S.contacts };
  let res, offline = false;
  try { res = await api('/api/sos', { method: 'POST', body, timeout: 15000 }); }
  catch (e) {
    offline = true; const q = LS.get('sosq', []); q.push(body); LS.set('sosq', q);
    res = { summary: 'SOS from ' + body.name + '. ' + reason + '. Location: https://maps.google.com/?q=' + pos.lat.toFixed(6) + ',' + pos.lng.toFixed(6), maps_url: '', sms_sent: [], sms_enabled: false, note: 'Also call 112 (India) or your local emergency number.' };
  }
  const nums = smsNums(), sent = (res.sms_sent || []).filter(x => x.ok).length;
  showModal('<div class="mcard"><h2 style="color:var(--bad)">SOS ready</h2>' + (offline ? '<p class="sm" style="background:rgba(245,181,61,.2);padding:8px 10px;border-radius:10px">You seem to be offline. The alert is saved and will be sent when you are back online. Use the buttons below now.</p>' : '') +
    (sent ? '<p class="sm"><b>SMS sent</b> to ' + sent + ' contact(s) through Twilio.</p>' : '') +
    '<div class="summary">' + esc(res.summary) + '</div><div class="row2"><a class="btn danger" href="tel:112">Call 112</a>' + (nums ? '<a class="btn primary" href="sms:' + nums + smsSep() + 'body=' + encodeURIComponent(res.summary) + '">Text my contacts</a>' : '') +
    '<a class="btn" target="_blank" rel="noopener" href="https://wa.me/?text=' + encodeURIComponent(res.summary) + '">WhatsApp</a><button class="btn" id="sosCopy">Copy</button></div>' +
    (!S.contacts.length ? '<p class="sm muted">Add trusted contacts in Settings so the message can go to them in one tap.</p>' : '') + '<p class="sm muted">' + esc(res.note || '') + '</p><button class="btn block" id="mClose">Close</button></div>');
  $('#sosCopy').onclick = () => copyText(res.summary);
}
function nearestSafeText(pos) {
  const r = liveRoute(); if (!r || !r.safe_points.length) return '';
  let b = null, bd = 1e12; r.safe_points.forEach(s => { const d = hav([pos.lat, pos.lng], [s.lat, s.lng]); if (d < bd) { bd = d; b = s; } });
  return b ? (b.name || b.type) + ' (' + Math.round(bd) + ' m away)' : '';
}
async function flushSosQueue() {
  const q = LS.get('sosq', []); if (!q.length) return; const rest = [];
  for (const b of q) { try { await api('/api/sos', { method: 'POST', body: b, timeout: 15000 }); } catch (e) { rest.push(b); } }
  LS.set('sosq', rest); if (rest.length < q.length) toast('Saved SOS alert was sent now that you are online.');
}

/* ------------------------------------------------------------ TinyFish intel */
function areasForIntel() { return [S.origin && S.origin.label, S.dest && S.dest.label].filter(Boolean); }
async function scanIntel() {
  const areas = areasForIntel(); if (!areas.length) { toast('Choose a start or destination first (Plan tab).'); return; }
  $('#intelScan').disabled = true; $('#intelStatus').textContent = 'TinyFish is searching the web for fresh local updates…'; $('#intelList').innerHTML = '';
  try { S.intel = await api('/api/intel', { method: 'POST', body: { areas }, timeout: 60000 }); renderIntel(); }
  catch (e) { $('#intelStatus').innerHTML = '<span style="color:var(--bad)"><b>' + esc(e.message) + '</b></span>'; }
  finally { $('#intelScan').disabled = false; }
}
function renderIntel() {
  const I = S.intel; if (!I) return;
  $('#intelStatus').textContent = I.items.length ? I.items.length + ' relevant update(s) for: ' + I.queries.join(' and ') + '. Area advisory adds up to +' + Math.round(I.advisory_penalty * 100) + ' risk points.' : 'No relevant recent updates found for ' + I.queries.join(' and ') + '. That is good news, or the area has little coverage.';
  $('#intelList').innerHTML = I.items.map((x, i) => '<div class="intel" data-i="' + i + '"><div class="rtop"><span class="chip ' + (x.category === 'safety' ? 'bad' : x.category === 'air' ? 'mid' : '') + '">' + esc(x.category) + '</span><span class="muted sm">' + esc(x.source) + '</span></div><h4>' + esc(x.title) + '</h4><p>' + esc(x.snippet) + '</p><div class="row2" style="margin:0"><a class="btn sm" target="_blank" rel="noopener" href="' + esc(x.url) + '">Open source</a><button class="btn sm" data-deep="' + i + '">Verify with TinyFish agent</button></div><div class="deep"></div></div>').join('');
}
async function deepScan(i, btn) {
  const item = S.intel.items[i], box = btn.closest('.intel').querySelector('.deep'); btn.disabled = true; box.innerHTML = '<p class="sm muted">A TinyFish web agent is reading the page. This can take up to a minute…</p>';
  try {
    const r = await api('/api/intel/deep', { method: 'POST', body: { url: item.url }, timeout: 130000 });
    const res = typeof r.result === 'string' ? (() => { try { return JSON.parse(r.result); } catch (e) { return { summary: r.result }; } })() : (r.result || {});
    const rows = Object.entries(res).filter(([k, v]) => v != null && v !== '').map(([k, v]) => '<b>' + esc(k.replace(/_/g, ' ')) + '</b><span>' + esc(typeof v === 'object' ? JSON.stringify(v) : v) + '</span>').join('');
    box.innerHTML = '<div class="kv">' + (rows || '<span>No structured data returned.</span>') + '</div><p class="sm muted">Agent status: ' + esc(r.status) + (r.error ? ' · ' + esc(r.error) : '') + '</p>';
  } catch (e) { box.innerHTML = '<p class="sm" style="color:var(--bad)">' + esc(e.message) + '</p>'; }
  finally { btn.disabled = false; }
}

/* ------------------------------------------------------------ community report */
async function sendReport() {
  if (!S.repPos) { toast('Choose where it happened first.'); return; }
  try {
    await api('/api/reports', { method: 'POST', body: { lat: S.repPos.lat, lng: S.repPos.lng, category: S.repCat, severity: S.repSev, note: $('#repNote').value.trim() } });
    toast('Thank you. Your report helps others choose safer routes.'); $('#repNote').value = ''; S.map.removeMarker('rep'); S.repPos = null; $('#repWhere').textContent = 'No location chosen yet.';
    if (S.result) { loadReports(); analyze(); }
  } catch (e) { toast(e.message); }
}

/* ------------------------------------------------------------ settings */
function renderContacts() {
  $('#contacts').innerHTML = S.contacts.map((c, i) => '<div class="contact"><div><b>' + esc(c.name) + '</b><div class="muted sm">' + esc(c.phone || 'No phone') + '</div></div><button class="btn sm" data-cdel="' + i + '">Remove</button></div>').join('') || '<p class="sm muted">No contacts yet. Add people who should get your SOS and live trip.</p>';
}
async function runDiag() {
  $('#diagOut').innerHTML = '<div><span></span><span>Testing connections…</span></div>';
  try {
    const r = await api('/api/diagnostics', { timeout: 60000 });
    $('#diagOut').innerHTML = r.checks.map(c => '<div><span>' + (c.ok ? '✅' : '⚠️') + '</span><span><b>' + esc(c.name) + '</b> (' + c.ms + ' ms)<br><span class="muted">' + esc(c.detail) + '</span></span></div>').join('') +
      '<div><span>' + (r.claude ? '✅' : '➖') + '</span><span><b>Claude explanations</b><br><span class="muted">' + (r.claude ? 'Enabled' : 'Optional. Add ANTHROPIC_API_KEY to .env') + '</span></span></div>' +
      '<div><span>' + (r.sms ? '✅' : '➖') + '</span><span><b>Twilio SMS</b><br><span class="muted">' + (r.sms ? 'Enabled' : 'Optional. Add TWILIO_* keys to .env') + '</span></span></div>';
  } catch (e) { $('#diagOut').innerHTML = '<div><span>⚠️</span><span>' + esc(e.message) + '</span></div>'; }
}
function applyWeights(fromUI) {
  const w = S.weights; $('#wS').value = w.safety; $('#wP').value = w.pollution; $('#wT').value = w.time; $('#wSv').textContent = w.safety; $('#wPv').textContent = w.pollution; $('#wTv').textContent = w.time;
  LS.set('weights', w);
  $$('#presets button').forEach(b => b.classList.toggle('on', b.dataset.w === [w.safety, w.pollution, w.time].join(',')));
  if (fromUI && S.result) { rank(); renderResults(); clearTimeout(S.reanalyzeT); S.reanalyzeT = setTimeout(analyze, 900); }
}

/* ------------------------------------------------------------ wiring */
function bindUI() {
  document.addEventListener('click', e => {
    const g = e.target.closest('[data-go]'); if (g) go(g.dataset.go);
    const tg = e.target.closest('[data-tab-go]'); if (tg) showTab(tg.dataset.tabGo);
  });
  $$('#tabs button').forEach(b => b.onclick = () => showTab(b.dataset.tab));
  $('#settingsBtn').onclick = () => { go('app'); showTab('settings'); };
  $('#themeBtn').onclick = () => { const n = isDark() ? 'light' : 'dark'; document.documentElement.dataset.theme = n; LS.set('theme', n); S.map && S.map.setTheme(n === 'dark'); if (S.result) { renderResults(); } };
  bindSuggest('o'); bindSuggest('d');
  $('#swap').onclick = () => { const a = S.origin, b = S.dest; S.origin = b; S.dest = a; $('#from').value = b ? b.label : ''; $('#to').value = a ? a.label : ''; S.result = null; $('#results').innerHTML = ''; S.map.clearRoutes(); drawEndpoints(); updateGo(); };
  $('#locFrom').onclick = async () => { try { const p = await getPos(); let label = 'My location'; try { label = (await api('/api/reverse?lat=' + p.lat + '&lng=' + p.lng, { timeout: 10000 })).label; } catch (e) {} setPoint('o', { lat: p.lat, lng: p.lng, label }); } catch (e) { toast(e.message); } };
  $('#pickFrom').onclick = () => { S.pick = 'o'; toast('Tap the map to set your start.'); };
  $('#pickTo').onclick = () => { S.pick = 'd'; toast('Tap the map to set your destination.'); };
  $('#saved').onclick = e => {
    const sv = e.target.closest('[data-sv]'), sa = e.target.closest('[data-save]');
    if (sv) { const p = S.saved[+sv.dataset.sv]; setPoint(!S.origin ? 'o' : 'd', { lat: p.lat, lng: p.lng, label: p.label }); }
    if (sa) { const pt = sa.dataset.save === 'o' ? S.origin : S.dest; if (!pt) { toast('Choose that place first.'); return; } const name = (prompt('Name this place (for example Home, College, Work)') || '').trim().slice(0, 18); if (!name) return; S.saved.push({ name, lat: pt.lat, lng: pt.lng, label: pt.label }); LS.set('saved', S.saved); renderSaved(); }
  };
  $('#modes').onclick = e => { const b = e.target.closest('button'); if (!b) return; S.mode = b.dataset.m; $$('#modes button').forEach(x => x.classList.toggle('on', x === b)); if (S.result) analyze(); };
  $('#departMode').onchange = e => { const later = e.target.value === 'later'; $('#departAt').hidden = !later; if (later && !$('#departAt').value) { const d = new Date(Date.now() + 3600e3 - new Date().getTimezoneOffset() * 60000); $('#departAt').value = d.toISOString().slice(0, 16); } if (S.result) analyze(); };
  $('#departAt').onchange = () => S.result && analyze();
  $('#presets').onclick = e => { const b = e.target.closest('button'); if (!b) return; const [s, p, t] = b.dataset.w.split(',').map(Number); S.weights = { safety: s, pollution: p, time: t }; applyWeights(true); };
  [['#wS', 'safety'], ['#wP', 'pollution'], ['#wT', 'time']].forEach(([id, k]) => $(id).oninput = e => { S.weights[k] = +e.target.value; if (!(S.weights.safety + S.weights.pollution + S.weights.time)) S.weights[k] = 5; applyWeights(true); });
  $('#analyze').onclick = analyze;
  $('#results').onclick = async e => {
    const c = e.target.closest('.rcard'); if (c) { S.sel = c.dataset.r; renderResults(); drawMap(); return; }
    if (e.target.closest('#startLive')) { showTab('live'); startLive(false); return; }
    if (e.target.closest('#shareRoute')) { const r = S.result.routes.find(x => x.id === S.best); const t = 'VAYORA AI compared routes from ' + S.origin.label.split(',')[0] + ' to ' + S.dest.label.split(',')[0] + '. Best: ' + r.name + ' (combined risk ' + Math.round(r.scores.combined) + '/100, PM2.5 ' + (r.pm25 == null ? 'n/a' : Math.round(r.pm25)) + ', ' + fmtDur(r.duration_s) + ').'; if (navigator.share) navigator.share({ title: 'VAYORA AI', text: t }).catch(() => {}); else copyText(t); return; }
    if (e.target.closest('#explainBtn')) {
      const R = S.result, out = $('#explainOut'); out.textContent = 'Asking Claude…';
      const ctx = R.routes.map(r => r.id + ': ' + r.name + ', ' + fmtDist(r.distance_m) + ', ' + fmtDur(r.duration_s) + ', safety risk ' + r.scores.safety + ', pollution risk ' + r.scores.pollution + ', PM2.5 ' + r.pm25 + ', well lit ' + r.stats.well_lit_pct + '%, dark stretch ' + r.stats.isolated_stretch_m + ' m').join('\n') + '\nRecommended: ' + R.recommended + '\nReasons: ' + R.why.map(w => w.text).join('; ');
      try { const x = await api('/api/explain', { method: 'POST', body: { context: ctx }, timeout: 45000 }); out.textContent = x.text || 'Claude is not available right now.'; } catch (err) { out.textContent = err.message; }
    }
  };
  /* live */
  $('#lvStart').onclick = () => startLive(false); $('#lvSim').onclick = () => startLive(true); $('#lvStop').onclick = () => stopLive();
  $('#lvDetour').onclick = () => { S.live.detour = !S.live.detour; $('#lvDetour').textContent = S.live.detour ? 'Return to route' : 'Simulate detour'; };
  $('#lvShare').onclick = shareTrip;
  $('#askOk').onclick = () => { clearInterval(S.live.askTimer); S.live.asking = false; S.live.detour = false; S.live.offN = 0; $('#lvAsk').hidden = true; $('#lvDetour').textContent = 'Simulate detour'; liveAlert('You confirmed you are safe.', 'ok'); };
  $('#askSos').onclick = () => { clearInterval(S.live.askTimer); S.live.asking = false; $('#lvAsk').hidden = true; openSOS('User pressed SOS after leaving the route'); };
  $('#sosFab').onclick = () => openSOS('Manual SOS');
  addEventListener('online', flushSosQueue);
  addEventListener('keydown', e => { if (e.key === 'Escape' && !$('#modal').hidden) closeModal(); });
  /* map bar */
  $('#bLocate').onclick = async () => { try { const p = await getPos(); S.map.setMarker('me', { lat: p.lat, lng: p.lng, color: '#2d7ff9', text: '' }); S.map.panTo(p.lat, p.lng, 16); } catch (e) { toast(e.message); } };
  $('#bSafe').onclick = () => { S.showSafe = !S.showSafe; $('#bSafe').textContent = 'Safe points: ' + (S.showSafe ? 'on' : 'off'); drawMap(); };
  $('#b3d').onclick = () => S.map.tilt();
  /* intel */
  $('#intelScan').onclick = scanIntel; $('#intelList').onclick = e => { const b = e.target.closest('[data-deep]'); if (b) deepScan(+b.dataset.deep, b); };
  /* report */
  $('#repCats').onclick = e => { const b = e.target.closest('button'); if (!b) return; S.repCat = b.dataset.c; $$('#repCats button').forEach(x => x.classList.toggle('on', x === b)); };
  $('#repSev').onclick = e => { const b = e.target.closest('button'); if (!b) return; S.repSev = +b.dataset.s; $$('#repSev button').forEach(x => x.classList.toggle('on', x === b)); };
  $('#repPin').onclick = () => { S.pick = 'rep'; toast('Tap the map where it happened.'); };
  $('#repLoc').onclick = async () => { try { const p = await getPos(); S.repPos = p; $('#repWhere').textContent = 'Using your location'; S.map.setMarker('rep', { lat: p.lat, lng: p.lng, color: '#f2546f', text: '!' }); } catch (e) { toast(e.message); } };
  $('#repSend').onclick = sendReport;
  /* settings */
  $('#gKey').value = LS.get('gkey', ''); $('#tKey').value = LS.get('tkey', ''); $('#cName').value = S.name;
  $('#saveKeys').onclick = () => { LS.set('gkey', $('#gKey').value.trim()); LS.set('tkey', $('#tKey').value.trim()); toast('Saved. Reloading…'); setTimeout(() => location.reload(), 600); };
  $('#diagBtn').onclick = runDiag;
  $('#cName').oninput = e => { S.name = e.target.value.trim(); LS.set('name', S.name); };
  $('#cAdd').onclick = () => { const n = $('#cn').value.trim(), p = $('#cp').value.trim().replace(/[^\d+]/g, ''); if (!n) { toast('Enter a contact name.'); return; } S.contacts.push({ name: n, phone: p }); LS.set('contacts', S.contacts); $('#cn').value = $('#cp').value = ''; renderContacts(); };
  $('#contacts').onclick = e => { const b = e.target.closest('[data-cdel]'); if (b) { S.contacts.splice(+b.dataset.cdel, 1); LS.set('contacts', S.contacts); renderContacts(); } };
  addEventListener('resize', () => { if (S.result && !$('#app').hidden) { drawProfile($('#pfChart'), S.result.routes.find(r => r.id === S.sel)); drawBestTime($('#btChart'), S.result.best_time.series, S.result.tz_offset_s, S.result.best_time.best_offset_h, ROUTE_COL); } });
}

(async function init() {
  const t = LS.get('theme', null); if (t) document.documentElement.dataset.theme = t;
  try { S.cfg = await api('/api/config', { timeout: 8000 }); } catch (e) { toast(e.message, 5000); }
  bindUI(); renderContacts(); renderSaved(); applyWeights(false);
  await initMap();
  if (new URLSearchParams(location.search).get('app') === '1') go('app');
  flushSosQueue();
})();
