/* MINCODE — 매매 로그 / 체결 내역 화면 */
function reasonPill(r) {
  const map = {
    stop: ['dn', 'STOP'], tp1: ['up', 'TP1'], tp2: ['up', 'TP2'], tp3: ['up', 'TP3'],
    exit_signal: ['accent', 'EXIT'], panic: ['dn', 'PANIC'], entry: ['muted', 'ENTRY'],
  };
  const [tone, label] = map[r] || ['muted', r];
  return <Pill tone={tone}>{label}</Pill>;
}

function LogsScreen({ s }) {
  const [tab, setTab] = React.useState('trades');
  const [lvFilter, setLvFilter] = React.useState('all');
  const totalNet = s.trades.reduce((a, t) => a + t.pnlNet, 0);
  const totalGross = s.trades.reduce((a, t) => a + t.pnlGross, 0);
  const totalCost = s.trades.reduce((a, t) => a + t.fees + Math.max(0, t.funding) + t.slippage, 0);
  const wins = s.trades.filter((t) => t.pnlNet > 0);
  const losses = s.trades.filter((t) => t.pnlNet <= 0);
  const pf = losses.length ? Math.abs(wins.reduce((a, t) => a + t.pnlNet, 0) / (losses.reduce((a, t) => a + t.pnlNet, 0) || 1)) : null;
  const logs = lvFilter === 'all' ? s.logs : s.logs.filter((l) => l.level === lvFilter);

  return (
    <div className="qp-logsScreen" data-screen-label="매매 로그">
      <div className="qp-kpis">
        <Stat label="누적 Net PnL" value={<span className={totalNet >= 0 ? 'tone-up' : 'tone-dn'}>{QPFmt.signUsd(totalNet)}</span>} sub={`gross ${QPFmt.signUsd(totalGross)}`} />
        <Stat label="총 비용 (fee+funding+slip)" value={QPFmt.usd(totalCost)} sub={totalGross !== 0 ? `gross의 ${Math.abs(totalCost / totalGross * 100).toFixed(1)}%` : ''} />
        <Stat label="승률" value={`${s.trades.length ? Math.round(wins.length / s.trades.length * 100) : 0}%`} sub={`${wins.length}승 ${losses.length}패`} />
        <Stat label="Profit Factor" value={pf ? pf.toFixed(2) : '—'} sub="총이익 / 총손실 (net)" />
      </div>

      <div className="qp-logs-grid">
        <Panel pad={false}
          title={
            <span className="qp-tabs-inline">
              <button className={tab === 'trades' ? 'on' : ''} onClick={() => setTab('trades')}>거래 내역</button>
              <button className={tab === 'fills' ? 'on' : ''} onClick={() => setTab('fills')}>체결</button>
            </span>
          }>
          {tab === 'trades' ? (
            <div className="qp-tablewrap">
              <table className="qp-table">
                <thead>
                  <tr><th>종료</th><th>방향</th><th className="num">진입</th><th className="num">청산</th><th className="num">계약</th><th className="num">Gross</th><th className="num">Fee</th><th className="num">Funding</th><th className="num">Slip</th><th className="num">Net</th><th>사유</th></tr>
                </thead>
                <tbody>
                  {s.trades.length === 0 ? (
                    <tr><td colSpan="11" className="qp-empty">완료된 거래가 없습니다</td></tr>
                  ) : s.trades.map((t, i) => (
                    <tr key={i}>
                      <td className="mono dim">{QPFmt.date(t.closedTs)}</td>
                      <td><Pill tone={t.side === 'long' ? 'up' : 'dn'}>{t.side === 'long' ? 'L' : 'S'}</Pill></td>
                      <td className="num mono">{QPFmt.px(t.entry)}</td>
                      <td className="num mono">{QPFmt.px(t.exit)}</td>
                      <td className="num mono">{t.contracts}</td>
                      <td className={'num mono ' + (t.pnlGross >= 0 ? 'tone-up' : 'tone-dn')}>{QPFmt.signUsd(t.pnlGross)}</td>
                      <td className="num mono dim">-{QPFmt.usd(t.fees).slice(1)}</td>
                      <td className="num mono dim">{t.funding >= 0 ? '-' : '+'}{QPFmt.usd(Math.abs(t.funding)).slice(1)}</td>
                      <td className="num mono dim">-{QPFmt.usd(t.slippage).slice(1)}</td>
                      <td className={'num mono strong ' + (t.pnlNet >= 0 ? 'tone-up' : 'tone-dn')}>{QPFmt.signUsd(t.pnlNet)}</td>
                      <td>{reasonPill(t.reason)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="qp-tablewrap">
              <table className="qp-table">
                <thead><tr><th>시각</th><th>구분</th><th>방향</th><th className="num">가격</th><th className="num">계약</th><th className="num">Fee</th><th>메모</th></tr></thead>
                <tbody>
                  {s.fills.length === 0 ? (
                    <tr><td colSpan="7" className="qp-empty">체결 내역이 없습니다</td></tr>
                  ) : s.fills.map((f, i) => (
                    <tr key={i}>
                      <td className="mono dim">{QPFmt.date(f.ts)}</td>
                      <td>{reasonPill(f.kind)}</td>
                      <td><Pill tone={f.side === 'long' ? 'up' : 'dn'}>{f.side === 'long' ? 'L' : 'S'}</Pill></td>
                      <td className="num mono">{QPFmt.px(f.price)}</td>
                      <td className="num mono">{f.contracts}</td>
                      <td className="num mono dim">-{QPFmt.usd(f.fee).slice(1)}</td>
                      <td className="dim">{f.note}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Panel>

        <Panel title="시스템 로그" titleEn="loop stream" pad={false}
          right={
            <span className="qp-tabs-inline small">
              {['all', 'signal', 'fill', 'warn', 'error'].map((lv) => (
                <button key={lv} className={lvFilter === lv ? 'on' : ''} onClick={() => setLvFilter(lv)}>{lv}</button>
              ))}
            </span>
          }>
          <div className="qp-minilog tall">
            {logs.slice(0, 60).map((l, i) => (
              <div key={i} className={'qp-logline lv-' + l.level}>
                <span className="mono qp-log-ts">{l.tsText || QPFmt.timeS(l.ts)}</span>
                <span className="qp-log-tx">{l.text}</span>
              </div>
            ))}
          </div>
        </Panel>
      </div>
    </div>
  );
}

Object.assign(window, { LogsScreen });
