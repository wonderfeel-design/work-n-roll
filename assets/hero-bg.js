// Abstract hero backgrounds for Work'n'Roll. Pure functions of time; loop every P seconds.
window.WNRBG = (function () {
  const P = 8, TAU = Math.PI * 2;

  function field(ctx, w, h, t) {
    const ph = (t % P) / P;
    const hy = h * 0.36;
    const vx = w * 0.5 + Math.sin(ph * TAU) * w * 0.02;
    let g = ctx.createLinearGradient(0, 0, 0, hy);
    g.addColorStop(0, '#132018'); g.addColorStop(1, '#3d4a2c');
    ctx.fillStyle = g; ctx.fillRect(0, 0, w, hy + 1);
    const sun = ctx.createRadialGradient(w * 0.68, hy, 0, w * 0.68, hy, w * 0.55);
    sun.addColorStop(0, 'rgba(244,196,120,0.55)'); sun.addColorStop(0.35, 'rgba(230,170,100,0.18)'); sun.addColorStop(1, 'rgba(230,170,100,0)');
    ctx.fillStyle = sun; ctx.fillRect(0, 0, w, h);
    ctx.fillStyle = '#16261a'; ctx.fillRect(0, hy, w, h - hy);
    const N = 30, x0 = -1.6 * w, span = 4.2 * w;
    const proj = (bx, f) => [vx + (bx - vx) * f, hy + (h - hy) * f];
    for (let i = 0; i < N; i++) {
      const a = x0 + (i * span) / N, b = x0 + ((i + 1) * span) / N;
      const [ax1, ay1] = proj(a, 1.2), [bx1] = proj(b, 1.2);
      ctx.beginPath(); ctx.moveTo(vx, hy); ctx.lineTo(ax1, ay1); ctx.lineTo(bx1, ay1); ctx.closePath();
      ctx.fillStyle = i % 2 ? '#1c3121' : '#24402a'; ctx.fill();
    }
    const M = 16;
    for (let i = 0; i < N; i++) {
      if (i % 2) continue;
      const cxr = x0 + ((i + 0.5) * span) / N;
      for (let k = 0; k < M; k++) {
        const u = (k / M + ph) % 1;
        const f = Math.pow(u, 2.3) * 1.2;
        if (f < 0.01) continue;
        const [x, y] = proj(cxr, f);
        if (x < -40 || x > w + 40 || y > h + 40) continue;
        const r = 0.8 + f * 16;
        ctx.beginPath(); ctx.ellipse(x, y, r * 1.1, r * 0.7, 0, 0, TAU);
        ctx.fillStyle = `rgba(110,160,92,${Math.min(1, 0.25 + f)})`; ctx.fill();
        ctx.beginPath(); ctx.ellipse(x - r * 0.2, y - r * 0.25, r * 0.55, r * 0.35, 0, 0, TAU);
        ctx.fillStyle = `rgba(160,200,120,${Math.min(0.8, f * 0.8)})`; ctx.fill();
      }
    }
    g = ctx.createLinearGradient(0, hy - h * 0.05, 0, hy + h * 0.16);
    g.addColorStop(0, 'rgba(230,190,130,0)'); g.addColorStop(0.35, 'rgba(230,190,130,0.22)'); g.addColorStop(1, 'rgba(230,190,130,0)');
    ctx.fillStyle = g; ctx.fillRect(0, hy - h * 0.05, w, h * 0.21);
  }

  function site(ctx, w, h, t) {
    const ph = (t % P) / P;
    let g = ctx.createLinearGradient(0, 0, 0, h);
    g.addColorStop(0, '#0f141a'); g.addColorStop(0.7, '#1a2129'); g.addColorStop(1, '#141a20');
    ctx.fillStyle = g; ctx.fillRect(0, 0, w, h);
    const glow = ctx.createRadialGradient(w * 0.3, h * 0.75, 0, w * 0.3, h * 0.75, w * 0.6);
    glow.addColorStop(0, 'rgba(240,170,80,0.22)'); glow.addColorStop(1, 'rgba(240,170,80,0)');
    ctx.fillStyle = glow; ctx.fillRect(0, 0, w, h);
    const camX = 3 * Math.sin(ph * TAU), camY = 7, F = h * 0.95, cx = w * 0.55, cy = h * 0.6;
    const pr = (X, Y, Z) => [cx + ((X - camX) * F) / Z, cy - ((Y - camY) * F) / Z];
    const line = (p, q, col, lw) => { ctx.beginPath(); ctx.moveTo(p[0], p[1]); ctx.lineTo(q[0], q[1]); ctx.strokeStyle = col; ctx.lineWidth = lw; ctx.stroke(); };
    // ground grid
    for (let x = -30; x <= 30; x += 3) line(pr(x, 0, 8), pr(x, 0, 60), 'rgba(140,160,180,0.10)', 1);
    for (let z = 8; z <= 60; z += 3) line(pr(-30, 0, z), pr(30, 0, z), 'rgba(140,160,180,0.10)', 1);
    // building frame
    const X0 = -9, X1 = 6, Z0 = 20, Z1 = 30, L = 6, FH = 3.2;
    const xs = [], zs = [];
    for (let x = X0; x <= X1 + 0.01; x += 3) xs.push(x);
    for (let z = Z0; z <= Z1 + 0.01; z += 2.5) zs.push(z);
    for (let l = L; l >= 0; l--) {
      const y = l * FH;
      const c = [pr(X0, y, Z0), pr(X1, y, Z0), pr(X1, y, Z1), pr(X0, y, Z1)];
      if (l > 0) {
        ctx.beginPath(); ctx.moveTo(...c[0]); c.slice(1).forEach(p => ctx.lineTo(...p)); ctx.closePath();
        ctx.fillStyle = 'rgba(130,150,170,0.10)'; ctx.fill();
      }
      for (let i = 0; i < 4; i++) line(c[i], c[(i + 1) % 4], 'rgba(185,200,215,0.55)', 1.6);
    }
    xs.forEach(x => [Z0, Z1].forEach(z => line(pr(x, 0, z), pr(x, L * FH, z), 'rgba(185,200,215,0.45)', 1.4)));
    zs.forEach(z => [X0, X1].forEach(x => line(pr(x, 0, z), pr(x, L * FH, z), 'rgba(185,200,215,0.35)', 1.2)));
    // work lights
    [[-6, 1, Z0], [0, 3, Z0], [3, 2, Z0], [-3, 4, Z0], [6, 5, Z0 + 5]].forEach(([x, l, z], i) => {
      const [px, py] = pr(x + 1.5, l * FH - 1.2, z);
      const fl = 0.75 + 0.25 * Math.sin(ph * TAU * (i + 1) + i);
      const rg = ctx.createRadialGradient(px, py, 0, px, py, 60);
      rg.addColorStop(0, `rgba(255,190,90,${0.55 * fl})`); rg.addColorStop(1, 'rgba(255,190,90,0)');
      ctx.fillStyle = rg; ctx.fillRect(px - 60, py - 60, 120, 120);
      ctx.beginPath(); ctx.arc(px, py, 3, 0, TAU); ctx.fillStyle = '#ffd59a'; ctx.fill();
    });
    // crane
    const MX = 10, MZ = 24, MH = 30;
    const m0 = pr(MX, 0, MZ), m1 = pr(MX, MH, MZ);
    line(m0, m1, 'rgba(240,180,90,0.85)', 3);
    for (let y = 0; y < MH; y += 2) line(pr(MX - 0.5, y, MZ), pr(MX + 0.5, y + 2, MZ), 'rgba(240,180,90,0.45)', 1);
    const ang = Math.PI + 0.35 + 0.3 * Math.sin(ph * TAU);
    const J = 20, jx = MX + Math.cos(ang) * J, jz = MZ + Math.sin(ang) * J * 0.35;
    const tip = pr(jx, MH, jz), back = pr(MX - Math.cos(ang) * 6, MH, MZ - Math.sin(ang) * 2);
    line(back, tip, 'rgba(240,180,90,0.85)', 2.4);
    line(pr(MX, MH + 4, MZ), tip, 'rgba(240,180,90,0.5)', 1);
    line(pr(MX, MH + 4, MZ), back, 'rgba(240,180,90,0.5)', 1);
    line(m1, pr(MX, MH + 4, MZ), 'rgba(240,180,90,0.85)', 2);
    const hk = 0.6 + 0.4 * Math.sin(ph * TAU * 2);
    const hx = MX + Math.cos(ang) * J * 0.72, hz = MZ + Math.sin(ang) * J * 0.72 * 0.35;
    const h0 = pr(hx, MH, hz), h1 = pr(hx, MH - 8 - 6 * hk, hz);
    line(h0, h1, 'rgba(220,225,230,0.6)', 1);
    ctx.fillStyle = 'rgba(240,180,90,0.9)'; ctx.fillRect(h1[0] - 14, h1[1], 28, 8);
    const blink = Math.sin(ph * TAU * 8) > 0.2 ? 1 : 0.15;
    const top = pr(MX, MH + 4, MZ);
    const rg = ctx.createRadialGradient(top[0], top[1], 0, top[0], top[1], 26);
    rg.addColorStop(0, `rgba(255,70,50,${0.8 * blink})`); rg.addColorStop(1, 'rgba(255,70,50,0)');
    ctx.fillStyle = rg; ctx.fillRect(top[0] - 26, top[1] - 26, 52, 52);
  }

  return { P, field, site };
})();
