/* MINCODE — 루트 앱 (실데이터판). 프로토타입과의 차이(정직성 원칙):
   - Start/Stop 버튼 없음: 실루프는 원격 일시정지 미지원(터미널 Ctrl-C/재시작).
   - PANIC 해제 버튼 없음: 실킬스위치는 sticky — 재가동은 run-paper.sh 재실행.
   - Tweaks 패널 → 간단한 테마 메뉴(시안/다크라이트/포인트 컬러, localStorage). */
const VARIANT_MAP = { '터미널': 'terminal', '모던': 'modern', '클래식': 'classic' };
const ACCENTS = ['#E5484D', '#F5A524', '#1F8A5B', '#2A6FDB'];

function Clock() {
  const [now, setNow] = React.useState(new Date());
  React.useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(t);
  }, []);
  const p = (n) => String(n).padStart(2, '0');
  return (
    <span className="qp-clock mono">
      <span className="qp-clock-date">{now.getFullYear()}-{p(now.getMonth() + 1)}-{p(now.getDate())}</span>
      <b>{p(now.getHours())}:{p(now.getMinutes())}:{p(now.getSeconds())}</b>
    </span>
  );
}

function KillSwitch({ s, engine }) {
  const [armed, setArmed] = React.useState(false);
  const [busy, setBusy] = React.useState(false);
  React.useEffect(() => {
    if (!armed) return;
    const t = setTimeout(() => setArmed(false), 3000);
    return () => clearTimeout(t);
  }, [armed]);
  if (s.panic) {
    return <span className="qp-pill tone-dn">PANIC — 재가동은 run-paper.sh</span>;
  }
  return (
    <button className={'qp-btn kill' + (armed ? ' armed' : '')} disabled={busy}
      onClick={() => {
        if (!armed) { setArmed(true); return; }
        setBusy(true);
        engine.panic(() => { setBusy(false); setArmed(false); });
      }}>
      {busy ? '청산 중…' : armed ? '한 번 더 — 즉시 청산' : '⏻ 비상정지'}
    </button>
  );
}

function ThemeMenu({ t, set }) {
  const [open, setOpen] = React.useState(false);
  return (
    <div style={{ position: 'relative' }}>
      <button className="qp-btn ghost" onClick={() => setOpen(!open)} aria-label="테마">◐</button>
      {open && (
        <div style={{ position: 'absolute', right: 0, top: 42, zIndex: 60, width: 218,
                      background: 'var(--panel)', border: '1px solid var(--line2)',
                      borderRadius: 10, padding: 12, boxShadow: '0 8px 28px rgba(0,0,0,.35)' }}>
          <div className="qp-stat-label">시안</div>
          <div className="qp-tabs-inline" style={{ marginBottom: 8 }}>
            {['터미널', '모던', '클래식'].map((v) => (
              <button key={v} className={t.variant === v ? 'on' : ''}
                onClick={() => set('variant', v)}>{v}</button>
            ))}
          </div>
          <div className="qp-stat-label">모드</div>
          <div className="qp-tabs-inline" style={{ marginBottom: 8 }}>
            {['다크', '라이트'].map((v) => (
              <button key={v} className={t.theme === v ? 'on' : ''}
                onClick={() => set('theme', v)}>{v}</button>
            ))}
          </div>
          <div className="qp-stat-label">포인트 컬러</div>
          <div style={{ display: 'flex', gap: 8, marginTop: 4 }}>
            {ACCENTS.map((c) => (
              <button key={c} onClick={() => set('accent', c)} aria-label={c}
                style={{ width: 22, height: 22, borderRadius: '50%', background: c,
                         border: t.accent === c ? '2px solid var(--txt)' : '2px solid transparent' }} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function TopBar({ s, engine, tab, setTab, t, setTweak }) {
  const price = s.price;
  const chg = s.prevClose ? (price / s.prevClose - 1) * 100 : 0;
  const tabs = [['dash', '대시보드'], ['logs', '매매 로그'], ['settings', '전략 설정']];
  const word = s.panic ? 'PANIC' : s.breakerTripped ? 'HALTED'
    : !s.connected ? 'NO SERVER' : s.running ? 'Trading' : 'LOOP DOWN';
  const wordCls = s.panic ? 'panic' : s.running ? 'live' : 'off';
  return (
    <header className="qp-topbar">
      <div className="qp-brand">
        <span className="qp-brand-mark" aria-hidden="true">M</span>
        <span className="qp-brand-text">
          <strong>MINCODE</strong>
          <em>QuantPilot · Paper Trading</em>
        </span>
      </div>
      <nav className="qp-tabs">
        {tabs.map(([k, label]) => (
          <button key={k} className={tab === k ? 'on' : ''} onClick={() => setTab(k)}>{label}</button>
        ))}
      </nav>
      <div className="qp-ticker mono">
        <span className="qp-ticker-sym">BTC-USDT-SWAP</span>
        <b className={chg >= 0 ? 'tone-up' : 'tone-dn'}>{QPFmt.px(price, 1)}</b>
        <span className={'qp-ticker-chg ' + (chg >= 0 ? 'tone-up' : 'tone-dn')}>{chg >= 0 ? '▲' : '▼'} {QPFmt.pct(chg)}</span>
        {s.params.fundingRate != null && (
          <span className="qp-ticker-fund">funding {(s.params.fundingRate * 100).toFixed(4)}% · {s.fundingCountdown}h 후</span>
        )}
      </div>
      <LoopStatus s={s} />
      <div className="qp-topbar-actions">
        <span className={'qp-trading-word mono ' + wordCls}>
          {word}
          {s.running && !s.panic ? <i className="qp-dots"><b>.</b><b>.</b><b>.</b></i> : null}
        </span>
        <KillSwitch s={s} engine={engine} />
        <ThemeMenu t={t} set={setTweak} />
      </div>
    </header>
  );
}

function BottomBar({ s }) {
  return (
    <footer className="qp-bottombar mono">
      <span><i className="qp-dot ok"></i>익절: TP사다리 {s.params.tpR.join('/')}R</span>
      <span><i className="qp-dot ok"></i>손절: ATR×{s.params.atrK} (고정 — 본전 이동 없음)</span>
      <span><i className={'qp-dot ' + (s.connected ? 'ok' : 'bad')}></i>{s.connected ? 'DB 폴링 2s' : '서버 연결 끊김'}</span>
      <span className="qp-bottombar-spacer"></span>
      <span className="dim">OKX 데이터 · 페이퍼($0 리스크)</span>
      <Clock />
    </footer>
  );
}

function App() {
  const engineRef = React.useRef(null);
  if (!engineRef.current) engineRef.current = QPEngine.create();
  const engine = engineRef.current;

  const [, force] = React.useReducer((x) => x + 1, 0);
  React.useEffect(() => engine.subscribe(() => force()), []);

  const [tab, setTabRaw] = React.useState(() => localStorage.getItem('mincode-tab') || 'dash');
  const setTab = (k) => { setTabRaw(k); localStorage.setItem('mincode-tab', k); };

  const [t, setT] = React.useState(() => {
    try { return Object.assign({ theme: '다크', variant: '모던', accent: '#E5484D' },
      JSON.parse(localStorage.getItem('mincode-theme') || '{}')); }
    catch (e) { return { theme: '다크', variant: '모던', accent: '#E5484D' }; }
  });
  const setTweak = (k, v) => setT((prev) => {
    const next = Object.assign({}, prev, { [k]: v });
    localStorage.setItem('mincode-theme', JSON.stringify(next));
    return next;
  });
  React.useEffect(() => {
    const root = document.documentElement;
    root.dataset.theme = t.theme === '라이트' ? 'light' : 'dark';
    root.dataset.variant = VARIANT_MAP[t.variant] || 'modern';
    root.style.setProperty('--accent', t.accent);
  }, [t.theme, t.variant, t.accent]);

  const s = engine.getState();

  if (s.loading) {
    return <div className="qp-app"><div className="qp-empty" style={{ marginTop: 120 }}>서버 연결 중…</div></div>;
  }
  if (!s.run) {
    return (
      <div className="qp-app">
        <div className="qp-empty" style={{ marginTop: 120 }}>
          {s.connected ? (s.hint || '페이퍼 런 없음') : '서버 연결 끊김 — quantpilot dashboard 를 실행하세요'}
        </div>
      </div>
    );
  }
  return (
    <div className={'qp-app' + (s.panic ? ' is-panic' : '')}>
      <TopBar s={s} engine={engine} tab={tab} setTab={setTab} t={t} setTweak={setTweak} />
      <main className="qp-main">
        {tab === 'dash' && <DashboardScreen s={s} engine={engine} />}
        {tab === 'logs' && <LogsScreen s={s} />}
        {tab === 'settings' && <SettingsScreen s={s} />}
      </main>
      <BottomBar s={s} />
    </div>
  );
}

ReactDOM.createRoot(document.getElementById('root')).render(<App />);
