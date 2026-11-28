<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from 'vue';
import {
  Bot,
  ChevronDown,
  ChevronRight,
  Loader2,
  MessageSquare,
  PanelLeft,
  PanelRight,
  Plus,
  Send,
  Sparkles,
  Square,
  Trash2,
  Wrench,
} from 'lucide-vue-next';
import PageHeader from '../../components/admin/PageHeader.vue';
import { get, post, put, del, streamPost } from '../../api/http';
import { useAuthStore } from '../../stores/auth';
import { useConfirm } from '../../composables/useConfirm';
import { useI18n } from '../../composables/useI18n';
import { useToast } from '../../composables/useToast';
import AgentProposalCard from './agent/AgentProposalCard.vue';
import AgentStrategySidebar from './agent/AgentStrategySidebar.vue';
import {
  type AgentMessageItem,
  type AgentProposal,
  STARTER_PROMPTS,
} from './agent/agentLogic';

const { t } = useI18n();
const auth = useAuthStore();
const toast = useToast();
const { ask } = useConfirm();

const loading = ref(true);
const loadError = ref('');
const summaryLoading = ref(false);
const showSessionsPanel = ref(true);
const showSummaryPanel = ref(true);

const agentConfig = ref<any>(null);
const stateSummary = ref<any>(null);
const sessions = ref<any[]>([]);
const activeSessionId = ref('');
const messages = ref<AgentMessageItem[]>([]);
const proposals = ref<AgentProposal[]>([]);

const draft = ref('');
const streaming = ref(false);
const streamAbort = ref<AbortController | null>(null);
const applyingProposalId = ref('');
const savingModel = ref(false);
const expandedReasoning = ref<Record<string, boolean>>({});
const chatScrollRef = ref<HTMLElement | null>(null);

const selectedModelId = computed(() => String(agentConfig.value?.model_id || 'auto'));
const availableModels = computed<any[]>(() => agentConfig.value?.available_models || []);
const activeBrainLabel = computed(() => {
  const llm = stateSummary.value?.llm;
  return llm?.active_model_name || llm?.active_model_id || '—';
});
const envBadgeClass = computed(() =>
  stateSummary.value?.environment === 'live' ? 'badge-warn' : 'badge-accent',
);
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
    stateSummary.value = await get('/api/v1/admin/agent/state-summary');
  } catch {
    /* keep existing summary on refresh failure */
  } finally {
    summaryLoading.value = false;
  }
}

async function openSession(sessionId: string) {
  if (!sessionId) return;
  activeSessionId.value = sessionId;
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

async function bootstrap() {
  loading.value = true;
  loadError.value = '';
  try {
    const [cfg, sum, listRes] = await Promise.all([
      get('/api/v1/admin/agent/config'),
      get('/api/v1/admin/agent/state-summary'),
      get('/api/v1/admin/agent/sessions'),
    ]);
    agentConfig.value = cfg;
    stateSummary.value = sum;
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

async function sendMessage(overrideText?: string) {
  const text = String(overrideText ?? draft.value).trim();
  if (!text || streaming.value) return;

  if (!activeSessionId.value) {
    await createSession();
  }
  const sid = activeSessionId.value;
  if (!sid) return;

  if (overrideText === undefined) {
    draft.value = '';
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

function onComposerKeydown(ev: KeyboardEvent) {
  if (ev.key === 'Enter' && !ev.shiftKey && !ev.isComposing) {
    ev.preventDefault();
    sendMessage();
  }
}

onMounted(bootstrap);
</script>

<template>
  <div class="ag-page">
    <PageHeader :title="t('admin.agent.title')" :description="t('admin.agent.desc')" :badge="t('admin.agent.badge')">
      <template #actions>
        <div class="ag-header-controls">
          <button
            type="button"
            class="btn btn-ghost btn-sm"
            :aria-expanded="showSessionsPanel"
            :aria-controls="showSessionsPanel ? 'ag-sessions-panel' : undefined"
            @click="showSessionsPanel = !showSessionsPanel"
          >
            <PanelLeft :size="14" />
            <span>{{ t('admin.agent.sidebarSessionsToggle') }}</span>
          </button>
          <button
            type="button"
            class="btn btn-ghost btn-sm"
            :aria-expanded="showSummaryPanel"
            :aria-controls="showSummaryPanel ? 'ag-summary-panel' : undefined"
            @click="showSummaryPanel = !showSummaryPanel"
          >
            <PanelRight :size="14" />
            <span>{{ t('admin.agent.sidebarSummaryToggle') }}</span>
          </button>
        </div>
      </template>
    </PageHeader>

    <section class="card ag-strip" :aria-label="t('admin.agent.runtimeStripAria')">
      <div class="ag-strip-metrics">
        <span class="badge mono" :class="envBadgeClass">
          {{ t('admin.agent.stripEnv') }}: {{ String(stateSummary?.environment || 'demo').toUpperCase() }}
        </span>
        <span class="ag-strip-pill mono">
          {{ t('admin.agent.stripBrain') }}: <strong>{{ activeBrainLabel }}</strong>
        </span>
        <span class="ag-strip-pill mono num">
          {{ t('admin.agent.stripPositions') }}: <strong>{{ stateSummary?.account?.positions_count ?? 0 }}</strong>
        </span>
        <span class="badge" :class="healthBadgeClass">
          {{ t('admin.agent.stripHealth') }}: {{ healthLabel }}
        </span>
        <span v-if="stateSummary?.version" class="ag-strip-pill mono">
          {{ t('admin.agent.stripVersion') }}: {{ stateSummary.version }}
        </span>
      </div>

      <label class="ag-model-picker">
        <span class="form-label">{{ t('admin.agent.modelLabel') }}</span>
        <select
          :value="selectedModelId"
          :disabled="!auth.isSuperadmin || savingModel"
          :aria-label="t('admin.agent.modelAria')"
          class="field ag-model-select"
          @change="updateModel(($event.target as HTMLSelectElement).value)"
        >
          <option value="auto">
            {{ t('admin.agent.modelAuto', undefined, { model: activeBrainLabel }) }}
          </option>
          <option v-for="m in availableModels" :key="m.id" :value="m.id">
            {{ m.name }} ({{ m.provider_name || m.api_format }})
          </option>
        </select>
      </label>
    </section>

    <p v-if="!auth.isSuperadmin" role="status" class="ag-readonly-banner">
      {{ t('admin.agent.readonlyNotice') }}
    </p>

    <div class="ag-workspace">
      <aside v-if="showSessionsPanel" id="ag-sessions-panel" class="card ag-sessions">
        <header class="card-head">
          <span class="ag-sessions-title">{{ t('admin.agent.sessionsTitle') }}</span>
          <button type="button" class="btn btn-primary btn-sm" @click="createSession">
            <Plus :size="13" />
            <span>{{ t('admin.agent.newSession') }}</span>
          </button>
        </header>

        <div class="ag-sessions-list">
          <p v-if="!sessions.length" class="ag-sessions-empty">{{ t('admin.agent.sessionsEmpty') }}</p>
          <div
            v-for="sess in sessions"
            :key="sess.id"
            class="ag-sess-row"
            :class="{ 'is-active': sess.id === activeSessionId }"
          >
            <button
              type="button"
              class="ag-sess-select"
              @click="openSession(sess.id)"
            >
              <MessageSquare :size="13" class="shrink-0" />
              <span class="truncate">{{ sess.title || t('admin.agent.sessionDefaultTitle') }}</span>
            </button>
            <button
              type="button"
              class="btn btn-quiet btn-icon btn-sm is-danger"
              :aria-label="t('admin.agent.deleteSessionAria')"
              :title="t('admin.agent.deleteSessionTitle')"
              @click="deleteSession(sess.id)"
            >
              <Trash2 :size="12" />
            </button>
          </div>
        </div>
      </aside>

      <section class="card ag-chat">
        <div ref="chatScrollRef" class="ag-stream">
          <div v-if="!messages.length && !loading" class="ag-empty">
            <span class="ag-empty-icon"><Bot :size="20" /></span>
            <h2 class="ag-empty-title">{{ t('admin.agent.emptyWelcomeTitle') }}</h2>
            <p class="ag-empty-desc">{{ t('admin.agent.emptyWelcomeDesc') }}</p>
            <div class="ag-starters" role="group" :aria-label="t('admin.agent.startersLabel')">
              <button
                v-for="sp in STARTER_PROMPTS"
                :key="sp.id"
                type="button"
                class="btn btn-ghost btn-sm ag-starter-btn"
                @click="sendMessage(t(sp.key))"
              >
                <Sparkles :size="12" />
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
            <header class="ag-msg-head">
              <span class="ag-msg-role">
                {{ msg.role === 'user' ? t('admin.agent.roleUser') : t('admin.agent.roleAssistant') }}
              </span>
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

            <div v-if="(msg.tool_calls || []).length" class="ag-traces" :aria-label="t('admin.agent.toolsTitle')">
              <div v-for="tc in msg.tool_calls" :key="tc.id" class="ag-trace-row">
                <Wrench :size="12" class="shrink-0" />
                <span class="mono ag-trace-name">{{ tc.name }}</span>
                <span
                  class="badge mono"
                  :class="tc.status === 'error' ? 'badge-down' : tc.status === 'ok' ? 'badge-up' : 'badge-accent'"
                >
                  {{ tc.status === 'error' ? t('admin.agent.toolError') : tc.status === 'ok' ? t('admin.agent.toolDone') : t('admin.agent.toolRunning') }}
                </span>
                <span v-if="tc.summary" class="ag-trace-summary truncate">{{ tc.summary }}</span>
              </div>
            </div>

            <div v-if="msg.content" class="ag-msg-text">{{ msg.content }}</div>

            <div v-for="pid in (msg.proposal_ids || [])" :key="pid" class="ag-msg-proposal">
              <AgentProposalCard
                v-if="proposalMap[pid]"
                :proposal="proposalMap[pid]"
                :busy="applyingProposalId === pid"
                @apply="handleProposalApply"
                @reject="handleProposalReject"
              />
            </div>
          </article>
        </div>

        <footer class="ag-composer">
          <textarea
            v-model="draft"
            rows="3"
            autocomplete="off"
            spellcheck="false"
            class="field ag-input"
            :aria-label="t('admin.agent.inputLabel')"
            :placeholder="t('admin.agent.inputPlaceholder')"
            :disabled="streaming"
            @keydown="onComposerKeydown"
          />
          <div class="ag-composer-actions">
            <button
              v-if="streaming"
              type="button"
              class="btn btn-ghost btn-sm is-danger"
              @click="stopGeneration"
            >
              <Square :size="13" />
              <span>{{ t('admin.agent.stop') }}</span>
            </button>
            <button
              v-else
              type="button"
              class="btn btn-primary btn-sm"
              :disabled="!draft.trim()"
              @click="sendMessage()"
            >
              <Loader2 v-if="loading" :size="13" class="animate-spin shrink-0" />
              <Send v-else :size="13" />
              <span>{{ t('admin.agent.send') }}</span>
            </button>
          </div>
        </footer>
      </section>

      <AgentStrategySidebar
        v-if="showSummaryPanel"
        id="ag-summary-panel"
        :summary="stateSummary"
        :loading="summaryLoading"
        @refresh="loadStateSummary"
        @ask="sendMessage"
      />
    </div>
  </div>
</template>

<style scoped>
.ag-page {
  display: flex;
  flex-direction: column;
  gap: var(--ds-space-4);
}
.ag-header-controls {
  display: flex;
  align-items: center;
  gap: var(--ds-space-2);
  flex-wrap: wrap;
}
.ag-strip {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--ds-space-4);
  flex-wrap: wrap;
  padding: var(--ds-space-3) var(--ds-space-4);
}
.ag-strip-metrics {
  display: flex;
  align-items: center;
  gap: var(--ds-space-2);
  flex-wrap: wrap;
}
.ag-strip-pill {
  font-size: var(--text-4xs);
  color: var(--ds-color-text-description);
}
.ag-strip-pill strong {
  color: var(--ds-color-text-primary);
}
.ag-model-picker {
  display: flex;
  align-items: center;
  gap: var(--ds-space-2);
}
.ag-model-select {
  min-width: 220px;
}
.ag-readonly-banner {
  margin: 0;
  padding: var(--ds-space-2) var(--ds-space-4);
  border: 1px solid var(--warn-line);
  border-radius: var(--r-ctl);
  background-color: var(--warn-bg);
  color: var(--warn);
  font-size: var(--text-3xs);
}
.ag-workspace {
  display: grid;
  grid-template-columns: 240px minmax(0, 1fr) 280px;
  gap: var(--ds-space-4);
  align-items: start;
}
.ag-sessions {
  display: flex;
  flex-direction: column;
}
.ag-sessions-title {
  font-size: var(--text-3xs);
  font-weight: 600;
  color: var(--ds-color-text-primary);
}
.ag-sessions-list {
  display: flex;
  flex-direction: column;
  gap: var(--ds-space-1);
  padding: var(--ds-space-2);
  max-height: 540px;
  overflow-y: auto;
}
.ag-sessions-empty {
  margin: 0;
  padding: var(--ds-space-4);
  font-size: var(--text-4xs);
  color: var(--ds-color-text-placeholder);
}
.ag-sess-row {
  display: flex;
  align-items: center;
  gap: var(--ds-space-1);
  padding: var(--ds-space-1);
  border-radius: var(--r-ctl);
  border: 1px solid transparent;
  transition: background-color var(--dur-fast);
}
.ag-sess-row.is-active {
  background-color: var(--ds-color-bg-surface-inset);
  border-color: var(--accent-line);
}
.ag-sess-select {
  display: flex;
  align-items: center;
  gap: var(--ds-space-2);
  flex: 1;
  min-width: 0;
  background: transparent;
  border: 0;
  color: var(--ds-color-text-primary);
  font-size: var(--text-3xs);
  text-align: left;
  cursor: pointer;
  padding: var(--ds-space-1) var(--ds-space-2);
}
.ag-chat {
  display: flex;
  flex-direction: column;
  min-height: 580px;
}
.ag-stream {
  display: flex;
  flex-direction: column;
  gap: var(--ds-space-4);
  padding: var(--ds-space-4);
  flex: 1;
  max-height: 620px;
  overflow-y: auto;
}
.ag-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  gap: var(--ds-space-3);
  padding: var(--ds-space-6) var(--ds-space-4);
}
.ag-empty-icon {
  display: grid;
  place-items: center;
  width: 44px;
  height: 44px;
  border-radius: var(--r-card);
  border: 1px solid var(--accent-line);
  background-color: var(--accent-bg);
  color: var(--accent);
}
.ag-empty-title {
  margin: 0;
  font-size: var(--text-base);
  font-weight: 600;
  color: var(--ds-color-text-primary);
}
.ag-empty-desc {
  margin: 0;
  max-width: 560px;
  font-size: var(--text-3xs);
  color: var(--ds-color-text-description);
  line-height: var(--leading-body);
}
.ag-starters {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: var(--ds-space-2);
}
.ag-starter-btn {
  text-align: left;
}
.ag-msg {
  display: flex;
  flex-direction: column;
  gap: var(--ds-space-2);
  padding: var(--ds-space-3) var(--ds-space-4);
  border-radius: var(--r-card);
  border: 1px solid var(--ds-color-border-default);
}
.ag-msg.is-user {
  background-color: var(--ds-color-bg-surface-inset);
}
.ag-msg.is-assistant {
  background-color: var(--ds-color-bg-surface);
}
.ag-msg-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--ds-space-2);
}
.ag-msg-role {
  font-size: var(--text-4xs);
  font-weight: 600;
  color: var(--ds-color-text-description);
}
.ag-msg-time {
  font-size: var(--text-4xs);
  color: var(--ds-color-text-placeholder);
}
.ag-reasoning-wrap {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: var(--ds-space-1);
}
.ag-reasoning-box {
  margin: var(--ds-space-2) 0 0;
  padding: var(--ds-space-3);
  border: 1px solid var(--ds-color-border-default);
  border-radius: var(--r-ctl);
  background-color: var(--ds-color-bg-surface-inset);
  font-size: var(--text-4xs);
  white-space: pre-wrap;
  word-break: break-word;
}
.ag-traces {
  display: flex;
  flex-direction: column;
  gap: var(--ds-space-1);
}
.ag-trace-row {
  display: flex;
  align-items: center;
  gap: var(--ds-space-2);
  padding: var(--ds-space-1) var(--ds-space-2);
  border-radius: var(--r-ctl);
  background-color: var(--ds-color-bg-surface-inset);
  font-size: var(--text-4xs);
}
.ag-trace-name {
  color: var(--ds-color-text-primary);
  font-weight: 600;
}
.ag-trace-summary {
  color: var(--ds-color-text-description);
  min-width: 0;
}
.ag-msg-text {
  font-size: var(--text-3xs);
  line-height: var(--leading-body);
  color: var(--ds-color-text-primary);
  white-space: pre-wrap;
  word-break: break-word;
}
.ag-msg-proposal {
  margin-top: var(--ds-space-2);
}
.ag-composer {
  display: flex;
  flex-direction: column;
  gap: var(--ds-space-2);
  padding: var(--ds-space-3) var(--ds-space-4);
  border-top: 1px solid var(--ds-color-border-default);
  background-color: var(--ds-color-bg-surface-inset);
}
.ag-input {
  width: 100%;
  resize: vertical;
  min-height: 76px;
}
.ag-composer-actions {
  display: flex;
  justify-content: flex-end;
  gap: var(--ds-space-2);
}
@media (max-width: 1120px) {
  .ag-workspace {
    grid-template-columns: 1fr;
  }
}
</style>
