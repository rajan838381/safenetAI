'use strict';
/* Shared helpers: storage, API calls, colours, formatting. */
const $ = (s, r = document) => r.querySelector(s), $$ = (s, r = document) => [...r.querySelectorAll(s)];
const LS = {
  get(k, d) { try { const v = localStorage.getItem('vayora:' + k); return v == null ? d : JSON.parse(v); } catch (e) { return d; } },
  set(k, v) { try { localStorage.setItem('vayora:' + k, JSON.stringify(v)); } catch (e) {} },
  del(k) { try { localStorage.removeItem('vayora:' + k); } catch (e) {} }
};
const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const clamp = (v, a = 0, b = 1) => v < a ? a : v > b ? b : v;
const RISK_STOPS = [[0, [23, 195, 160]], [40, [245, 181, 61]], [75, [242, 84, 111]]];
function riskRGB(v) {
  v = clamp(v, 0, 100);
  for (let i = 1; i < RISK_STOPS.length; i++) {
    const a = RISK_STOPS[i - 1], b = RISK_STOPS[i];
    if (v <= b[0]) { const t = (v - a[0]) / (b[0] - a[0]); return a[1].map((c, k) => c + (b[1][k] - c) * t); }
  }
  return RISK_STOPS[2][1];
}
const riskColor = v => 'rgb(' + riskRGB(v).map(Math.round).join(',') + ')';
const band = v => v < 35 ? { l: 'Low', c: 'ok' } : v < 60 ? { l: 'Moderate', c: 'mid' } : { l: 'High', c: 'bad' };
const fmtDist = m => m < 1000 ? Math.round(m) + ' m' : (m / 1000).toFixed(1) + ' km';
const fmtDur = s => { const m = Math.round(s / 60); return m < 60 ? m + ' min' : Math.floor(m / 60) + ' h ' + (m % 60) + ' min'; };
function hav(a, b) {
  const R = 6371000, r = Math.PI / 180, dLa = (b[0] - a[0]) * r, dLo = (b[1] - a[1]) * r;
  const h = Math.sin(dLa / 2) ** 2 + Math.cos(a[0] * r) * Math.cos(b[0] * r) * Math.sin(dLo / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(h));
}
let toastT;
function toast(msg, ms = 2800) {
  const e = $('#toast'); e.textContent = msg; e.classList.add('on');
  clearTimeout(toastT); toastT = setTimeout(() => e.classList.remove('on'), ms);
}
async function api(path, { method = 'GET', body, timeout = 90000 } = {}) {
  const headers = { 'Content-Type': 'application/json' };
  const g = LS.get('gkey', ''), t = LS.get('tkey', '');
  if (g) headers['X-Google-Key'] = g;
  if (t) headers['X-TinyFish-Key'] = t;
  const ctl = new AbortController(), timer = setTimeout(() => ctl.abort(), timeout);
  try {
    const r = await fetch(path, { method, headers, body: body ? JSON.stringify(body) : undefined, signal: ctl.signal });
    const text = await r.text();
    let j = null; try { j = text ? JSON.parse(text) : null; } catch (e) {}
    if (!r.ok) {
      let d = j && j.detail;
      if (Array.isArray(d)) d = d.map(x => x.msg).join('; ');
      throw new Error(d || ('Request failed (' + r.status + ')'));
    }
    return j;
  } catch (e) {
    if (e.name === 'AbortError') throw new Error('The request took too long. Please try again.');
    if (e instanceof TypeError) throw new Error('Cannot reach the VAYORA server. Is it running?');
    throw e;
  } finally { clearTimeout(timer); }
}
