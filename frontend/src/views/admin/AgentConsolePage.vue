<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue';
import { useRouter } from 'vue-router';
import {
  Activity,
  Bot,
  ChevronDown,
  ChevronRight,
  Loader2,
  PanelLeft,
  PanelRight,
  PauseCircle,
  Plus,
  Send,
  Sparkles,
  Square,
  Wrench,
  X,
} from 'lucide-vue-next';
import PageHeader from '../../components/admin/PageHeader.vue';
import { get, post, put, del, streamPost } from '../../api/http';
import { useAuthStore } from '../../stores/auth';
import { useConfirm } from '../../composables/useConfirm';
import { useI18n } from '../../composables/useI18n';
import { useToast } from '../../composables/useToast';
import AgentProposalCard from './agent/AgentProposalCard.vue';
import AgentSessionDrawer from './agent/AgentSessionDrawer.vue';
import AgentStrategySidebar from './agent/AgentStrategySidebar.vue';
import { renderSafeMarkdown } from '../../utils/markdown';
import {
  type AgentInsightsPayload,
  type AgentInspectorPayload,
  type AgentMessageItem,
  type AgentProposal,
  type StagedPromptContext,
  INSIGHT_CARD_CLASS,
  STARTER_PROMPTS,
  composeStagedMessage,
} from './agent/agentLogic';

const router = useRouter();
const { t } = useI18n();
const auth = useAuthStore();
const toast = useToast();
const { ask } = useConfirm();

const loading = ref(true);
const loadError = ref('');
const summaryLoading = ref(false);
const showSessionsPanel = ref(false);
const showSummaryPanel = ref(true);
const togglingKey = ref('');

const agentConfig = ref<any>(null);
const stateSummary = ref<any>(null);
const insightsPayload = ref<AgentInsightsPayload | null>(null);
const inspectorPayload = ref<AgentInspectorPayload | null>(null);
const sessions = ref<any[]>([]);
const activeSessionId = ref('');
const messages = ref<AgentMessageItem[]>([]);
const proposals = ref<AgentProposal[]>([]);

const draft = ref('');
const stagedContext = ref<StagedPromptContext | null>(null);
const composerInputRef = ref<HTMLTextAreaElement | null>(null);
const composerHighlighted = ref(false);
let highlightTimer: ReturnType<typeof setTimeout> | null = null;
const streaming = ref(false);
const streamAbort = ref<AbortController | null>(null);
const applyingProposalId = ref('');
const savingModel = ref(false);
const expandedReasoning = ref<Record<string, boolean>>({});
const expandedToolGroups = ref<Record<string, boolean>>({});
const expandedTools = ref<Record<string, boolean>>({});
const chatScrollRef = ref<HTMLElement | null>(null);

const canSend = computed(() => !streaming.value && (Boolean(draft.value.trim()) || Boolean(stagedContext.value)));

const selectedModelId = computed(() => String(agentConfig.value?.model_id || 'auto'));
const availableModels = computed<any[]>(() => agentConfig.value?.available_models || []);
const activeBrainLabel = computed(() => {
  const llm = stateSummary.value?.llm;
  return llm?.active_model_name || llm?.active_model_id || '—';
});
const envBadgeClass = computed(() =>
  stateSummary.value?.environment === 'live' ? 'badge-warn' : 'badge-accent',
);
const isTradingPaused = computed(() => Boolean(stateSummary.value?.trading_paused));
const healthLabel = computed(() => {
  const h = stateSummary.value?.data_health?.overall;
  if (h === 'LIVE') return t('admin.agent.healthFresh');
  if (h === 'STALE') return t('admin.agent.healthStale');
  return t('admin.agent.healthUnknown');
});
const healthBadgeClass = computed(() => {
  const h = stateSummary.value?.data_health?.overall;
  if (h === 'LIVE') return 'badge-up';
  if (h === 'STALE') return 'badge-warn';
  return '';
});

const proposalMap = computed(() => {
  const map: Record<string, AgentProposal> = {};
  for (const p of proposals.value) {
    map[p.id] = p;
  }
  return map;
});

function scrollToBottom() {
  nextTick(() => {
    const el = chatScrollRef.value;
    if (el) el.scrollTop = el.scrollHeight;
  });
}

async function loadStateSummary() {
  summaryLoading.value = true;
  try {
    const [sum, ins, insp] = await Promise.all([
      get('/api/v1/admin/agent/state-summary'),
      get('/api/v1/admin/agent/insights').catch(() => null),
      get('/api/v1/admin/agent/inspector').catch(() => null),
    ]);
    stateSummary.value = sum;
    if (ins) insightsPayload.value = ins;
    if (insp) inspectorPayload.value = insp;
  } catch {
    /* keep existing summary on refresh failure */
  } finally {
    summaryLoading.value = false;
  }
}

async function openSession(sessionId: string) {
  if (!sessionId) return;
  activeSessionId.value = sessionId;
  showSessionsPanel.value = false;
  const detail = await get(`/api/v1/admin/agent/sessions/${encodeURIComponent(sessionId)}`);
  messages.value = Array.isArray(detail?.messages) ? detail.messages : [];
  proposals.value = Array.isArray(detail?.proposals) ? detail.proposals : [];
  scrollToBottom();
}

async function createSession() {
  const res = await post('/api/v1/admin/agent/sessions', {
    model_id: selectedModelId.value,
  });
  const sess = res?.session;
  if (sess?.id) {
    sessions.value = [sess, ...sessions.value.filter((x) => x.id !== sess.id)];
    activeSessionId.value = sess.id;
    messages.value = [];
    proposals.value = [];
    showSessionsPanel.value = false;
  }
}

async function deleteSession(sessionId: string) {
  const ok = await ask({
    title: t('admin.agent.deleteSessionConfirmTitle'),
    desc: t('admin.agent.deleteSessionConfirmDesc'),
    danger: true,
    okText: t('common.remove'),
  });
  if (!ok) return;
  try {
    await del(`/api/v1/admin/agent/sessions/${encodeURIComponent(sessionId)}`);
    sessions.value = sessions.value.filter((s) => s.id !== sessionId);
    toast.ok(t('admin.agent.sessionDeleted'));
    if (activeSessionId.value === sessionId) {
      if (sessions.value.length) {
        await openSession(sessions.value[0].id);
      } else {
        await createSession();
      }
    }
  } catch (e: any) {
    toast.err(t('admin.agent.loadFailed', undefined, { msg: e.message }));
  }
}

async function updateModel(nextModelId: string) {
  if (!auth.isSuperadmin || savingModel.value) return;
  savingModel.value = true;
  try {
    agentConfig.value = await put('/api/v1/admin/agent/config', { model_id: nextModelId });
    toast.ok(t('admin.agent.modelSaved'));
  } catch (e: any) {
    toast.err(t('admin.agent.chatFailed', undefined, { msg: e.message }));
  } finally {
    savingModel.value = false;
  }
}

async function handleQuickToggle(payload: {
  target: string;
  enabled: boolean;
  itemId?: string;
  label: string;
}) {
  if (!auth.isSuperadmin) return;
  const key = payload.itemId ? `${payload.target}:${payload.itemId}` : payload.target;
  togglingKey.value = key;
  try {
    await post('/api/v1/admin/control-plane/quick-toggle', {
      target: payload.target,
      enabled: payload.enabled,
      item_id: payload.itemId,
      auto_snapshot: true,
    });
    await loadStateSummary();
    if (payload.target === 'trading_paused') {
      window.dispatchEvent(
        new CustomEvent('astra:control-plane-changed', {
          detail: { trading_paused: payload.enabled },
        }),
      );
    }
    toast.ok(t('admin.agent.toggleSaved', undefined, { label: payload.label }));
  } catch (e: any) {
    toast.err(t('admin.agent.toggleFailed', undefined, { msg: e.message || 'error' }));
  } finally {
    togglingKey.value = '';
  }
}

async function bootstrap() {
  loading.value = true;
  loadError.value = '';
  try {
    const [cfg, sum, listRes, ins, insp] = await Promise.all([
      get('/api/v1/admin/agent/config'),
      get('/api/v1/admin/agent/state-summary'),
      get('/api/v1/admin/agent/sessions'),
      get('/api/v1/admin/agent/insights').catch(() => null),
      get('/api/v1/admin/agent/inspector').catch(() => null),
    ]);
    agentConfig.value = cfg;
    stateSummary.value = sum;
    insightsPayload.value = ins;
    inspectorPayload.value = insp;
    sessions.value = Array.isArray(listRes?.sessions) ? listRes.sessions : [];
    if (sessions.value.length) {
      await openSession(sessions.value[0].id);
    } else {
      await createSession();
    }
  } catch (e: any) {
    loadError.value = e.message || 'error';
    toast.err(t('admin.agent.loadFailed', undefined, { msg: loadError.value }));
  } finally {
    loading.value = false;
  }
}

function stopGeneration() {
  if (streamAbort.value) {
    streamAbort.value.abort();
    streamAbort.value = null;
  }
}

function stagePrompt(payload: StagedPromptContext) {
  stagedContext.value = {
    label: String(payload.label || '').trim(),
    prompt: String(payload.prompt || '').trim(),
  };
  composerHighlighted.value = true;
  if (highlightTimer) clearTimeout(highlightTimer);
  highlightTimer = setTimeout(() => {
    composerHighlighted.value = false;
  }, 900);
  nextTick(() => {
    composerInputRef.value?.focus();
    composerInputRef.value?.scrollIntoView({ block: 'nearest' });
  });
}

function clearStagedContext() {
  stagedContext.value = null;
  nextTick(() => composerInputRef.value?.focus());
}

async function sendMessage(overrideText?: string) {
  const text = overrideText !== undefined
    ? String(overrideText).trim()
    : composeStagedMessage(stagedContext.value, draft.value, {
        refPrefix: t('admin.agent.stagedRefPrefix'),
        notePrefix: t('admin.agent.stagedNotePrefix'),
      });
  if (!text || streaming.value) return;

  if (!activeSessionId.value) {
    await createSession();
  }
  const sid = activeSessionId.value;
  if (!sid) return;

  if (overrideText === undefined) {
    draft.value = '';
    stagedContext.value = null;
  }

  const userMsg: AgentMessageItem = {
    id: `local_u_${Date.now()}`,
    role: 'user',
    content: text,
  };
  const assistantMsg: AgentMessageItem = {
    id: `local_a_${Date.now()}`,
    role: 'assistant',
    content: '',
    reasoning: '',
    tool_calls: [],
    proposal_ids: [],
  };
  messages.value = [...messages.value, userMsg, assistantMsg];
  const assistantIdx = messages.value.length - 1;
  scrollToBottom();

  const controller = new AbortController();
  streamAbort.value = controller;
  streaming.value = true;

  try {
    await streamPost(
      `/api/v1/admin/agent/sessions/${encodeURIComponent(sid)}/chat`,
      { message: text, model_id: selectedModelId.value },
      (ev) => {
        const cur = messages.value[assistantIdx];
        if (!cur) return;

        if (ev.type === 'session_updated' && ev.session?.id) {
          sessions.value = sessions.value.map((s) => (s.id === ev.session.id ? ev.session : s));
        } else if (ev.type === 'reasoning_delta' && ev.text) {
          cur.reasoning = `${cur.reasoning || ''}${ev.text}`;
          scrollToBottom();
        } else if (ev.type === 'text_delta' && ev.text) {
          cur.content = `${cur.content || ''}${ev.text}`;
          scrollToBottom();
        } else if (ev.type === 'tool_start') {
          const traces = [...(cur.tool_calls || [])];
          traces.push({
            id: String(ev.id || `tc_${traces.length}`),
            name: String(ev.name || 'tool'),
            arguments: ev.arguments || {},
            status: 'running',
          });
          cur.tool_calls = traces;
          scrollToBottom();
        } else if (ev.type === 'tool_result') {
          const traces = [...(cur.tool_calls || [])];
          const hit = traces.find((x) => x.id === ev.id) || traces[traces.length - 1];
          if (hit) {
            hit.status = ev.status === 'error' ? 'error' : 'ok';
            hit.summary = String(ev.summary || '');
            if (typeof ev.duration_ms === 'number') hit.duration_ms = ev.duration_ms;
            if (typeof ev.result_preview === 'string') hit.result_preview = ev.result_preview;
          }
          cur.tool_calls = traces;
          scrollToBottom();
        } else if (ev.type === 'proposal' && ev.proposal?.id) {
          const prop = ev.proposal as AgentProposal;
          proposals.value = [...proposals.value.filter((p) => p.id !== prop.id), prop];
          cur.proposal_ids = [...(cur.proposal_ids || []), prop.id];
          scrollToBottom();
        } else if (ev.type === 'done') {
          if (ev.message?.id) {
            cur.id = ev.message.id;
            if (Array.isArray(ev.message.proposal_ids)) {
              cur.proposal_ids = ev.message.proposal_ids;
            }
          }
          if (ev.proposal?.id) {
            const prop = ev.proposal as AgentProposal;
            proposals.value = [...proposals.value.filter((p) => p.id !== prop.id), prop];
          }
          if (ev.state_summary) {
            stateSummary.value = ev.state_summary;
          }
        } else if (ev.type === 'error') {
          const msg = String(ev.error || ev.message || 'error');
          if (!cur.content) {
            cur.content = msg;
          }
          toast.err(t('admin.agent.chatFailed', undefined, { msg }));
        }
      },
      controller.signal,
    );
  } catch (e: any) {
    if (e?.name === 'AbortError') {
      const cur = messages.value[assistantIdx];
      if (cur && !cur.content) {
        cur.content = t('admin.agent.stoppedNote');
      }
    } else {
      toast.err(t('admin.agent.chatFailed', undefined, { msg: e.message || 'error' }));
    }
  } finally {
    streaming.value = false;
    streamAbort.value = null;
    scrollToBottom();
  }
}

async function handleProposalApply(payload: {
  proposalId: string;
  selectedItemIds: string[];
  confirmations: Record<string, string>;
}) {
  applyingProposalId.value = payload.proposalId;
  try {
    const res = await post(`/api/v1/admin/agent/proposals/${encodeURIComponent(payload.proposalId)}/apply`, {
      selected_item_ids: payload.selectedItemIds,
      confirmations: payload.confirmations,
    });
    if (res?.proposal?.id) {
      proposals.value = proposals.value.map((p) => (p.id === res.proposal.id ? res.proposal : p));
    }
    if (res?.state_summary) {
      stateSummary.value = res.state_summary;
    }
    loadStateSummary();
    if (res?.ok) {
      toast.ok(t('admin.agent.proposalAppliedToast'));
    } else {
      const errItem = (res?.results || []).find((r: any) => !r.ok);
      toast.err(t('admin.agent.proposalApplyFailed', undefined, { msg: errItem?.error || 'partial error' }));
    }
  } catch (e: any) {
    toast.err(t('admin.agent.proposalApplyFailed', undefined, { msg: e.message || 'error' }));
  } finally {
    applyingProposalId.value = '';
  }
}

async function handleProposalRollback(payload: { proposalId: string }) {
  const ok = await ask({
    title: t('admin.agent.proposalRollbackConfirmTitle'),
    desc: t('admin.agent.proposalRollbackConfirmDesc'),
    danger: true,
    okText: t('admin.agent.proposalRollback'),
  });
  if (!ok) return;
  applyingProposalId.value = payload.proposalId;
  try {
    const res = await post(`/api/v1/admin/agent/proposals/${encodeURIComponent(payload.proposalId)}/rollback`, {});
    if (res?.proposal?.id) {
      proposals.value = proposals.value.map((p) => (p.id === res.proposal.id ? res.proposal : p));
    }
    if (res?.state_summary) {
      stateSummary.value = res.state_summary;
    }
    loadStateSummary();
    toast.ok(t('admin.agent.proposalRolledBackToast'));
  } catch (e: any) {
    toast.err(t('admin.agent.proposalRollbackFailed', undefined, { msg: e.message || 'error' }));
  } finally {
    applyingProposalId.value = '';
  }
}

async function handleProposalReject(payload: { proposalId: string }) {
  applyingProposalId.value = payload.proposalId;
  try {
    const res = await post(`/api/v1/admin/agent/proposals/${encodeURIComponent(payload.proposalId)}/reject`, {
      reason: '',
    });
    if (res?.proposal?.id) {
      proposals.value = proposals.value.map((p) => (p.id === res.proposal.id ? res.proposal : p));
    }
    toast.ok(t('admin.agent.proposalRejectedToast'));
  } catch (e: any) {
    toast.err(t('admin.agent.proposalRejectFailed', undefined, { msg: e.message || 'error' }));
  } finally {
    applyingProposalId.value = '';
  }
}

function toggleReasoning(msgId: string) {
  expandedReasoning.value[msgId] = !expandedReasoning.value[msgId];
}

function toggleToolGroup(msgId: string) {
  expandedToolGroups.value[msgId] = !expandedToolGroups.value[msgId];
}

function toggleToolDetail(toolId: string) {
  expandedTools.value[toolId] = !expandedTools.value[toolId];
}

function toolGroupLabel(calls: any[]): string {
  const total = calls.length;
  const done = calls.filter((c) => c.status === 'ok' || c.status === 'error').length;
  if (done < total) {
    return t('admin.agent.toolsRunningSummaryLabel', undefined, { done, total });
  }
  return t('admin.agent.toolsSummaryLabel', undefined, { count: total });
}

function onComposerKeydown(ev: KeyboardEvent) {
  if (ev.key === 'Enter' && !ev.shiftKey && !ev.isComposing) {
    ev.preventDefault();
    sendMessage();
  }
}

onMounted(bootstrap);
onBeforeUnmount(() => {
  if (highlightTimer) clearTimeout(highlightTimer);
});
</script>

<template>
  <div class="ag-page">
    <header class="ag-topbar" :aria-label="t('admin.agent.runtimeStripAria')">
      <div class="ag-topbar-left">
        <PageHeader compact :title="t('admin.agent.title')" />
        <div class="ag-strip-metrics">
          <span class="badge mono" :class="envBadgeClass">
            {{ String(stateSummary?.environment || 'demo').toUpperCase() }}
          </span>
          <button
            type="button"
            class="badge ag-badge-btn"
            :class="isTradingPaused ? 'badge-warn' : 'badge-up'"
            @click="router.push('/admin/strategy?tab=schedule')"
          >
            <PauseCircle v-if="isTradingPaused" :size="12" />
            <Activity v-else :size="12" />
            <span>{{ isTradingPaused ? t('admin.agent.enginePausedBadge') : t('admin.agent.engineLiveBadge') }}</span>
          </button>
          <span class="badge mono num">
            {{ t('admin.agent.stripPositions') }}: {{ stateSummary?.account?.positions_count ?? 0 }}
          </span>
          <span class="badge" :class="healthBadgeClass">
            {{ healthLabel }}
          </span>
          <span
            v-if="insightsPayload"
            class="badge mono num"
            :class="insightsPayload.critical_count > 0 ? 'badge-down' : insightsPayload.warning_count > 0 ? 'badge-warn' : 'badge-up'"
          >
            {{ t('admin.agent.insightsHealthScore', undefined, { score: insightsPayload.health_score }) }}
          </span>
        </div>
      </div>

      <div class="ag-topbar-right">
        <select
          :value="selectedModelId"
          :disabled="!auth.isSuperadmin || savingModel"
          :aria-label="t('admin.agent.modelAria')"
          class="field ag-model-select"
          @change="updateModel(($event.target as HTMLSelectElement).value)"
        >
          <option value="auto">
            {{ t('admin.agent.modelAutoShort', undefined, { model: activeBrainLabel }) }}
          </option>
          <option v-for="m in availableModels" :key="m.id" :value="m.id">
            {{ m.name }} ({{ m.provider_name || m.api_format }})
          </option>
        </select>

        <button type="button" class="btn btn-primary btn-sm" @click="createSession">
          <Plus :size="14" />
          <span class="hidden sm:inline">{{ t('admin.agent.newSession') }}</span>
        </button>

        <button
          type="button"
          class="btn btn-ghost btn-sm"
          :aria-expanded="showSessionsPanel"
          :aria-controls="showSessionsPanel ? 'ag-sessions-panel' : undefined"
          @click="showSessionsPanel = !showSessionsPanel"
        >
          <PanelLeft :size="14" />
          <span class="hidden md:inline">{{ t('admin.agent.sidebarSessionsToggle') }}</span>
        </button>

        <button
          type="button"
          class="btn btn-ghost btn-sm"
          :aria-expanded="showSummaryPanel"
          :aria-controls="showSummaryPanel ? 'ag-summary-panel' : undefined"
          @click="showSummaryPanel = !showSummaryPanel"
        >
          <PanelRight :size="14" />
          <span class="hidden md:inline">{{ t('admin.agent.sidebarSummaryToggle') }}</span>
        </button>
      </div>
    </header>

    <div class="ag-workspace">
      <div v-if="showSessionsPanel" id="ag-sessions-panel">
        <AgentSessionDrawer
          :sessions="sessions"
          :activeSessionId="activeSessionId"
          @close="showSessionsPanel = false"
          @select="openSession"
          @create="createSession"
          @delete="deleteSession"
        />
      </div>

      <section class="ag-main-stage">
        <p v-if="!auth.isSuperadmin" role="status" class="ag-readonly-banner">
          {{ t('admin.agent.readonlyNotice') }}
        </p>

        <div ref="chatScrollRef" class="ag-stream scroll-area">
          <div class="ag-stream-inner">
            <div v-if="!messages.length && !loading" class="ag-empty">
              <span class="ag-empty-icon"><Bot :size="24" /></span>
              <h2 class="ag-empty-title">{{ t('admin.agent.emptyWelcomeTitle') }}</h2>
              <p class="ag-empty-desc">{{ t('admin.agent.emptyWelcomeDesc') }}</p>

              <div v-if="(insightsPayload?.insights || []).length" class="ag-insights-panel" :aria-label="t('admin.agent.insightsTitle')">
                <div class="ag-insights-head">
                  <span class="ag-insights-title">{{ t('admin.agent.insightsTitle') }}</span>
                  <span class="ag-insights-hint">{{ t('admin.agent.insightsClickToAsk') }}</span>
                </div>
                <div class="ag-insights-grid">
                  <button
                    v-for="ins in insightsPayload?.insights"
                    :key="ins.id"
                    type="button"
                    class="insight-card"
                    :class="INSIGHT_CARD_CLASS[ins.severity] || 'insight-card--info'"
                    @click="stagePrompt({ label: ins.title, prompt: ins.suggested_prompt })"
                  >
                    <div class="ag-insight-top">
                      <span class="ag-insight-name">{{ ins.title }}</span>
                      <span v-if="ins.metric" class="badge mono">{{ ins.metric }}</span>
                    </div>
                    <span class="ag-insight-desc">{{ ins.detail }}</span>
                  </button>
                </div>
              </div>

              <div class="ag-starters" role="group" :aria-label="t('admin.agent.startersLabel')">
                <button
                  v-for="sp in STARTER_PROMPTS"
                  :key="sp.id"
                  type="button"
                  class="btn btn-ghost btn-sm ag-starter-btn"
                  @click="sendMessage(t(sp.key))"
                >
                  <Sparkles :size="13" />
                  <span>{{ t(sp.key) }}</span>
                </button>
              </div>
            </div>

            <article
              v-for="msg in messages"
              :key="msg.id"
              class="ag-msg"
              :class="msg.role === 'user' ? 'is-user' : 'is-assistant'"
            >
              <header v-if="msg.role === 'assistant'" class="ag-msg-head">
                <span class="ag-msg-role">{{ t('admin.agent.roleAssistant') }}</span>
                <span v-if="msg.created_at" class="ag-msg-time mono num">{{ msg.created_at }}</span>
              </header>

              <div v-if="msg.reasoning" class="ag-reasoning-wrap">
                <button
                  type="button"
                  class="btn btn-quiet btn-sm"
                  :aria-expanded="!!expandedReasoning[msg.id]"
                  :aria-controls="expandedReasoning[msg.id] ? `ag-reason-${msg.id}` : undefined"
                  @click="toggleReasoning(msg.id)"
                >
                  <ChevronDown v-if="expandedReasoning[msg.id]" :size="13" />
                  <ChevronRight v-else :size="13" />
                  <span>{{ t('admin.agent.reasoningTitle') }}</span>
                </button>
                <pre
                  v-if="expandedReasoning[msg.id]"
                  :id="`ag-reason-${msg.id}`"
                  tabindex="0"
                  class="ag-reasoning-box mono"
                >{{ msg.reasoning }}</pre>
              </div>

              <div v-if="(msg.tool_calls || []).length" class="ag-tools-group" :aria-label="t('admin.agent.toolsTitle')">
                <button
                  type="button"
                  class="ag-tools-summary"
                  :aria-expanded="!!expandedToolGroups[msg.id]"
                  :aria-controls="expandedToolGroups[msg.id] ? `ag-tools-${msg.id}` : undefined"
                  @click="toggleToolGroup(msg.id)"
                >
                  <Wrench :size="13" class="shrink-0" />
                  <span>{{ toolGroupLabel(msg.tool_calls || []) }}</span>
                  <ChevronDown v-if="expandedToolGroups[msg.id]" :size="13" class="shrink-0" />
                  <ChevronRight v-else :size="13" class="shrink-0" />
                </button>

                <div v-if="expandedToolGroups[msg.id]" :id="`ag-tools-${msg.id}`" class="ag-traces">
                  <div v-for="tc in msg.tool_calls" :key="tc.id" class="ag-trace-wrap">
                    <div class="ag-trace-row">
                      <span class="mono ag-trace-name">{{ tc.name }}</span>
                      <span
                        class="badge mono"
                        :class="tc.status === 'error' ? 'badge-down' : tc.status === 'ok' ? 'badge-up' : 'badge-accent'"
                      >
                        {{ tc.status === 'error' ? t('admin.agent.toolError') : tc.status === 'ok' ? t('admin.agent.toolDone') : t('admin.agent.toolRunning') }}
                      </span>
                      <span v-if="typeof tc.duration_ms === 'number'" class="ag-trace-ms mono num">
                        {{ t('admin.agent.toolDurationMs', undefined, { ms: tc.duration_ms }) }}
                      </span>
                      <span v-if="tc.summary" class="ag-trace-summary truncate">{{ tc.summary }}</span>
                      <button
                        v-if="tc.result_preview || (tc.arguments && Object.keys(tc.arguments).length)"
                        type="button"
                        class="btn btn-quiet btn-sm ag-trace-toggle"
                        :aria-expanded="!!expandedTools[tc.id]"
                        :aria-controls="expandedTools[tc.id] ? `ag-tool-det-${tc.id}` : undefined"
                        @click="toggleToolDetail(tc.id)"
                      >
                        <span>{{ expandedTools[tc.id] ? t('admin.agent.toolCollapseDetails') : t('admin.agent.toolExpandDetails') }}</span>
                      </button>
                    </div>
                    <div v-if="expandedTools[tc.id]" :id="`ag-tool-det-${tc.id}`" class="ag-trace-detail mono">
                      <div v-if="tc.arguments && Object.keys(tc.arguments).length">
                        <strong>{{ t('admin.agent.toolArgsLabel') }}:</strong> {{ JSON.stringify(tc.arguments) }}
                      </div>
                      <div v-if="tc.result_preview">
                        <strong>{{ t('admin.agent.toolResultPreviewLabel') }}:</strong> {{ tc.result_preview }}
                      </div>
                    </div>
                  </div>
                </div>
              </div>

              <div
                v-if="msg.content && msg.role === 'assistant'"
                class="ag-md"
                v-html="renderSafeMarkdown(msg.content)"
              />
              <div v-else-if="msg.content" class="ag-msg-text">{{ msg.content }}</div>

              <div v-for="pid in (msg.proposal_ids || [])" :key="pid" class="ag-msg-proposal">
                <AgentProposalCard
                  v-if="proposalMap[pid]"
                  :proposal="proposalMap[pid]"
                  :busy="applyingProposalId === pid"
                  @apply="handleProposalApply"
                  @reject="handleProposalReject"
                  @rollback="handleProposalRollback"
                />
              </div>
            </article>
          </div>
        </div>

        <div class="ag-composer-deck">
          <footer
            class="ag-composer"
            :class="{ 'is-staged': Boolean(stagedContext), 'is-highlighted': composerHighlighted }"
          >
            <div v-if="stagedContext" class="ag-staged-bar">
              <div class="ag-staged-top">
                <span class="badge badge-accent ag-staged-badge">
                  <Sparkles :size="12" />
                  <span>{{ t('admin.agent.stagedContextLabel') }}: {{ stagedContext.label }}</span>
                </span>
                <button
                  type="button"
                  class="btn btn-quiet btn-icon btn-sm"
                  :aria-label="t('admin.agent.stagedContextClearAria')"
                  :title="t('admin.agent.stagedContextClearAria')"
                  @click="clearStagedContext"
                >
                  <X :size="14" />
                </button>
              </div>
              <p class="ag-staged-preview">{{ stagedContext.prompt }}</p>
              <p class="ag-staged-hint">{{ t('admin.agent.stagedContextHint') }}</p>
            </div>

            <textarea
              ref="composerInputRef"
              v-model="draft"
              rows="2"
              autocomplete="off"
              spellcheck="false"
              class="field ag-input"
              :aria-label="t('admin.agent.inputLabel')"
              :placeholder="stagedContext ? t('admin.agent.stagedPlaceholder') : t('admin.agent.inputPlaceholder')"
              :disabled="streaming"
              @keydown="onComposerKeydown"
            />
            <div class="ag-composer-actions">
              <span class="ag-composer-hint">{{ t('admin.agent.composerShortcutHint') }}</span>
              <button
                v-if="streaming"
                type="button"
                class="btn btn-ghost is-danger"
                @click="stopGeneration"
              >
                <Square :size="14" />
                <span>{{ t('admin.agent.stop') }}</span>
              </button>
              <button
                v-else
                type="button"
                class="btn btn-primary"
                :disabled="!canSend"
                @click="sendMessage()"
              >
                <Loader2 v-if="loading" :size="14" class="animate-spin shrink-0" />
                <Send v-else :size="14" />
                <span>{{ t('admin.agent.send') }}</span>
              </button>
            </div>
          </footer>
        </div>
      </section>

      <AgentStrategySidebar
        v-if="showSummaryPanel"
        id="ag-summary-panel"
        :summary="stateSummary"
        :inspector="inspectorPayload"
        :loading="summaryLoading"
        :tradingPaused="isTradingPaused"
        :togglingKey="togglingKey"
        :isSuperadmin="auth.isSuperadmin"
        @refresh="loadStateSummary"
        @stage="stagePrompt"
        @toggle="handleQuickToggle"
      />
    </div>
  </div>
</template>

<style scoped>
.ag-page {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  background-color: var(--ds-color-bg-page);
}
.ag-topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--ds-space-3);
  padding: var(--ds-space-2) var(--ds-space-5);
  min-height: 52px;
  border-bottom: 1px solid var(--ds-color-border-subtle);
  background-color: var(--ds-color-bg-surface-1);
  flex-wrap: wrap;
}
.ag-topbar-left {
  display: flex;
  align-items: center;
  gap: var(--ds-space-3);
  flex-wrap: wrap;
  min-width: 0;
}
.ag-strip-metrics {
  display: flex;
  align-items: center;
  gap: var(--ds-space-2);
  flex-wrap: wrap;
}
.ag-badge-btn {
  cursor: pointer;
}
.ag-topbar-right {
  display: flex;
  align-items: center;
  gap: var(--ds-space-2);
  flex-wrap: wrap;
}
.ag-model-select {
  min-width: 210px;
  max-width: 280px;
  height: var(--h-md);
  font-size: var(--text-xs);
}
.ag-workspace {
  flex: 1;
  min-height: 0;
  display: flex;
  overflow: hidden;
}
.ag-main-stage {
  flex: 1;
  min-width: 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
}
.ag-readonly-banner {
  margin: var(--ds-space-3) var(--ds-space-5) 0;
  padding: var(--ds-space-2) var(--ds-space-3);
  border: 1px solid var(--warn-line);
  border-radius: var(--r-ctl);
  background-color: var(--warn-bg);
  color: var(--warn);
  font-size: var(--text-base);
}
.ag-stream {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: var(--ds-space-5) var(--ds-space-5) var(--ds-space-4);
}
.ag-stream-inner {
  max-width: 840px;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  gap: var(--ds-space-5);
}
.ag-empty {
  margin: var(--ds-space-5) auto;
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  gap: var(--ds-space-3);
}
.ag-empty-icon {
  width: 48px;
  height: 48px;
  display: grid;
  place-items: center;
  border-radius: var(--r-card);
  background-color: var(--ds-color-brand-subtle);
  color: var(--ds-color-brand);
}
.ag-empty-title {
  margin: 0;
  font-size: var(--text-xl);
  font-weight: 600;
  color: var(--ds-color-text-primary);
}
.ag-empty-desc {
  margin: 0;
  max-width: 64ch;
  font-size: var(--text-base);
  line-height: var(--leading-body);
  color: var(--ds-color-text-description);
}
.ag-insights-panel {
  width: 100%;
  display: flex;
  flex-direction: column;
  gap: var(--ds-space-2);
  text-align: left;
  margin-top: var(--ds-space-2);
}
.ag-insights-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--ds-space-2);
}
.ag-insights-title {
  font-size: var(--text-base);
  font-weight: 600;
  color: var(--ds-color-text-primary);
}
.ag-insights-hint {
  font-size: var(--text-xs);
  color: var(--ds-color-text-placeholder);
}
.ag-insights-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(230px, 1fr));
  gap: var(--ds-space-2);
}
.ag-insight-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--ds-space-2);
}
.ag-insight-name {
  font-size: var(--text-base);
  font-weight: 600;
  color: var(--ds-color-text-primary);
}
.ag-insight-desc {
  font-size: var(--text-xs);
  color: var(--ds-color-text-description);
  line-height: 1.5;
}
.ag-starters {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: var(--ds-space-2);
  margin-top: var(--ds-space-2);
}
.ag-starter-btn {
  max-width: 100%;
  text-align: left;
}
.ag-msg {
  display: flex;
  flex-direction: column;
  gap: var(--ds-space-2);
}
.ag-msg.is-user {
  align-self: flex-end;
  max-width: 82%;
  padding: var(--ds-space-3) var(--ds-space-4);
  border-radius: var(--r-card);
  border: 1px solid var(--ds-color-border-default);
  background-color: var(--ds-color-bg-surface-2);
}
.ag-msg.is-assistant {
  padding: var(--ds-space-2) 0;
}
.ag-msg-head {
  display: flex;
  align-items: center;
  gap: var(--ds-space-2);
}
.ag-msg-role {
  font-size: var(--text-xs);
  font-weight: 600;
  color: var(--ds-color-text-description);
}
.ag-msg-time {
  font-size: var(--text-xs);
  color: var(--ds-color-text-placeholder);
}
.ag-reasoning-wrap {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: var(--ds-space-1);
}
.ag-reasoning-box {
  width: 100%;
  margin: 0;
  padding: var(--ds-space-3);
  border-radius: var(--r-ctl);
  border: 1px solid var(--ds-color-border-subtle);
  background-color: var(--ds-color-bg-surface-1);
  color: var(--ds-color-text-description);
  font-size: var(--text-xs);
  white-space: pre-wrap;
  max-height: 220px;
  overflow: auto;
}
.ag-tools-group {
  display: flex;
  flex-direction: column;
  gap: var(--ds-space-2);
}
.ag-tools-summary {
  align-self: flex-start;
  display: inline-flex;
  align-items: center;
  gap: var(--ds-space-2);
  padding: var(--sp-2) var(--ds-space-3);
  min-height: 30px;
  border-radius: var(--r-ctl);
  border: 1px solid var(--ds-color-border-subtle);
  background-color: var(--ds-color-bg-surface-1);
  font-size: var(--text-xs);
  color: var(--ds-color-text-description);
  transition: border-color var(--dur-fast) var(--ease-out), color var(--dur-fast) var(--ease-out);
}
.ag-tools-summary:hover {
  border-color: var(--ds-color-border-strong);
  color: var(--ds-color-text-primary);
}
.ag-traces {
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
  padding-left: var(--ds-space-3);
  border-left: 2px solid var(--ds-color-border-subtle);
}
.ag-trace-wrap {
  display: flex;
  flex-direction: column;
  gap: var(--ds-space-1);
}
.ag-trace-row {
  display: flex;
  align-items: center;
  gap: var(--ds-space-2);
  padding: var(--sp-2) var(--ds-space-3);
  border-radius: var(--r-ctl);
  background-color: var(--ds-color-bg-surface-1);
  font-size: var(--text-xs);
}
.ag-trace-name {
  font-weight: 600;
  color: var(--ds-color-text-primary);
}
.ag-trace-ms {
  color: var(--ds-color-text-placeholder);
  flex-shrink: 0;
}
.ag-trace-summary {
  color: var(--ds-color-text-description);
  flex: 1;
  min-width: 0;
}
.ag-trace-toggle {
  flex-shrink: 0;
}
.ag-trace-detail {
  padding: var(--ds-space-2) var(--ds-space-3);
  border-radius: var(--r-ctl);
  background-color: var(--ds-color-bg-surface-1);
  font-size: var(--text-xs);
  color: var(--ds-color-text-description);
  display: flex;
  flex-direction: column;
  gap: var(--ds-space-1);
  word-break: break-all;
}
.ag-msg-text {
  font-size: var(--text-md);
  line-height: 1.65;
  color: var(--ds-color-text-primary);
  white-space: pre-wrap;
}
.ag-md {
  font-size: var(--text-md);
  line-height: 1.7;
  color: var(--ds-color-text-primary);
}
.ag-md :deep(p) {
  margin: 0 0 var(--ds-space-3);
}
.ag-md :deep(p:last-child) {
  margin-bottom: 0;
}
.ag-md :deep(ul),
.ag-md :deep(ol) {
  margin: 0 0 var(--ds-space-3);
  padding-left: var(--ds-space-5);
}
.ag-md :deep(code) {
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  background-color: var(--ds-color-bg-surface-inset);
  padding: var(--sp-1) var(--sp-2);
  border-radius: var(--r-ctl);
}
.ag-md :deep(pre) {
  padding: var(--ds-space-3);
  border-radius: var(--r-ctl);
  background-color: var(--ds-color-bg-surface-inset);
  overflow-x: auto;
}
.ag-md :deep(table) {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--text-base);
  margin: var(--ds-space-2) 0 var(--ds-space-3);
}
.ag-md :deep(th),
.ag-md :deep(td) {
  border: 1px solid var(--ds-color-border-subtle);
  padding: var(--ds-space-2) var(--ds-space-3);
  text-align: left;
}
.ag-msg-proposal {
  margin-top: var(--ds-space-2);
}
.ag-composer-deck {
  padding: 0 var(--ds-space-5) var(--ds-space-4);
}
.ag-composer {
  max-width: 840px;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  gap: var(--ds-space-2);
  padding: var(--ds-space-3) var(--ds-space-4);
  border: 1px solid var(--ds-color-border-default);
  border-radius: var(--r-card);
  background-color: var(--ds-color-bg-surface-1);
  transition: border-color var(--dur-base) var(--ease-out);
}
.ag-composer.is-staged {
  border-color: var(--accent-line);
}
.ag-composer.is-highlighted {
  border-color: var(--ds-color-brand);
}
.ag-staged-bar {
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
  padding: var(--ds-space-2) var(--ds-space-3);
  border-radius: var(--r-ctl);
  background-color: var(--ds-color-brand-subtle);
}
.ag-staged-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--ds-space-2);
}
.ag-staged-badge {
  display: inline-flex;
  align-items: center;
  gap: var(--sp-1);
}
.ag-staged-preview {
  margin: 0;
  font-size: var(--text-base);
  color: var(--ds-color-text-primary);
  line-height: 1.5;
}
.ag-staged-hint {
  margin: 0;
  font-size: var(--text-xs);
  color: var(--ds-color-text-description);
}
.ag-input {
  width: 100%;
  height: auto;
  padding: 0;
  resize: vertical;
  min-height: 52px;
  border: 0;
  background: transparent;
  color: var(--ds-color-text-primary);
  font-size: var(--text-md);
  line-height: 1.6;
  outline: none;
}
.ag-input:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
.ag-input::placeholder {
  color: var(--ds-color-text-placeholder);
}
.ag-composer-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--ds-space-2);
  padding-top: var(--ds-space-1);
  border-top: 1px solid var(--ds-color-border-subtle);
}
.ag-composer-hint {
  font-size: var(--text-xs);
  color: var(--ds-color-text-placeholder);
}
@media (max-width: 1120px) {
  .ag-workspace {
    flex-direction: column;
    overflow: auto;
  }
  .ag-main-stage {
    min-height: 460px;
  }
  .ag-msg.is-user {
    max-width: 96%;
  }
}
</style>
