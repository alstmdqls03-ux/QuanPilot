/* MINCODE — 메인 대시보드 화면 */
function DashboardScreen({ s, engine }) {
  const p = s.position;
  const price = s.price;
  const uPnl = engine.unrealized();
  const rsiNow = s.rsi[s.rsi.length - 1];
  const totalNet = s.trades.reduce((a, t) => a + t.pnlNet, 0);
  const wins = s.trades.filter((t) => t.pnlNet > 0).length;
  const equity = s.capital + uPnl;
  const totalRet = (equity / s.startCapital - 1) * 100;

  // 포지션 파생값
  let lossAtStop = null, liqGap = null, rNow = null;
  if (p) {
    const dir = p.side === 'long' ? 1 : -1;
    lossAtStop = p.realizedGross + p.remaining * s.params.ctVal * (p.stop - p.entry) * dir - p.fees - p.funding;
    liqGap = Math.abs(price - p.liq) / price * 100;
    rNow = ((price - p.entry) * dir) / p.R;
  }

  // 비용 분해 대상: 열린 포지션 우선, 없으면 마지막 거래
  const costSrc = p
    ? { title: '현재 포지션 비용 분해 (실현분)', gross: p.realizedGross, fees: p.fees, funding: p.funding, slippage: p.slippage, net: p.realizedGross - p.fees - p.funding }
    : s.trades[0]
      ? { title: '마지막 거래 비용 분해', gross: s.trades[0].pnlGross, fees: s.trades[0].fees, funding: s.trades[0].funding, slippage: s.trades[0].slippage, net: s.trades[0].pnlNet }
      : null;

  return (
    <div className="qp-dash">
      {/* KPI 줄 */}
      <div className="qp-kpis" data-screen-label="대시보드 KPI">
        <Stat label="Equity (자본+미실현)" value={QPFmt.usd(equity)} sub={<span className={totalRet >= 0 ? 'tone-up' : 'tone-dn'}>{QPFmt.pct(totalRet)} 누적</span>} />
        <Stat label="미실현 손익" value={<span className={uPnl >= 0 ? 'tone-up' : 'tone-dn'}>{QPFmt.signUsd(uPnl)}</span>} sub={p ? `${p.side === 'long' ? 'LONG' : 'SHORT'} ${p.remaining}계약 보유 중` : '포지션 없음'} />
        <Stat label="누적 거래 (net)" value={<span className={totalNet >= 0 ? 'tone-up' : 'tone-dn'}>{QPFmt.signUsd(totalNet)}</span>} sub={`${s.trades.length}건 · 승률 ${s.trades.length ? Math.round(wins / s.trades.length * 100) : 0}%`} />
        <div className="qp-stat risk-kpi" data-comment-anchor="risk-sizing">
          <div className="qp-stat-label">이번 거래 최대 손실 (per-trade {s.params.riskPct}%)</div>
          <div className="qp-stat-value mono tone-accent">{p ? QPFmt.usd(p.maxLoss) : s.nextTradeMaxLoss ? QPFmt.usd(s.nextTradeMaxLoss) : '—'}</div>
          <div className="qp-stat-sub">수수료+슬리피지 포함 · invariant 강제</div>
        </div>
      </div>

      <div className="qp-dash-grid">
        {/* 좌측: 차트 + 하단 */}
        <div className="qp-dash-left">
          <Panel title="BTC-USDT-SWAP · 1H" titleEn="OKX Perpetual" pad={false}
            right={<span className="mono qp-chart-price"><b className={price >= s.prevClose ? 'tone-up' : 'tone-dn'}>{QPFmt.px(price, 1)}</b> <span className={price >= s.prevClose ? 'tone-up' : 'tone-dn'}>{QPFmt.pct((price / s.prevClose - 1) * 100)}</span></span>}>
            <CandleChart candles={s.candles} rsi={s.rsi} position={p} params={s.params} />
          </Panel>
          <div className="qp-dash-bottom">
            <Panel title="Equity Curve">
              <EquityCurve equity={s.equity} />
            </Panel>
            <Panel title="비용 분해" titleEn="gross → net">
              {costSrc ? <CostBreakdown {...costSrc} /> : <div className="qp-empty">아직 거래 없음</div>}
            </Panel>
          </div>
        </div>

        {/* 우측: 리스크/포지션 컨텍스트 */}
        <div className="qp-dash-right">
          <Panel title="서킷브레이커" titleEn="circuit breaker">
            <BreakerGauge s={s} />
          </Panel>

          <Panel title="포지션" titleEn="position context"
            right={p ? <Pill tone={p.side === 'long' ? 'up' : 'dn'}>{p.side === 'long' ? 'LONG' : 'SHORT'} {p.remaining}/{p.contracts}계약</Pill> : <Pill tone="muted">FLAT</Pill>}>
            {p ? (
              <div className="qp-pos">
                <div className="qp-pos-grid">
                  <Stat label="진입가" value={QPFmt.px(p.entry)} />
                  <Stat label="현재 R" value={<span className={rNow >= 0 ? 'tone-up' : 'tone-dn'}>{rNow.toFixed(2)}R</span>} />
                  <Stat label="손절가" value={<span className={p.stop === p.entry ? 'tone-accent' : ''}>{QPFmt.px(p.stop)}</span>} sub={p.stop === p.entry ? '본전 이동됨' : '초기 -1R'} />
                  <Stat label="손절 시 잔여 손실" value={<span className={lossAtStop >= 0 ? 'tone-up' : 'tone-dn'}>{QPFmt.signUsd(lossAtStop)}</span>} sub="실현분·비용 반영 net" />
                  <Stat label="강제청산가" value={QPFmt.px(p.liq)} sub={<span className={liqGap < 8 ? 'tone-dn' : ''}>여유 {liqGap.toFixed(1)}%</span>} />
                  <Stat label="비용 누적" value={QPFmt.usd(p.fees + p.funding + p.slippage)} sub="fee+funding+slip" />
                </div>
              </div>
            ) : (
              <div className="qp-empty">포지션 없음 — RSI 진입 밴드 도달 시 자동 진입<br /><span className="mono">예상 사이징: {s.nextTradeMaxLoss ? `최대손실 ${QPFmt.usd(s.nextTradeMaxLoss)}` : '—'}</span></div>
            )}
          </Panel>

          <Panel title="분할익절 사다리" titleEn="TP ladder 1R/2R/3R">
            <TpLadder pos={p} price={price} />
          </Panel>

          <Panel title="전략 신호" titleEn="rsi-mr">
            <RsiGauge rsi={rsiNow} p={s.params} />
          </Panel>

          <Panel title="라이브 로그" titleEn="loop events" pad={false}
            right={<Pill tone={s.running ? 'ok' : 'muted'} pulse={s.running}>{s.running ? 'streaming' : 'paused'}</Pill>}>
            <div className="qp-minilog">
              {s.logs.slice(0, 9).map((l, i) => (
                <div key={i} className={'qp-logline lv-' + l.level}>
                  <span className="mono qp-log-ts">{l.tsText || QPFmt.timeS(l.ts)}</span>
                  <span className="qp-log-tx">{l.text}</span>
                </div>
              ))}
            </div>
          </Panel>
        </div>
      </div>
    </div>
  );
}

Object.assign(window, { DashboardScreen });
