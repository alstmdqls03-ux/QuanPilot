/* MINCODE — 공용 UI 컴포넌트 (Panel, 게이지, TP사다리, 비용분해 등) */
const { useState, useEffect, useRef, useMemo } = React;

// ---------- 포맷 ----------
const QPFmt = {
  usd(n, d = 2) {
    if (n == null || isNaN(n)) return '—';
    const s = Math.abs(n).toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d });
    return (n < 0 ? '-$' : '$') + s;
  },
  signUsd(n, d = 2) {
    if (n == null || isNaN(n)) return '—';
    const s = Math.abs(n).toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d });
    return (n >= 0 ? '+$' : '-$') + s;
  },
  px(n, d) {
    if (n == null || isNaN(n)) return '—';
    const dd = d != null ? d : (n >= 1000 ? 1 : 2);
    return n.toLocaleString('en-US', { minimumFractionDigits: dd, maximumFractionDigits: dd });
  },
  pct(n, d = 2) {
    if (n == null || isNaN(n)) return '—';
    return (n >= 0 ? '+' : '') + n.toFixed(d) + '%';
  },
  time(ts) {
    const d = new Date(ts);
    return String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0');
  },
  timeS(ts) {
    const d = new Date(ts);
    return QPFmt.time(ts) + ':' + String(d.getSeconds()).padStart(2, '0');
  },
  date(ts) {
    const d = new Date(ts);
    return `${d.getMonth() + 1}/${d.getDate()} ${QPFmt.time(ts)}`;
  },
};

// ---------- 패널 ----------
function Panel({ title, titleEn, right, children, className, pad = true, style }) {
  return (
    <section className={'qp-panel ' + (className || '')} style={style}>
      {title ? (
        <header className="qp-panel-hd">
          <h3 className="qp-panel-title">{title}{titleEn ? <span className="qp-panel-title-en">{titleEn}</span> : null}</h3>
          {right ? <div className="qp-panel-right">{right}</div> : null}
        </header>
      ) : null}
      <div className={'qp-panel-bd' + (pad ? '' : ' nopad')}>{children}</div>
    </section>
  );
}

function Stat({ label, value, sub, tone, mono = true, size }) {
  return (
    <div className="qp-stat">
      <div className="qp-stat-label">{label}</div>
      <div className={'qp-stat-value' + (mono ? ' mono' : '') + (tone ? ' tone-' + tone : '')} style={size ? { fontSize: size } : null}>{value}</div>
      {sub ? <div className="qp-stat-sub">{sub}</div> : null}
    </div>
  );
}

function Pill({ tone = 'default', children, pulse }) {
  return <span className={'qp-pill tone-' + tone + (pulse ? ' pulse' : '')}>{children}</span>;
}

// ---------- 루프 생존 상태 ----------
function LoopStatus({ s }) {
  const alive = s.running && !s.panic;
  const fresh = s.lastBarAgoSec;
  const stale = fresh != null && fresh > (s.staleAfterSec || 25);
  const freshTxt = fresh == null ? '—' : fresh < 120 ? fresh + 's' : Math.round(fresh / 60) + '분';
  return (
    <div className="qp-loop" data-comment-anchor="loop-status">
      <span className={'qp-heart ' + (s.panic ? 'dead' : alive ? 'alive' : 'paused')}></span>
      <div className="qp-loop-text">
        <strong>{s.panic ? 'PANIC' : s.breakerTripped ? 'BREAKER' : alive ? 'LOOP ALIVE' : 'PAUSED'}</strong>
        <span className={stale ? 'warn' : ''}>마지막 봉 {QPFmt.time(s.lastBarTs)} · 신선도 {freshTxt}</span>
      </div>
    </div>
  );
}

// ---------- RSI 신호 게이지 ----------
function RsiGauge({ rsi, p, compact }) {
  const v = rsi == null ? 50 : Math.max(0, Math.min(100, rsi));
  const zone = v < p.entryLow ? 'long' : v > p.entryHigh ? 'short' : (v >= p.exitLow && v <= p.exitHigh) ? 'exit' : 'hold';
  const zoneLabel = { long: 'LONG 진입 밴드', short: 'SHORT 진입 밴드', exit: '청산(중립) 밴드', hold: '대기 — 신호 없음' }[zone];
  const W = 100;
  return (
    <div className="qp-rsi">
      <div className="qp-rsi-head">
        <span className="qp-rsi-val mono">RSI(14) <b className={'z-' + zone}>{rsi == null ? '—' : rsi.toFixed(1)}</b></span>
        <Pill tone={zone === 'long' ? 'up' : zone === 'short' ? 'dn' : zone === 'exit' ? 'accent' : 'muted'}>{zoneLabel}</Pill>
      </div>
      <svg viewBox="0 0 100 16" className="qp-rsi-svg" preserveAspectRatio="none">
        <rect x="0" y="6" width={W} height="5" rx="2.5" className="rsi-track"></rect>
        <rect x="0" y="6" width={p.entryLow} height="5" rx="2.5" className="rsi-long"></rect>
        <rect x={p.entryHigh} y="6" width={100 - p.entryHigh} height="5" rx="2.5" className="rsi-short"></rect>
        <rect x={p.exitLow} y="6" width={p.exitHigh - p.exitLow} height="5" className="rsi-exit"></rect>
        <line x1={v} x2={v} y1="1" y2="15" className="rsi-needle"></line>
        <circle cx={v} cy="8.5" r="2.6" className="rsi-knob"></circle>
      </svg>
      <div className="qp-rsi-scale mono">
        <span>0</span><span style={{ position: 'absolute', left: p.entryLow + '%' }}>{p.entryLow}</span>
        <span style={{ position: 'absolute', left: p.exitLow + '%' }}>{p.exitLow}</span>
        <span style={{ position: 'absolute', left: p.exitHigh + '%' }}>{p.exitHigh}</span>
        <span style={{ position: 'absolute', left: p.entryHigh + '%' }}>{p.entryHigh}</span><span>100</span>
      </div>
      {!compact && (
        <p className="qp-rsi-why">
          {zone === 'hold' ? `왜 지금 안 사/안 팔아? — RSI가 진입 밴드(<${p.entryLow} 또는 >${p.entryHigh}) 밖, 청산 밴드(${p.exitLow}–${p.exitHigh}) 밖` :
            zone === 'long' ? `RSI < ${p.entryLow} → 과매도. 포지션 없으면 LONG 진입 신호` :
            zone === 'short' ? `RSI > ${p.entryHigh} → 과매수. 포지션 없으면 SHORT 진입 신호` :
            `RSI 중립 복귀(${p.exitLow}–${p.exitHigh}) → 보유 포지션 청산 신호`}
        </p>
      )}
    </div>
  );
}

// ---------- 서킷브레이커 게이지 ----------
function BreakerGauge({ s }) {
  const limit = (s.dayStartEquity || s.startCapital) * (s.params.breakerPct / 100);
  const used = Math.max(0, -s.dailyRealized);
  const ratio = Math.min(1, used / limit);
  const left = Math.max(0, limit - used);
  const tone = s.breakerTripped ? 'dn' : ratio > 0.6 ? 'warn' : 'ok';
  return (
    <div className="qp-breaker" data-comment-anchor="breaker-gauge">
      <div className="qp-breaker-row">
        <span className="qp-stat-label">일일 실현손익 / 서킷브레이커 −{s.params.breakerPct}%</span>
        <span className={'mono qp-breaker-num ' + (s.dailyRealized >= 0 ? 'tone-up' : 'tone-dn')}>{QPFmt.signUsd(s.dailyRealized)}</span>
      </div>
      <div className="qp-breaker-track">
        <div className={'qp-breaker-fill t-' + tone} style={{ width: (ratio * 100) + '%' }}></div>
        <div className="qp-breaker-limit"></div>
      </div>
      <div className="qp-breaker-foot mono">
        <span>{s.breakerTripped ? '⛔ 발동됨 — 루프 정지' : `한도까지 ${QPFmt.usd(left)} 여유`}</span>
        <span>limit −{QPFmt.usd(limit, 0).slice(1)}</span>
      </div>
    </div>
  );
}

// ---------- TP 사다리 ----------
function TpLadder({ pos, price }) {
  if (!pos) return <div className="qp-empty">포지션 없음 — 진입 시 1R/2R/3R 사다리가 표시됩니다</div>;
  const dir = pos.side === 'long' ? 1 : -1;
  const rNow = ((price - pos.entry) * dir) / pos.R;
  const rows = [...pos.targets].reverse();
  return (
    <div className="qp-ladder" data-comment-anchor="tp-ladder">
      {rows.map((t) => (
        <div key={t.label} className={'qp-rung' + (t.filled ? ' filled' : rNow >= t.r - 0.08 ? ' near' : '')}>
          <span className="qp-rung-check">{t.filled ? '✓' : ''}</span>
          <span className="qp-rung-label">{t.label} <em>{t.r}R</em></span>
          <span className="qp-rung-px mono">{QPFmt.px(t.price)}</span>
          <span className="qp-rung-amt mono">{t.contracts}계약{t.filled ? ' 체결' : ' 대기'}</span>
        </div>
      ))}
      <div className="qp-rung now">
        <span className="qp-rung-check">●</span>
        <span className="qp-rung-label">현재가 <em>{rNow.toFixed(2)}R</em></span>
        <span className="qp-rung-px mono">{QPFmt.px(price)}</span>
        <span className="qp-rung-amt"></span>
      </div>
      <div className={'qp-rung sl' + (pos.stop === pos.entry ? ' be' : '')}>
        <span className="qp-rung-check">✕</span>
        <span className="qp-rung-label">{pos.stop === pos.entry ? 'SL (본전)' : 'SL 손절'} <em>{pos.stop === pos.entry ? '0R' : '-1R'}</em></span>
        <span className="qp-rung-px mono">{QPFmt.px(pos.stop)}</span>
        <span className="qp-rung-amt mono">{pos.remaining}계약</span>
      </div>
      <div className="qp-rung entry">
        <span className="qp-rung-check">▸</span>
        <span className="qp-rung-label">진입가</span>
        <span className="qp-rung-px mono">{QPFmt.px(pos.entry)}</span>
        <span className="qp-rung-amt mono">{pos.contracts}계약</span>
      </div>
    </div>
  );
}

// ---------- 비용 분해 (gross → net) ----------
function CostBreakdown({ gross, fees, funding, slippage, net, title }) {
  const rows = [
    { k: 'Gross PnL', v: gross, sign: true },
    { k: '수수료 (taker)', v: -Math.abs(fees) },
    { k: 'Funding', v: -funding },
    { k: '슬리피지', v: -Math.abs(slippage) },
  ];
  const max = Math.max(Math.abs(gross), Math.abs(net), 1);
  return (
    <div className="qp-cost">
      {title ? <div className="qp-stat-label" style={{ marginBottom: 6 }}>{title}</div> : null}
      {rows.map((r) => (
        <div key={r.k} className="qp-cost-row">
          <span className="qp-cost-k">{r.k}</span>
          <span className="qp-cost-bar">
            <i className={r.v >= 0 ? 'pos' : 'neg'} style={{ width: Math.min(100, Math.abs(r.v) / max * 100) + '%' }}></i>
          </span>
          <span className={'mono qp-cost-v ' + (r.v >= 0 ? 'tone-up' : 'tone-dn')}>{QPFmt.signUsd(r.v)}</span>
        </div>
      ))}
      <div className="qp-cost-row net">
        <span className="qp-cost-k">Net PnL</span>
        <span className="qp-cost-bar"><i className={net >= 0 ? 'pos' : 'neg'} style={{ width: Math.min(100, Math.abs(net) / max * 100) + '%' }}></i></span>
        <span className={'mono qp-cost-v ' + (net >= 0 ? 'tone-up' : 'tone-dn')}>{QPFmt.signUsd(net)}</span>
      </div>
      <p className="qp-cost-note">승패 판정은 항상 <b>net</b> 기준 — 수수료 빼면 수익이 사라지는지 보이게</p>
    </div>
  );
}

// ---------- 미니 스파크라인 ----------
function Spark({ data, w = 220, h = 44, tone }) {
  if (!data || data.length < 2) return null;
  const min = Math.min(...data), max = Math.max(...data);
  const span = max - min || 1;
  const pts = data.map((v, i) => `${(i / (data.length - 1) * w).toFixed(1)},${(h - 3 - (v - min) / span * (h - 6)).toFixed(1)}`).join(' ');
  const up = data[data.length - 1] >= data[0];
  return (
    <svg width="100%" viewBox={`0 0 ${w} ${h}`} className="qp-spark" preserveAspectRatio="none">
      <polyline points={pts} className={'spark-line ' + (tone || (up ? 'up' : 'dn'))} fill="none"></polyline>
    </svg>
  );
}

Object.assign(window, { QPFmt, Panel, Stat, Pill, LoopStatus, RsiGauge, BreakerGauge, TpLadder, CostBreakdown, Spark });
