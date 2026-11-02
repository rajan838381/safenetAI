'use strict';
/* Small canvas charts (no libraries). */
function prepCanvas(cv) {
  const dpr = Math.min(2, window.devicePixelRatio || 1), w = cv.clientWidth, h = cv.clientHeight;
  if (!w || !h) return null;
  if (cv.width !== Math.round(w * dpr) || cv.height !== Math.round(h * dpr)) { cv.width = Math.round(w * dpr); cv.height = Math.round(h * dpr); }
  const g = cv.getContext('2d'); g.setTransform(dpr, 0, 0, dpr, 0, 0); g.clearRect(0, 0, w, h);
  const cs = getComputedStyle(document.documentElement);
  return { g, w, h, line: cs.getPropertyValue('--line').trim() || '#ccc', muted: cs.getPropertyValue('--muted').trim() || '#888', text: cs.getPropertyValue('--text').trim() || '#000' };
}
function axes(c, y0, y1, xlabels, L = 28, R = 8, T = 8, B = 18) {
  const { g, w, h } = c, pw = w - L - R, ph = h - T - B;
  g.font = '11px "Plus Jakarta Sans", system-ui, sans-serif'; g.fillStyle = c.muted; g.strokeStyle = c.line; g.lineWidth = 1;
  for (let i = 0; i <= 2; i++) {
    const v = y0 + (y1 - y0) * i / 2, y = T + ph - (v - y0) / (y1 - y0) * ph;
    g.beginPath(); g.moveTo(L, y); g.lineTo(w - R, y); g.stroke(); g.textAlign = 'right'; g.fillText(Math.round(v), L - 5, y + 4);
  }
  g.textAlign = 'center';
  xlabels.forEach((t, i) => g.fillText(t, L + pw * (xlabels.length === 1 ? 0.5 : i / (xlabels.length - 1)), h - 4));
  return { L, T, pw, ph, X: f => L + pw * f, Y: v => T + ph - (clamp(v, y0, y1) - y0) / (y1 - y0) * ph };
}
/* Risk along a route: coloured combined-risk area, plus safety and pollution lines. */
function drawProfile(cv, route, markerKm) {
  const c = prepCanvas(cv); if (!c || !route || !route.profile.length) return;
  const P = route.profile, total = P[P.length - 1].d_km || 1;
  const a = axes(c, 0, 100, ['0', (total / 2).toFixed(1), total.toFixed(1) + ' km']), g = c.g;
  const xs = P.map(p => a.X(p.d_km / total));
  for (let i = 1; i < P.length; i++) {
    g.fillStyle = riskColor(P[i].combined); g.globalAlpha = .35;
    g.beginPath(); g.moveTo(xs[i - 1], a.Y(P[i - 1].combined)); g.lineTo(xs[i], a.Y(P[i].combined)); g.lineTo(xs[i], a.Y(0)); g.lineTo(xs[i - 1], a.Y(0)); g.fill();
  }
  g.globalAlpha = 1;
  [['safety', '#6c4cf5'], ['pollution', '#17c3b2']].forEach(([k, col]) => {
    g.strokeStyle = col; g.lineWidth = 2; g.lineJoin = 'round'; g.beginPath();
    P.forEach((p, i) => i ? g.lineTo(xs[i], a.Y(p[k])) : g.moveTo(xs[i], a.Y(p[k]))); g.stroke();
  });
  if (markerKm != null) {
    const x = a.X(clamp(markerKm / total)); g.strokeStyle = c.text; g.setLineDash([4, 3]); g.beginPath(); g.moveTo(x, a.T); g.lineTo(x, a.T + a.ph); g.stroke(); g.setLineDash([]);
  }
  g.font = '11px "Plus Jakarta Sans", sans-serif'; g.textAlign = 'left';
  g.fillStyle = '#6c4cf5'; g.fillText('Safety risk', a.L + 6, 14); g.fillStyle = '#17c3b2'; g.fillText('Pollution', a.L + 76, 14);
}
/* Combined risk if you leave now, +1 h, +2 h ... for each route. */
function drawBestTime(cv, series, tz, bestOffset, colors) {
  const c = prepCanvas(cv); if (!c || !series.length) return;
  const ids = Object.keys(series[0].routes), all = series.flatMap(s => ids.map(i => s.routes[i]));
  const y0 = Math.max(0, Math.floor(Math.min(...all) / 10) * 10 - 5), y1 = Math.min(100, Math.ceil(Math.max(...all) / 10) * 10 + 5);
  const lab = s => { const d = new Date(Date.parse(s.t) + tz * 1000); return String(d.getUTCHours()).padStart(2, '0') + ':00'; };
  const idx = [0, Math.round((series.length - 1) / 3), Math.round((series.length - 1) * 2 / 3), series.length - 1];
  const a = axes(c, y0, y1, idx.map(i => lab(series[i]))), g = c.g;
  ids.forEach(id => {
    g.strokeStyle = colors[id]; g.lineWidth = 2.2; g.lineJoin = 'round'; g.beginPath();
    series.forEach((s, i) => { const x = a.X(i / (series.length - 1)), y = a.Y(s.routes[id]); i ? g.lineTo(x, y) : g.moveTo(x, y); }); g.stroke();
  });
  const x = a.X(bestOffset / (series.length - 1));
  g.fillStyle = '#17c3a0'; g.beginPath(); g.arc(x, a.Y(Math.min(...ids.map(i => series[bestOffset].routes[i]))), 5, 0, 7); g.fill();
  g.font = '11px "Plus Jakarta Sans", sans-serif'; g.textAlign = 'left';
  ids.forEach((id, i) => { g.fillStyle = colors[id]; g.fillText('Route ' + id, a.L + 6 + i * 62, 14); });
}
