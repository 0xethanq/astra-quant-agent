/**
 * Pure logic helpers for AI Console (`AgentConsolePage.vue` & `AgentProposalCard.vue`).
 * Zero Vue / DOM dependencies so Node tests can import and verify directly.
 */

export interface AgentProposalKvDiff {
  field: string;
  label?: string;
  before: any;
  after: any;
}

export interface AgentProposalItem {
  id: string;
  domain: string;
  action?: string;
  title: string;
  reason?: string;
  diff_type?: 'kv' | 'text' | string;
  diff?: AgentProposalKvDiff[] | string;
  warnings?: string[];
  high_risk?: boolean;
  required_phrase?: string;
  required_phrase_reason?: string;
  payload?: Record<string, any>;
}

export interface AgentProposalApplyResultItem {
  item_id: string;
  title?: string;
  ok: boolean;
  detail?: string;
  error?: string;
}

export interface AgentProposal {
  id: string;
  session_id: string;
  title?: string;
  summary?: string;
  status: 'pending' | 'applied' | 'partially_applied' | 'failed' | 'rejected' | string;
  snapshot_hash?: string | null;
  items: AgentProposalItem[];
  applied_result?: {
    results?: AgentProposalApplyResultItem[];
    applied_count?: number;
    failed_count?: number;
    rejected_reason?: string;
  } | null;
  created_at?: string;
  applied_at?: string | null;
  applied_by?: string | null;
}

export interface AgentToolTrace {
  id: string;
  name: string;
  arguments?: Record<string, any>;
  status?: 'running' | 'ok' | 'error' | string;
  summary?: string;
}

export interface AgentMessageItem {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  reasoning?: string;
  tool_calls?: AgentToolTrace[];
  proposal_ids?: string[];
  created_at?: string;
}

export const STARTER_PROMPTS = [
  { key: 'admin.agent.starterDiagnose', id: 'diagnose' },
  { key: 'admin.agent.starterRiskTighten', id: 'risk_tighten' },
  { key: 'admin.agent.starterPromptReview', id: 'prompt_review' },
  { key: 'admin.agent.starterCouncilReview', id: 'council_review' },
  { key: 'admin.agent.starterDryRun', id: 'dry_run' },
] as const;

export function itemIdOf(item: AgentProposalItem): string {
  return String(item.id || '');
}

/**
 * Collect unique required confirmation phrases across selected proposal items.
 */
export function collectRequiredPhrases(
  items: AgentProposalItem[],
  selectedIds: string[],
): string[] {
  const chosen = new Set(selectedIds);
  const seen = new Set<string>();
  const out: string[] = [];
  for (const item of items || []) {
    if (!chosen.has(itemIdOf(item))) continue;
    const phrase = String(item.required_phrase || '').trim();
    if (phrase && !seen.has(phrase)) {
      seen.add(phrase);
      out.push(phrase);
    }
  }
  return out;
}

/**
 * Return any required confirmation phrases not yet matched verbatim (case-insensitive / trimmed).
 */
export function missingConfirmations(
  items: AgentProposalItem[],
  selectedIds: string[],
  inputs: Record<string, string>,
): string[] {
  const required = collectRequiredPhrases(items, selectedIds);
  const missing: string[] = [];
  for (const phrase of required) {
    const typed = String(inputs?.[phrase] || '').trim().toUpperCase();
    if (typed !== phrase.toUpperCase()) {
      missing.push(phrase);
    }
  }
  return missing;
}

/**
 * Parse a complete or partial SSE text buffer into `{ events, rest }`.
 */
export function parseSseBuffer(rawBuffer: string): {
  events: Array<Record<string, any>>;
  rest: string;
} {
  const normalized = String(rawBuffer || '').replace(/\r\n/g, '\n');
  const events: Array<Record<string, any>> = [];
  let cursor = 0;

  while (true) {
    const idx = normalized.indexOf('\n\n', cursor);
    if (idx === -1) break;
    const frame = normalized.slice(cursor, idx);
    cursor = idx + 2;
    const dataLines: string[] = [];
    for (const line of frame.split('\n')) {
      if (line.startsWith('data:')) {
        dataLines.push(line.slice(5).trimStart());
      }
    }
    const payload = dataLines.join('\n').trim();
    if (!payload) continue;
    try {
      events.push(JSON.parse(payload));
    } catch {
      /* ignore malformed JSON frame */
    }
  }

  return { events, rest: normalized.slice(cursor) };
}

export function formatDiffValue(value: any): string {
  if (value === null || value === undefined) return '—';
  if (typeof value === 'boolean') return value ? 'true' : 'false';
  if (typeof value === 'string') return value;
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}
