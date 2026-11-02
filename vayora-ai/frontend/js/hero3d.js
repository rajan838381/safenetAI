'use strict';
/* Light 3D: a slowly turning globe with route arcs on the home page, plus gentle card tilt. */
(function () {
  const cv = document.getElementById('hero3d');
  if (cv && window.THREE && !matchMedia('(prefers-reduced-motion: reduce)').matches) {
    try {
      const r = new THREE.WebGLRenderer({ canvas: cv, alpha: true, antialias: true });
      r.setPixelRatio(Math.min(devicePixelRatio || 1, 2));
      const scene = new THREE.Scene(), cam = new THREE.PerspectiveCamera(40, 1, .1, 50); cam.position.z = 5.2;
      const globe = new THREE.Group(); scene.add(globe);
      globe.add(new THREE.Mesh(new THREE.IcosahedronGeometry(1.6, 2), new THREE.MeshBasicMaterial({ color: 0x6c4cf5, wireframe: true, transparent: true, opacity: .35 })));
      globe.add(new THREE.Mesh(new THREE.SphereGeometry(1.55, 32, 24), new THREE.MeshBasicMaterial({ color: 0x17c3b2, transparent: true, opacity: .1 })));
      const pts = [], rnd = (() => { let s = 7; return () => (s = (s * 16807) % 2147483647) / 2147483647; })();
      const onSphere = (rad) => { const u = rnd() * 2 - 1, t = rnd() * Math.PI * 2, q = Math.sqrt(1 - u * u); return new THREE.Vector3(q * Math.cos(t) * rad, u * rad, q * Math.sin(t) * rad); };
      for (let i = 0; i < 260; i++) { const p = onSphere(1.62); pts.push(p.x, p.y, p.z); }
      const pg = new THREE.BufferGeometry(); pg.setAttribute('position', new THREE.Float32BufferAttribute(pts, 3));
      globe.add(new THREE.Points(pg, new THREE.PointsMaterial({ color: 0x17c3b2, size: .045 })));
      const arcs = [], cols = [0x17c3a0, 0xf5b53d, 0xf2546f];
      cols.forEach(c => {
        const a = onSphere(1.62), b = onSphere(1.62), m = a.clone().add(b).multiplyScalar(.5).normalize().multiplyScalar(2.25);
        const curve = new THREE.QuadraticBezierCurve3(a, m, b);
        globe.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(curve.getPoints(40)), new THREE.LineBasicMaterial({ color: c })));
        const dot = new THREE.Mesh(new THREE.SphereGeometry(.05, 12, 12), new THREE.MeshBasicMaterial({ color: c })); globe.add(dot); arcs.push({ curve, dot, t: rnd() });
      });
      const ring = new THREE.Mesh(new THREE.TorusGeometry(2.2, .008, 8, 120), new THREE.MeshBasicMaterial({ color: 0x8d73ff, transparent: true, opacity: .5 }));
      ring.rotation.x = 1.2; scene.add(ring);
      let mx = 0, my = 0;
      addEventListener('pointermove', e => { mx = (e.clientX / innerWidth - .5); my = (e.clientY / innerHeight - .5); });
      const size = () => { const w = cv.clientWidth, h = cv.clientHeight; if (w && h) { r.setSize(w, h, false); cam.aspect = w / h; cam.updateProjectionMatrix(); } };
      addEventListener('resize', size); size();
      (function loop() {
        requestAnimationFrame(loop);
        if (!cv.offsetParent || document.hidden) return;
        globe.rotation.y += .0045; globe.rotation.x += (my * .5 - globe.rotation.x) * .05; globe.rotation.z += (mx * .3 - globe.rotation.z) * .05;
        ring.rotation.z += .003;
        arcs.forEach(a => { a.t = (a.t + .004) % 1; a.dot.position.copy(a.curve.getPoint(a.t)); });
        r.render(scene, cam);
      })();
    } catch (e) { cv.style.display = 'none'; }
  }
  document.querySelectorAll('[data-tilt]').forEach(el => {
    el.addEventListener('pointermove', e => {
      const b = el.getBoundingClientRect(), x = (e.clientX - b.left) / b.width - .5, y = (e.clientY - b.top) / b.height - .5;
      el.style.transform = 'perspective(700px) rotateX(' + (-y * 8) + 'deg) rotateY(' + (x * 10) + 'deg) translateY(-3px)';
    });
    el.addEventListener('pointerleave', () => { el.style.transform = ''; });
  });
})();
