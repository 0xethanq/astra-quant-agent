/** Audit log page copy */
export const enAdminAudit = {
  tabsLabel: 'Accounts & audit sections',
  tabAudit: 'Audit log',
  intro: "Append-only operations audit trail; logins, configuration changes and trading actions are all recorded.",
  badge: "Governance · 1/3",
  searchPlaceholder: "Search action / status / account / detail...",
  refresh: "Refresh",
  entries: "entries",
  rowHint: "Click any row to drill into the raw parameter JSON",
  colTimestamp: "Timestamp",
  colAction: "Action",
  colStatus: "Result",
  colDetail: "Operator & audit detail",
  empty: "No audit records match the current filter",
  detailTitle: "Audit detail",
  close: "Close",

  // ── added by the rebuild (batch 11) ──
  bandTotal: 'Audit records',
  bandSuccess: 'Succeeded',
  bandFailed: 'Abnormal',
  bandLatest: 'Latest entry',
  filterAll: 'All',
  filterSuccess: 'Succeeded',
  filterFailed: 'Abnormal',
  recordsTitle: 'Audit stream',
  actorLabel: 'Actor',
  rawJson: 'Raw record JSON',
  noMatch: 'No matching records',

  status: {
    success: 'Success',
    completed: 'Completed',
    accepted: 'Accepted',
    failed: 'Failed',
    denied: 'Denied',
    error: 'Error',
    confirmed_closed: 'Confirmed closed',
  },
  // ── batch 44: accessible name for the status filter tablist ──
  filtersLabel: 'Filter audit records by status',
};
