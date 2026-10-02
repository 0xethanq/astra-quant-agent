export const enEvolution = {
  title: 'Strategy Evolution',
  desc: 'Audits the full closed-trade ledger every 6 hours',
  hud: {
    at: 'Last review',
    sample: 'Sample',
    winRate: 'Win rate',
    pf: 'Profit factor',
    status: 'Status',
    sampleN: '{n} closed trades',
    statuses: { CHANGED: 'Evolved', NO_CHANGE: 'Held', RUNNING: 'Reviewing', FAILED: 'Failed' },
    empty: 'No review record yet',
  },
  rationale: { title: 'Verdict', desc: 'Full reasoning behind "change or hold"' },
  insights: { title: 'Trade Attribution', desc: 'Pain-point slices of representative closes', empty: 'No slices yet' },
  actions: { title: 'Action list', empty: 'No new actions this round' },
  memory: {
    title: 'Core Trading Rules',
    desc: 'Rules the AI maintains; old ones decay by half-life',
    empty: 'Rule library is empty until the first review',
    halfLife: 'Half-life {n}d',
    remaining: '{n}% left',
    weight: 'Weight',
    bornAt: 'Distilled {t}',
    rules: '{n} active',
    dev: 'Raw Strategy Markdown',
    devDesc: 'Raw markdown of the rule library',
    dimension: 'Dimension',
    lesson: 'Rule',
    evidence: 'Evidence',
  },
  guard: {
    title: 'Anti-pollution guard',
    on: 'Active',
    off: 'Not active',
    desc: 'Small samples, emotional wording and overfitted rules are rejected from the library',
    snapshot: 'Math snapshot observability',
    snapshotCounts: 'dynamics {observed}/{total} · price-only {priceOnly} · none {none}',
    baselineProtected: '{n} baseline rules re-added',
  },
  // batch 38: list separator for display (fullwidth vs ASCII)
  itemSep: '; ',
  // ── batch 41: localize strings previously hardcoded in EvolutionView ──
  autoIterateBadge: '6h Iteration Cycle',
  snapshotAuditTitle: 'Snapshot Data Audit',
  actText: '[{type}] {text}',
  // ── 2026-10 (direction 1: evidence-chain observability) ──
  evidenceChainTitle: 'Evidence Chain Health',
  // ⚠️ This measures *tier-factor observability*, NOT "snapshot is non-empty":
  // in production, 100% of rows had a non-empty snapshot while 0% had tier factors
  // (legacy snapshots carry price-only observations). Mislabeling it would show
  // "entry coverage 100%" and hide the very gap it exists to expose.
  evidenceEntryCoverage: 'Entry tier-factor observability',
  evidenceExitCoverage: 'Mechanism-confirmed exit reasons',
  evidenceGapsTitle: 'Evidence gaps (disclosed honestly)',
  evidenceNoGaps: 'Evidence chain intact: no entry-context or exit-reason gaps',
};
