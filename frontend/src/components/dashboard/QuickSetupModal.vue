<script setup lang="ts">
import { ref, computed } from 'vue';
import { useI18n } from '../../composables/useI18n';
import { useApi } from '../../composables/useApi';
import BaseDialog from '../base/BaseDialog.vue';
import {
  KeyRound,
  Brain,
  ShieldCheck,
  CheckCircle2,
  AlertTriangle,
  Loader2,
  Sparkles,
} from 'lucide-vue-next';

defineProps<{
  open: boolean;
}>();

const emit = defineEmits<{
  (e: 'close'): void;
  (e: 'saved'): void;
}>();

const { t } = useI18n();
const { api } = useApi();

const currentStep = ref(1);

// Step 1: OKX
const okxEnv = ref<'demo' | 'live'>('demo');
const okxApiKey = ref('');
const okxSecretKey = ref('');
const okxPassphrase = ref('');
const testingOkx = ref(false);
const okxTestResult = ref<{ ok: boolean; msg?: string; latency?: number } | null>(null);

// Step 2: LLM (纯自定义供应商模式)
const customBaseUrl = ref('');
const customModel = ref('');
const llmApiKey = ref('');
const testingLlm = ref(false);
const llmTestResult = ref<{ ok: boolean; msg?: string } | null>(null);

// Step 3: Risk
const riskProfile = ref<'conservative' | 'balanced' | 'aggressive'>('balanced');
const adminPassword = ref('');

const saving = ref(false);
const saveError = ref('');
const saveSuccess = ref(false);

const derivedLlmConfig = computed(() => {
  return {
    baseUrl: customBaseUrl.value.trim() || 'https://api.openai.com/v1',
    model: customModel.value.trim() || 'gpt-4o',
  };
});

async function testOkxConnection() {
  if (!okxApiKey.value || !okxSecretKey.value || !okxPassphrase.value) {
    return;
  }
  testingOkx.value = true;
  okxTestResult.value = null;
  try {
    const res = await api<any>('/api/v1/admin/multi-exchange/test-connection', {
      method: 'POST',
      body: JSON.stringify({
        venue: 'okx',
        environment: okxEnv.value,
        api_key: okxApiKey.value.trim(),
        secret_key: okxSecretKey.value.trim(),
        passphrase: okxPassphrase.value.trim(),
        timeout: 8,
      }),
    });
    if (res && res.ok) {
      okxTestResult.value = { ok: true, latency: res.latency_ms || 120 };
    } else {
      okxTestResult.value = { ok: false, msg: res?.error || res?.mode || 'auth failed' };
    }
  } catch (err: any) {
    okxTestResult.value = { ok: false, msg: err?.message || 'network error' };
  } finally {
    testingOkx.value = false;
  }
}

async function testLlmConnection() {
  if (!llmApiKey.value) return;
  testingLlm.value = true;
  llmTestResult.value = null;
  const cfg = derivedLlmConfig.value;
  try {
    const res = await api<any>('/api/v1/admin/llm/test', {
      method: 'POST',
      body: JSON.stringify({
        base_url: cfg.baseUrl,
        api_key: llmApiKey.value.trim(),
        model: cfg.model,
        timeout: 15,
      }),
    });
    if (res && res.ok) {
      llmTestResult.value = { ok: true };
    } else {
      llmTestResult.value = { ok: false, msg: res?.error || 'model test failed' };
    }
  } catch (err: any) {
    llmTestResult.value = { ok: false, msg: err?.message || 'network error' };
  } finally {
    testingLlm.value = false;
  }
}

async function handleApply() {
  saving.value = true;
  saveError.value = '';
  saveSuccess.value = false;
  const cfg = derivedLlmConfig.value;

  try {
    const res = await api<any>('/api/v1/system/setup/apply', {
      method: 'POST',
      body: JSON.stringify({
        okx_env: okxEnv.value,
        okx_api_key: okxApiKey.value.trim(),
        okx_secret_key: okxSecretKey.value.trim(),
        okx_passphrase: okxPassphrase.value.trim(),
        llm_base_url: cfg.baseUrl,
        llm_api_key: llmApiKey.value.trim(),
        llm_model: cfg.model,
        llm_reasoning_effort: 'high',
        risk_profile: riskProfile.value,
        admin_password: adminPassword.value.trim(),
      }),
    });

    if (res && res.ok) {
      saveSuccess.value = true;
      setTimeout(() => {
        emit('saved');
        emit('close');
      }, 1500);
    } else {
      saveError.value = res?.message || 'save failed';
    }
  } catch (err: any) {
    saveError.value = err?.message || 'network error';
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <BaseDialog
    :open="open"
    :title="t('dash.firstRun.wizardTitle')"
    :desc="t('dash.firstRun.wizardDesc')"
    size="md"
    @close="emit('close')"
  >
    <template #title>
      <div class="flex items-center gap-2">
        <Sparkles class="h-5 w-5 text-amber-400" aria-hidden="true" />
        <span class="text-base font-bold text-[var(--ink-strong)]">{{ t('dash.firstRun.wizardTitle') }}</span>
      </div>
    </template>

    <div class="space-y-4">
      <!-- 步骤选择标签 -->
      <nav class="grid grid-cols-3 gap-1 rounded-lg bg-[var(--surface-2)] p-1" aria-label="Wizard Steps">
        <button
          type="button"
          class="flex items-center justify-center gap-1.5 rounded-md px-2 py-1.5 text-xs font-medium cursor-pointer transition-colors"
          :class="currentStep === 1 ? 'bg-[var(--surface-card)] text-[var(--ink-strong)] font-semibold shadow-sm' : 'text-[var(--ink-3)] hover:text-[var(--ink-1)]'"
          @click="currentStep = 1"
        >
          <KeyRound class="h-3.5 w-3.5" :class="currentStep === 1 ? 'text-amber-400' : ''" />
          <span>{{ t('dash.firstRun.wizardStep1') }}</span>
        </button>
        <button
          type="button"
          class="flex items-center justify-center gap-1.5 rounded-md px-2 py-1.5 text-xs font-medium cursor-pointer transition-colors"
          :class="currentStep === 2 ? 'bg-[var(--surface-card)] text-[var(--ink-strong)] font-semibold shadow-sm' : 'text-[var(--ink-3)] hover:text-[var(--ink-1)]'"
          @click="currentStep = 2"
        >
          <Brain class="h-3.5 w-3.5" :class="currentStep === 2 ? 'text-sky-400' : ''" />
          <span>{{ t('dash.firstRun.wizardStep2') }}</span>
        </button>
        <button
          type="button"
          class="flex items-center justify-center gap-1.5 rounded-md px-2 py-1.5 text-xs font-medium cursor-pointer transition-colors"
          :class="currentStep === 3 ? 'bg-[var(--surface-card)] text-[var(--ink-strong)] font-semibold shadow-sm' : 'text-[var(--ink-3)] hover:text-[var(--ink-1)]'"
          @click="currentStep = 3"
        >
          <ShieldCheck class="h-3.5 w-3.5" :class="currentStep === 3 ? 'text-emerald-400' : ''" />
          <span>{{ t('dash.firstRun.wizardStep3') }}</span>
        </button>
      </nav>

      <!-- Step 1: OKX -->
      <div v-show="currentStep === 1" class="space-y-3">
        <div>
          <label class="t-label mb-1.5 block">{{ t('dash.firstRun.envMode') }}</label>
          <div class="grid grid-cols-2 gap-2">
            <button
              type="button"
              class="flex flex-col items-start gap-1 rounded-lg border p-2.5 text-left transition-all cursor-pointer"
              :class="okxEnv === 'demo' ? 'border-emerald-500/40 bg-emerald-500/10 text-emerald-400' : 'border-[var(--line-2)] hover:bg-[var(--surface-2)] text-[var(--ink-2)]'"
              @click="okxEnv = 'demo'"
            >
              <span class="text-xs font-semibold">{{ t('dash.firstRun.demoMode') }}</span>
            </button>
            <button
              type="button"
              class="flex flex-col items-start gap-1 rounded-lg border p-2.5 text-left transition-all cursor-pointer"
              :class="okxEnv === 'live' ? 'border-rose-500/40 bg-rose-500/10 text-rose-400' : 'border-[var(--line-2)] hover:bg-[var(--surface-2)] text-[var(--ink-2)]'"
              @click="okxEnv = 'live'"
            >
              <span class="text-xs font-semibold">{{ t('dash.firstRun.liveMode') }}</span>
            </button>
          </div>
        </div>

        <div class="space-y-2">
          <div>
            <label class="t-label mb-1 block" for="wiz-okx-key">API Key</label>
            <input
              id="wiz-okx-key"
              v-model="okxApiKey"
              type="text"
              class="input w-full font-mono text-xs"
              :placeholder="t('dash.firstRun.keyPlaceholder')"
              autocomplete="off"
              spellcheck="false"
            />
          </div>
          <div>
            <label class="t-label mb-1 block" for="wiz-okx-secret">Secret Key</label>
            <input
              id="wiz-okx-secret"
              v-model="okxSecretKey"
              type="password"
              class="input w-full font-mono text-xs"
              :placeholder="t('dash.firstRun.secretPlaceholder')"
              autocomplete="off"
              spellcheck="false"
            />
          </div>
          <div>
            <label class="t-label mb-1 block" for="wiz-okx-pass">Passphrase</label>
            <input
              id="wiz-okx-pass"
              v-model="okxPassphrase"
              type="password"
              class="input w-full font-mono text-xs"
              :placeholder="t('dash.firstRun.passphrasePlaceholder')"
              autocomplete="off"
              spellcheck="false"
            />
          </div>
        </div>

        <div class="flex items-center justify-between pt-1">
          <button
            type="button"
            class="btn btn-quiet btn-sm"
            :disabled="testingOkx || !okxApiKey"
            @click="testOkxConnection"
          >
            <Loader2 v-if="testingOkx" class="h-3.5 w-3.5 animate-spin shrink-0" />
            <span v-if="testingOkx">{{ t('dash.firstRun.testingOkx') }}</span>
            <span v-else>{{ t('dash.firstRun.testOkxBtn') }}</span>
          </button>
          <button type="button" class="btn btn-primary btn-sm" @click="currentStep = 2">
            <span>{{ t('common.next') }}</span>
          </button>
        </div>

        <div v-if="okxTestResult" class="text-xs">
          <p v-if="okxTestResult.ok" class="text-emerald-400 flex items-center gap-1.5">
            <CheckCircle2 class="h-3.5 w-3.5" />
            <span>{{ t('dash.firstRun.testOkxSuccess', undefined, { ms: okxTestResult.latency || 120 }) }}</span>
          </p>
          <p v-else class="text-rose-400 flex items-center gap-1.5">
            <AlertTriangle class="h-3.5 w-3.5" />
            <span>{{ t('dash.firstRun.testOkxFail', undefined, { msg: okxTestResult.msg || '' }) }}</span>
          </p>
        </div>
      </div>

      <!-- Step 2: LLM (纯自定义配置) -->
      <div v-show="currentStep === 2" class="space-y-3">
        <div class="grid grid-cols-1 sm:grid-cols-2 gap-2">
          <div>
            <label class="t-label mb-1 block" for="wiz-custom-url">Base URL</label>
            <input
              id="wiz-custom-url"
              v-model="customBaseUrl"
              type="text"
              class="input w-full font-mono text-xs"
              :placeholder="t('dash.firstRun.customUrlPlaceholder')"
            />
          </div>
          <div>
            <label class="t-label mb-1 block" for="wiz-custom-model">Model</label>
            <input
              id="wiz-custom-model"
              v-model="customModel"
              type="text"
              class="input w-full font-mono text-xs"
              :placeholder="t('dash.firstRun.customModelPlaceholder')"
            />
          </div>
        </div>

        <div>
          <label class="t-label mb-1 block" for="wiz-llm-key">API Key</label>
          <input
            id="wiz-llm-key"
            v-model="llmApiKey"
            type="password"
            class="input w-full font-mono text-xs"
            :placeholder="t('dash.firstRun.llmKeyPlaceholder')"
            autocomplete="off"
            spellcheck="false"
          />
        </div>

        <div class="flex items-center justify-between pt-1">
          <button
            type="button"
            class="btn btn-quiet btn-sm"
            :disabled="testingLlm || !llmApiKey"
            @click="testLlmConnection"
          >
            <Loader2 v-if="testingLlm" class="h-3.5 w-3.5 animate-spin shrink-0" />
            <span v-if="testingLlm">{{ t('dash.firstRun.testingLlm') }}</span>
            <span v-else>{{ t('dash.firstRun.testLlmBtn') }}</span>
          </button>
          <div class="flex gap-2">
            <button type="button" class="btn btn-quiet btn-sm" @click="currentStep = 1">
              <span>{{ t('common.prev') }}</span>
            </button>
            <button type="button" class="btn btn-primary btn-sm" @click="currentStep = 3">
              <span>{{ t('common.next') }}</span>
            </button>
          </div>
        </div>

        <div v-if="llmTestResult" class="text-xs">
          <p v-if="llmTestResult.ok" class="text-emerald-400 flex items-center gap-1.5">
            <CheckCircle2 class="h-3.5 w-3.5" />
            <span>{{ t('dash.firstRun.testLlmSuccess') }}</span>
          </p>
          <p v-else class="text-rose-400 flex items-center gap-1.5">
            <AlertTriangle class="h-3.5 w-3.5" />
            <span>{{ t('dash.firstRun.testLlmFail', undefined, { msg: llmTestResult.msg || '' }) }}</span>
          </p>
        </div>
      </div>

      <!-- Step 3: Risk & Finish -->
      <div v-show="currentStep === 3" class="space-y-3">
        <div>
          <label class="t-label mb-1.5 block">{{ t('dash.firstRun.riskProfile') }}</label>
          <div class="space-y-2">
            <button
              v-for="r in [
                { id: 'conservative', labelKey: 'dash.firstRun.riskConservative', desc: '2-3x' },
                { id: 'balanced', labelKey: 'dash.firstRun.riskBalanced', desc: '3-5x' },
                { id: 'aggressive', labelKey: 'dash.firstRun.riskAggressive', desc: '5-7x' },
              ]"
              :key="r.id"
              type="button"
              class="w-full flex items-center justify-between rounded-lg border p-2.5 text-left transition-colors cursor-pointer"
              :class="riskProfile === r.id ? 'border-emerald-500/40 bg-emerald-500/10 text-emerald-400 font-semibold' : 'border-[var(--line-2)] hover:bg-[var(--surface-2)] text-[var(--ink-2)]'"
              @click="riskProfile = r.id as any"
            >
              <span class="text-xs">{{ t(r.labelKey) }}</span>
            </button>
          </div>
        </div>

        <div>
          <label class="t-label mb-1 block" for="wiz-admin-pass">Superadmin Password (12+ chars, optional)</label>
          <input
            id="wiz-admin-pass"
            v-model="adminPassword"
            type="password"
            class="input w-full font-mono text-xs"
            placeholder="••••••••••••••••"
            autocomplete="new-password"
            spellcheck="false"
          />
        </div>

        <div v-if="saveError" role="alert" class="p-2.5 rounded-lg border border-rose-500/30 bg-rose-500/10 text-rose-400 text-xs flex items-center gap-2">
          <AlertTriangle class="h-4 w-4 shrink-0" />
          <span>{{ saveError }}</span>
        </div>

        <div v-if="saveSuccess" role="status" class="p-2.5 rounded-lg border border-emerald-500/30 bg-emerald-500/10 text-emerald-400 text-xs flex items-center gap-2">
          <CheckCircle2 class="h-4 w-4 shrink-0" />
          <span>{{ t('dash.firstRun.saveSuccess') }}</span>
        </div>

        <div class="flex items-center justify-between pt-2">
          <button type="button" class="btn btn-quiet btn-sm" @click="currentStep = 2">
            <span>{{ t('common.prev') }}</span>
          </button>
          <button
            type="button"
            class="btn btn-primary btn-sm"
            :disabled="saving"
            @click="handleApply"
          >
            <Loader2 v-if="saving" class="h-3.5 w-3.5 animate-spin shrink-0" />
            <span v-if="saving">{{ t('dash.firstRun.saving') }}</span>
            <span v-else>{{ t('dash.firstRun.saveAndActivate') }}</span>
          </button>
        </div>
      </div>
    </div>
  </BaseDialog>
</template>
