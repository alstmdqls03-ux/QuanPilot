/* MINCODE — 실데이터 어댑터. 프로토타입의 모의 QPEngine을 대체한다.
   /api/state(실 SQLite)를 2초 폴링해 UI 컴포넌트가 기대하는 상태 모양으로 매핑.
   숫자는 전부 서버(실코드)에서 계산 — 여기는 모양 변환만. */
(function () {
  'use strict';
  var POLL_MS = 2000;

  function mapPosition(api) {
    var p = api.position;
    if (!p) return null;
    var feeEst = p.original_contracts * p.entry * api.params.ctVal *
      (api.params.takerBps / 10000) * 2;
    var realizedGross = (api.position.pending_fills || [])
      .reduce(function (a, f) { return a + f.pnl_gross; }, 0);
    return {
      side: p.side, entry: p.entry,
      contracts: p.original_contracts,        // UI: 진입 총 계약
      remaining: p.contracts,                 // UI: 남은 계약
      stop: p.stop, R: p.r_unit, openedTs: p.opened_ts,
      targets: (p.ladder || []).map(function (t) {
        return { label: t.label, r: t.r, price: t.price, frac: t.frac,
                 contracts: t.contracts, filled: t.filled, fillTs: t.fill_ts };
      }),
      riskUsd: p.r_unit * p.original_contracts * api.params.ctVal,
      maxLoss: p.r_unit * p.original_contracts * api.params.ctVal + feeEst,
      fees: p.fees_accum, funding: 0 /* 보유 중 미정산 — 청산 시 일괄 */, slippage: 0,
      realizedGross: realizedGross, liq: p.liq, entryRsi: null,
      unrealized: p.unrealized, lossAtStop: p.loss_at_stop,
    };
  }

  function synthFills(api) {
    var fills = [];
    var p = api.position;
    if (p) {
      (p.pending_fills || []).forEach(function (f) {
        fills.push({ ts: f.ts, kind: f.reason, side: p.side, price: f.price,
                     contracts: f.contracts, fee: f.fee, note: '부분익절 (보유 중)' });
      });
      fills.push({ ts: p.opened_ts, kind: 'entry', side: p.side, price: p.entry,
                   contracts: p.original_contracts, fee: p.open_fee, note: '' });
    }
    (api.trades || []).forEach(function (t) {
      fills.push({ ts: t.closed_ts, kind: t.reason, side: t.side, price: t.exit,
                   contracts: t.contracts, fee: t.fees, note: '청산(집계)' });
      fills.push({ ts: t.opened_ts, kind: 'entry', side: t.side, price: t.entry,
                   contracts: t.contracts, fee: 0, note: '' });
    });
    fills.sort(function (a, b) { return b.ts - a.ts; });
    return fills;
  }

  function mapState(api) {
    var curve = api.equity_curve || [];
    var startCap = curve.length ? curve[0][1] : api.realized_equity;
    var pos = mapPosition(api);
    var lastTs = api.last_processed_bar_ts || api.last_bar_ts || Date.now();
    // 다음 funding(8h 경계)까지 남은 시간
    var fundingH = 8 - Math.floor((lastTs / 3600000) % 8) % 8;
    return {
      run: true, version: Date.now(),
      params: api.params,
      candles: api.candles || [], rsi: api.rsi || [],
      price: api.price, prevClose: api.prev_close,
      capital: api.realized_equity, startCapital: startCap,
      dayStartEquity: api.day_start_equity,
      dailyRealized: api.daily_realized_pnl,
      position: pos,
      trades: (api.trades || []).map(function (t) {
        return { side: t.side, entry: t.entry, exit: t.exit, contracts: t.contracts,
                 pnlGross: t.pnl_gross, fees: t.fees, funding: t.funding,
                 slippage: 0 /* 체결가에 이미 반영(불리한 쪽) — 분리 기록 안 함 */,
                 pnlNet: t.pnl_net, openedTs: t.opened_ts, closedTs: t.closed_ts,
                 reason: t.reason };
      }),
      fills: synthFills(api),
      logs: (api.logs || []).map(function (l) {
        return { ts: 0, tsText: l.ts_text, level: l.level, text: l.text };
      }),
      equity: curve.map(function (p2) { return { ts: p2[0], eq: p2[1] }; }),
      running: !!api.loop_alive && !api.panic_halted,
      panic: !!api.panic_halted,
      breakerTripped: !!api.halted && !api.panic_halted,
      lastBarTs: lastTs,
      lastBarAgoSec: api.freshness_sec,
      // 캔들 ts는 봉 '시작' 시각 → 1h봉은 정상이어도 신선도가 60~120분까지 벌어진다.
      staleAfterSec: 7500,
      fundingCountdown: fundingH,
      nextTradeMaxLoss: api.next_trade_max_loss,
      metrics: api.metrics, gapCheckOk: true,
      loopAlive: !!api.loop_alive, connected: true,
    };
  }

  function create() {
    var S = { run: false, loading: true, connected: false, version: 0,
              params: { breakerPct: 5, tpR: [1, 2, 3], atrK: 1.5 },
              candles: [], rsi: [], trades: [], fills: [], logs: [], equity: [],
              price: 0, prevClose: 1, capital: 0, startCapital: 1,
              dailyRealized: 0, position: null, running: false, panic: false,
              breakerTripped: false, lastBarTs: Date.now(), lastBarAgoSec: null,
              hint: null };
    var listeners = new Set();
    function emit() { listeners.forEach(function (f) { f(S); }); }

    function poll() {
      fetch('/api/state').then(function (r) { return r.json(); }).then(function (api) {
        if (api.run === false) {
          S = Object.assign({}, S, { run: false, loading: false, connected: true,
                                     hint: api.hint || '페이퍼 런 없음' });
        } else {
          S = mapState(api);
          S.loading = false;
        }
        emit();
      }).catch(function () {
        S = Object.assign({}, S, { connected: false, loading: false });
        emit();
      });
    }
    poll();
    setInterval(poll, POLL_MS);

    return {
      getState: function () { return S; },
      subscribe: function (fn) { listeners.add(fn); return function () { listeners.delete(fn); }; },
      unrealized: function () { return S.position ? S.position.unrealized : 0; },
      panic: function (cb) {
        fetch('/api/panic', { method: 'POST' })
          .then(function (r) { return r.json(); })
          .then(function (res) { poll(); if (cb) cb(res); })
          .catch(function (e) { if (cb) cb({ ok: false, error: String(e) }); });
      },
      refresh: poll,
    };
  }

  window.QPEngine = { create: create };
})();
