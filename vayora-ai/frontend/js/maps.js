'use strict';
/* Map adapters: Google Maps (when a key is available) or free Leaflet + OpenStreetMap. Same interface for both. */
const ROUTE_COL = { A: '#5aa9ff', B: '#ffb347', C: '#d08bff' };

/* Split a route polyline into coloured pieces using its risk profile. */
function splitByRisk(route) {
  const pl = route.polyline, prof = route.profile;
  if (!prof || !prof.length || pl.length < 2) return [{ pts: pl, v: route.scores.combined }];
  const cum = [0];
  for (let i = 1; i < pl.length; i++) cum.push(cum[i - 1] + hav(pl[i - 1], pl[i]) / 1000);
  const total = cum[cum.length - 1] || 1, pTotal = prof[prof.length - 1].d_km || 1, segs = [];
  let cur = null;
  for (let i = 0; i < pl.length - 1; i++) {
    const dm = ((cum[i] + cum[i + 1]) / 2) / total * pTotal;
    let j = 0; while (j < prof.length - 1 && prof[j + 1].d_km <= dm) j++;
    const v = prof[j].combined, b = Math.round(v / 6);
    if (!cur || cur.b !== b) { cur = { b, v, pts: [pl[i]] }; segs.push(cur); }
    cur.pts.push(pl[i + 1]);
  }
  return segs;
}

function loadGoogle(key) {
  return new Promise((resolve, reject) => {
    if (window.google && window.google.maps) return resolve();
    const t = setTimeout(() => reject(new Error('Google Maps timed out')), 12000);
    window.__gmReady = () => { clearTimeout(t); resolve(); };
    const s = document.createElement('script');
    s.src = 'https://maps.googleapis.com/maps/api/js?key=' + encodeURIComponent(key) + '&callback=__gmReady&v=weekly';
    s.onerror = () => { clearTimeout(t); reject(new Error('Google Maps failed to load')); };
    document.head.appendChild(s);
  });
}

class GoogleMapAdapter {
  constructor() { this.name = 'Google Maps'; this.markers = {}; this.polys = []; this.layers = {}; this.supportsTilt = true; }
  async init(el) {
    this.map = new google.maps.Map(el, { center: { lat: 28.6139, lng: 77.209 }, zoom: 12, mapId: 'DEMO_MAP_ID', mapTypeControl: false, streetViewControl: false, fullscreenControl: false, clickableIcons: false });
    this.info = new google.maps.InfoWindow();
  }
  onClick(cb) { this.map.addListener('click', e => cb(e.latLng.lat(), e.latLng.lng())); }
  center() { const c = this.map.getCenter(); return { lat: c.lat(), lng: c.lng() }; }
  panTo(lat, lng, zoom) { this.map.panTo({ lat, lng }); if (zoom) this.map.setZoom(zoom); }
  setMarker(id, { lat, lng, color, text }) {
    this.removeMarker(id);
    this.markers[id] = new google.maps.Marker({ map: this.map, position: { lat, lng }, zIndex: 10,
      icon: { path: google.maps.SymbolPath.CIRCLE, scale: 13, fillColor: color, fillOpacity: 1, strokeColor: '#fff', strokeWeight: 3 },
      label: text ? { text, color: '#fff', fontWeight: '800', fontSize: '12px' } : undefined });
  }
  removeMarker(id) { if (this.markers[id]) { this.markers[id].setMap(null); delete this.markers[id]; } }
  clearRoutes() { this.polys.forEach(p => p.setMap(null)); this.polys = []; }
  drawRoutes(routes, selId, onSelect) {
    this.clearRoutes();
    const path = r => r.polyline.map(p => ({ lat: p[0], lng: p[1] }));
    routes.filter(r => r.id !== selId).forEach(r => {
      const pl = new google.maps.Polyline({ map: this.map, path: path(r), strokeColor: ROUTE_COL[r.id], strokeOpacity: .6, strokeWeight: 6, zIndex: 1 });
      pl.addListener('click', () => onSelect(r.id)); this.polys.push(pl);
    });
    const sel = routes.find(r => r.id === selId); if (!sel) return;
    this.polys.push(new google.maps.Polyline({ map: this.map, path: path(sel), strokeColor: '#ffffff', strokeOpacity: 1, strokeWeight: 11, zIndex: 2 }));
    splitByRisk(sel).forEach(s => this.polys.push(new google.maps.Polyline({ map: this.map, path: s.pts.map(p => ({ lat: p[0], lng: p[1] })), strokeColor: riskColor(s.v), strokeOpacity: 1, strokeWeight: 7, zIndex: 3 })));
  }
  setPoints(layer, pts, color) {
    (this.layers[layer] || []).forEach(m => m.setMap(null)); this.layers[layer] = [];
    pts.forEach(p => {
      const m = new google.maps.Marker({ map: this.map, position: { lat: p.lat, lng: p.lng }, title: p.title || '', zIndex: 5,
        icon: { path: google.maps.SymbolPath.CIRCLE, scale: 6, fillColor: color, fillOpacity: .95, strokeColor: '#fff', strokeWeight: 2 } });
      m.addListener('click', () => { this.info.setContent('<div style="font:13px sans-serif;max-width:220px">' + (p.html || esc(p.title || '')) + '</div>'); this.info.open(this.map, m); });
      this.layers[layer].push(m);
    });
  }
  fit(latlngs) {
    if (!latlngs.length) return;
    const b = new google.maps.LatLngBounds(); latlngs.forEach(p => b.extend({ lat: p[0], lng: p[1] }));
    this.map.fitBounds(b, 60);
  }
  setTheme() {}
  tilt() { const on = this.map.getTilt() > 0; this.map.setTilt(on ? 0 : 60); if (!on) { this.map.setZoom(Math.max(this.map.getZoom(), 16)); this.map.setHeading(45); } else this.map.setHeading(0); }
  resize() { google.maps.event.trigger(this.map, 'resize'); }
}

class LeafletMapAdapter {
  constructor() { this.name = 'OpenStreetMap'; this.markers = {}; this.polys = []; this.layers = {}; this.supportsTilt = false; }
  async init(el) {
    this.map = L.map(el, { zoomControl: true }).setView([28.6139, 77.209], 12);
    this.setTheme(isDark());
  }
  onClick(cb) { this.map.on('click', e => cb(e.latlng.lat, e.latlng.lng)); }
  center() { const c = this.map.getCenter(); return { lat: c.lat, lng: c.lng }; }
  panTo(lat, lng, zoom) { zoom ? this.map.setView([lat, lng], zoom) : this.map.panTo([lat, lng]); }
  setTheme(dark) {
    if (this.tile) this.map.removeLayer(this.tile);
    const u = dark ? 'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png' : 'https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png';
    this.tile = L.tileLayer(u, { subdomains: 'abcd', maxZoom: 19, attribution: '&copy; OpenStreetMap contributors &copy; CARTO' }).addTo(this.map);
  }
  setMarker(id, { lat, lng, color, text }) {
    this.removeMarker(id);
    const icon = L.divIcon({ className: '', iconSize: [26, 26], iconAnchor: [13, 13],
      html: '<div class="dot" style="background:' + color + ';width:26px;height:26px;display:grid;place-items:center;color:#fff;font:800 12px sans-serif">' + (text || '') + '</div>' });
    this.markers[id] = L.marker([lat, lng], { icon, zIndexOffset: 1000 }).addTo(this.map);
  }
  removeMarker(id) { if (this.markers[id]) { this.map.removeLayer(this.markers[id]); delete this.markers[id]; } }
  clearRoutes() { this.polys.forEach(p => this.map.removeLayer(p)); this.polys = []; }
  drawRoutes(routes, selId, onSelect) {
    this.clearRoutes();
    routes.filter(r => r.id !== selId).forEach(r => {
      const pl = L.polyline(r.polyline, { color: ROUTE_COL[r.id], weight: 6, opacity: .6 }).addTo(this.map);
      pl.on('click', () => onSelect(r.id)); this.polys.push(pl);
    });
    const sel = routes.find(r => r.id === selId); if (!sel) return;
    this.polys.push(L.polyline(sel.polyline, { color: '#ffffff', weight: 11, opacity: 1 }).addTo(this.map));
    splitByRisk(sel).forEach(s => this.polys.push(L.polyline(s.pts, { color: riskColor(s.v), weight: 7, opacity: 1, lineCap: 'round' }).addTo(this.map)));
  }
  setPoints(layer, pts, color) {
    (this.layers[layer] || []).forEach(m => this.map.removeLayer(m)); this.layers[layer] = [];
    pts.forEach(p => {
      const m = L.circleMarker([p.lat, p.lng], { radius: 6, color: '#fff', weight: 2, fillColor: color, fillOpacity: .95 }).addTo(this.map);
      m.bindPopup('<div style="font:13px sans-serif;max-width:220px">' + (p.html || esc(p.title || '')) + '</div>');
      this.layers[layer].push(m);
    });
  }
  fit(latlngs) { if (latlngs.length) this.map.fitBounds(L.latLngBounds(latlngs), { padding: [50, 50] }); }
  tilt() {}
  resize() { this.map.invalidateSize(); }
}
const isDark = () => (document.documentElement.dataset.theme || (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light')) === 'dark';
