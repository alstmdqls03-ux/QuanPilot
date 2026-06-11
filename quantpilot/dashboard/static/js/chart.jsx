/* MINCODE — 캔들 차트 (canvas) + RSI 스트립 + Equity curve */
function cssVar(name, el) {
  return getComputedStyle(el || document.documentElement).getPropertyValue(name).trim();
}

function CandleChart({ candles, rsi, position, params, height = 430 }) {
  const ref = React.useRef(null);
  const wrapRef = React.useRef(null);

  React.useEffect(() => {
    const cv = ref.current, wrap = wrapRef.current;
    if (!cv || !wrap) return;
    const dpr = window.devicePixelRatio || 1;
    const W = wrap.clientWidth, H = height;
    cv.width = W * dpr; cv.height = H * dpr;
    cv.style.width = W + 'px'; cv.style.height = H + 'px';
    const ctx = cv.getContext('2d');
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    const UP = cssVar('--up'), DN = cssVar('--dn'), LINE = cssVar('--line'),
      TXT2 = cssVar('--txt3'), ACC = cssVar('--accent'), PANEL = cssVar('--panel');

    ctx.clearRect(0, 0, W, H);

    const N = 90; // 표시 봉 수
    const data = candles.slice(-N);
    const rsiData = rsi.slice(-N);
    const padR = 64, padT = 10;
    const rsiH = 64, volH = 36, gap = 8;
    const priceH = H - rsiH - volH - gap * 2 - padT - 16;
    const cw = (W - padR) / N;

    let lo = Infinity, hi = -Infinity, vMax = 0;
    data.forEach((c) => { lo = Math.min(lo, c.l); hi = Math.max(hi, c.h); vMax = Math.max(vMax, c.v); });
    if (position) { lo = Math.min(lo, position.stop); hi = Math.max(hi, ...position.targets.map((t) => t.price)); }
    const span = (hi - lo) || 1; lo -= span * 0.04; hi += span * 0.04;
    const y = (p) => padT + (hi - p) / (hi - lo) * priceH;
    const x = (i) => i * cw + cw / 2;

    // 그리드 + 가격축
    ctx.font = '10px "JetBrains Mono", monospace';
    ctx.fillStyle = TXT2; ctx.strokeStyle = LINE; ctx.lineWidth = 1;
    for (let g = 0; g <= 4; g++) {
      const p = lo + (hi - lo) * g / 4, yy = y(p);
      ctx.beginPath(); ctx.moveTo(0, yy + 0.5); ctx.lineTo(W - padR, yy + 0.5); ctx.stroke();
      ctx.fillText(p.toLocaleString('en-US', { maximumFractionDigits: 0 }), W - padR + 8, yy + 3);
    }

    // 거래량
    const volTop = padT + priceH + gap;
    data.forEach((c, i) => {
      ctx.fillStyle = c.c >= c.o ? UP : DN;
      ctx.globalAlpha = 0.45;
      const vh = Math.max(1, c.v / vMax * volH);
      ctx.fillRect(x(i) - cw * 0.32, volTop + volH - vh, cw * 0.64, vh);
      ctx.globalAlpha = 1;
    });

    // 캔들
    data.forEach((c, i) => {
      const up = c.c >= c.o;
      ctx.strokeStyle = ctx.fillStyle = up ? UP : DN;
      ctx.beginPath(); ctx.moveTo(x(i), y(c.h)); ctx.lineTo(x(i), y(c.l)); ctx.stroke();
      const bodyT = y(Math.max(c.o, c.c)), bodyB = y(Math.min(c.o, c.c));
      ctx.fillRect(x(i) - cw * 0.32, bodyT, cw * 0.64, Math.max(1, bodyB - bodyT));
    });

    // 포지션 라인 (entry / SL / TP)
    function hline(p, color, label, dash) {
      const yy = y(p);
      if (yy < padT - 4 || yy > padT + priceH + 4) return;
      ctx.save();
      ctx.strokeStyle = color; ctx.setLineDash(dash || [4, 4]); ctx.lineWidth = 1.2;
      ctx.beginPath(); ctx.moveTo(0, yy + 0.5); ctx.lineTo(W - padR, yy + 0.5); ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = color;
      const tw = ctx.measureText(label).width + 10;
      ctx.fillRect(W - padR - tw, yy - 8, tw, 16);
      ctx.fillStyle = PANEL || '#000';
      ctx.fillText(label, W - padR - tw + 5, yy + 3.5);
      ctx.restore();
    }
    if (position) {
      const be = Math.abs(position.stop - position.entry) < 0.01;
      if (!be) hline(position.entry, TXT2, 'ENTRY ' + position.entry.toFixed(0), [2, 3]);
      hline(position.stop, DN, (be ? 'SL=BE ' : 'SL ') + position.stop.toFixed(0));
      position.targets.forEach((t) => {
        if (!t.filled) hline(t.price, UP, t.label + ' ' + t.price.toFixed(0));
        else hline(t.price, cssVar('--ok') || UP, t.label + ' ✓');
      });
    }

    // 현재가 라인
    const last = data[data.length - 1];
    const lp = last.c, lyy = y(lp);
    ctx.strokeStyle = ACC; ctx.setLineDash([1, 3]);
    ctx.beginPath(); ctx.moveTo(0, lyy + 0.5); ctx.lineTo(W - padR, lyy + 0.5); ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle = ACC;
    ctx.fillRect(W - padR + 2, lyy - 9, padR - 4, 18);
    ctx.fillStyle = '#fff';
    ctx.font = 'bold 11px "JetBrains Mono", monospace';
    ctx.fillText(lp.toLocaleString('en-US', { maximumFractionDigits: 0 }), W - padR + 8, lyy + 4);

    // RSI 스트립
    const rTop = volTop + volH + gap;
    ctx.font = '10px "JetBrains Mono", monospace';
    ctx.strokeStyle = LINE;
    const ry = (v) => rTop + (100 - v) / 100 * rsiH;
    // 진입/청산 밴드 음영
    ctx.fillStyle = UP; ctx.globalAlpha = 0.10;
    ctx.fillRect(0, ry(params.entryLow), W - padR, ry(0) - ry(params.entryLow));
    ctx.fillStyle = DN;
    ctx.fillRect(0, ry(100), W - padR, ry(params.entryHigh) - ry(100));
    ctx.fillStyle = TXT2; ctx.globalAlpha = 0.12;
    ctx.fillRect(0, ry(params.exitHigh), W - padR, ry(params.exitLow) - ry(params.exitHigh));
    ctx.globalAlpha = 1;
    [params.entryLow, params.entryHigh].forEach((b) => {
      ctx.strokeStyle = LINE; ctx.setLineDash([2, 3]);
      ctx.beginPath(); ctx.moveTo(0, ry(b) + 0.5); ctx.lineTo(W - padR, ry(b) + 0.5); ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = TXT2; ctx.fillText(String(b), W - padR + 8, ry(b) + 3);
    });
    // RSI 라인
    ctx.strokeStyle = ACC; ctx.lineWidth = 1.4; ctx.beginPath();
    let started = false;
    rsiData.forEach((v, i) => {
      if (v == null) return;
      const xx = x(i), yy = ry(v);
      if (!started) { ctx.moveTo(xx, yy); started = true; } else ctx.lineTo(xx, yy);
    });
    ctx.stroke();
    ctx.fillStyle = TXT2;
    ctx.fillText('RSI(14)', 4, rTop + 10);

    // 시간축
    ctx.fillStyle = TXT2;
    for (let i = 0; i < N; i += 18) {
      if (!data[i]) continue;
      const d = new Date(data[i].ts);
      ctx.fillText(`${d.getMonth() + 1}/${d.getDate()} ${String(d.getHours()).padStart(2, '0')}h`, x(i) - 14, H - 3);
    }
  });

  return (
    <div ref={wrapRef} className="qp-chart-wrap">
      <canvas ref={ref}></canvas>
    </div>
  );
}

function EquityCurve({ equity, height = 110 }) {
  if (!equity || equity.length < 2) return null;
  const W = 600, H = height;
  const vals = equity.map((e) => e.eq);
  const min = Math.min(...vals), max = Math.max(...vals);
  const span = max - min || 1;
  const pts = vals.map((v, i) => `${(i / (vals.length - 1) * W).toFixed(1)},${(H - 6 - (v - min) / span * (H - 14)).toFixed(1)}`);
  const up = vals[vals.length - 1] >= vals[0];
  return (
    <div className="qp-eq">
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" height={H} preserveAspectRatio="none">
        <polygon points={`0,${H} ${pts.join(' ')} ${W},${H}`} className={'eq-fill ' + (up ? 'up' : 'dn')}></polygon>
        <polyline points={pts.join(' ')} className={'eq-line ' + (up ? 'up' : 'dn')} fill="none"></polyline>
      </svg>
      <div className="qp-eq-foot mono">
        <span>{QPFmt.usd(min, 0)}</span>
        <span>Equity (자본+미실현)</span>
        <span>{QPFmt.usd(max, 0)}</span>
      </div>
    </div>
  );
}

Object.assign(window, { CandleChart, EquityCurve });
