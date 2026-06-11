/* MINCODE — 전략 설정 (읽기 전용).
   WHY 읽기 전용: 실루프는 실행 중 파라미터 변경을 지원하지 않는다(CLI 플래그로 시작 시
   고정). 편집 가능한 척하는 UI는 "적용됐다"는 착각 → 실거래에서 사고. 디자인의 편집
   패널은 값 표시로 대체하고, 변경 방법(재시작)을 명시한다. */
function RoField({ label, sub, value }) {
  return (
    <div className="qp-field">
      <div className="qp-field-head">
        <label>{label}</label>
        {sub ? <span className="qp-field-sub">{sub}</span> : null}
      </div>
      <div className="mono" style={{ fontSize: 15, fontWeight: 700 }}>{value}</div>
    </div>
  );
}

function SettingsScreen({ s }) {
  const P = s.params;
  const riskUsd = s.capital * (P.riskPct / 100);
  return (
    <div className="qp-settings">
      <div className="qp-settings-actions" style={{ justifyContent: 'flex-start', marginTop: 0, marginBottom: 'var(--gap)' }}>
        <span className="qp-note">
          읽기 전용 — 파라미터는 루프 시작 시 고정됩니다. 변경하려면 루프를 내리고
          <span className="mono"> quantpilot paper --strategy … </span>옵션으로 재시작하세요.
        </span>
      </div>
      <div className="qp-settings-grid">
        <Panel title="리스크" titleEn="risk — 시스템의 1급 시민">
          <RoField label="Per-trade 리스크" sub="진입마다 최대 잃을 수 있는 돈"
            value={`${P.riskPct}% — 현재 자본 ${QPFmt.usd(s.capital)} 기준 최대 손실 ${QPFmt.usd(riskUsd)} / 거래`} />
          <RoField label="레버리지" value={`${P.leverage}× (isolated)`} />
          <RoField label="일일 서킷브레이커" sub="실현손익 한도 도달 시 신규 진입 차단(UTC 자정 리셋)"
            value={`−${P.breakerPct}%`} />
          <p className="qp-note">invariant: max_loss + fee + 손절 슬리피지 ≤ capital × {P.riskPct}% — 사이징에서 assert로 강제</p>
        </Panel>

        <Panel title="전략 · rsi-mr" titleEn="RSI mean-reversion">
          <RoField label="진입 밴드" sub="RSI < 하단 → LONG / RSI > 상단 → SHORT"
            value={`${P.entryLow} ↓LONG · ${P.entryHigh} ↑SHORT`} />
          <RoField label="청산 밴드 (중립 복귀)" sub="보유 중 RSI가 이 구간 진입 시 exit"
            value={`${P.exitLow} ~ ${P.exitHigh}`} />
          <RoField label="ATR 손절 배수 k" sub="SL = entry ∓ ATR(14) × k" value={`${P.atrK}×`} />
          <div className="qp-gauge-preview">
            <RsiGauge rsi={s.rsi[s.rsi.length - 1]} p={P} compact />
          </div>
        </Panel>

        <Panel title="분할익절 사다리" titleEn="TP ladder">
          {P.tpR.map((r, i) => (
            <RoField key={i} label={`TP${i + 1}`} sub={`entry ± R×${r}`}
              value={`${r}R · 비중 ${P.tpFrac[i]}`} />
          ))}
          <p className="qp-note">실엔진은 TP1 체결 후에도 손절선을 옮기지 않음(본전 이동 없음 — 보수적 단순화)</p>
        </Panel>

        <Panel title="비용 모델" titleEn="costs — net으로 승패 판정">
          <RoField label="Taker 수수료" value={`${P.takerBps} bps`} />
          <RoField label="슬리피지 가정" sub="체결가를 항상 불리한 쪽으로" value={`${P.slipBps} bps`} />
          <RoField label="Funding" sub="8h 경계마다 notional × rate (OKX 실데이터)"
            value={P.fundingRate != null ? `${(P.fundingRate * 100).toFixed(4)}% / 8h` : '—'} />
          <p className="qp-note">⭐ 봉 안에서 SL·TP 동시 도달 시 <b>손절 먼저</b> 체결 가정 — 백테스트 과낙관 방지</p>
        </Panel>
      </div>
    </div>
  );
}

Object.assign(window, { SettingsScreen });
