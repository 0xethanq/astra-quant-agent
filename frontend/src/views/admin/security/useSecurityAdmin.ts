import { computed, inject, onMounted, ref, type InjectionKey } from 'vue';
import { Layers, ShieldCheck, Wallet, Zap } from 'lucide-vue-next';
import { useApi } from '../../../composables/useApi';
import { useConfirm } from '../../../composables/useConfirm';
import { useI18n } from '../../../composables/useI18n';
import { useToast } from '../../../composables/useToast';
import { useAuthStore } from '../../../stores/auth';
import {
  deriveMxHealthChips,
  deriveOkxLinked,
  envBadge,
  okxEnvText as okxEnvTextOf,
} from '../securityLogic';

export type SecurityTabKey = 'venues' | 'pool' | 'emergency';

export function useSecurityAdmin() {
  const toast = useToast();
  const { ask } = useConfirm();
  const { api } = useApi();
  const auth = useAuthStore();
  const { t } = useI18n();

  const config = ref<any>(null);
  const runtime = ref<any>(null);
  const channels = ref<any[]>([]);
  const channelOf = (key: string) => channels.value.find((c) => c.key === key) || null;

  const loading = ref(true);
  const loadError = ref('');
  const activeTab = ref<SecurityTabKey>('venues');
  const positionsLoadedOnce = ref(false);

  const keys = ref({
    live_key: '',
    live_secret: '',
    live_pass: '',
    demo_key: '',
    demo_secret: '',
    demo_pass: '',
  });

  const newCapital = ref<string>('');
  const capitalConfirm = ref<string>('');
  const savingCapital = ref(false);
  const capitalAmountOk = computed(() => {
    const n = Number(newCapital.value);
    return !Number.isNaN(n) && n > 0;
  });
  const capitalConfirmOk = computed(() => capitalConfirm.value.trim().toUpperCase() === 'UPDATE CAPITAL');

  const instruments = ref<any[]>([]);
  const instLimits = ref<any>({ minimum: 1, maximum: 20 });

  const snapshot = ref<any>(null);
  const snapshotState = ref('');
  const snapshotError = ref(false);
  const manualClose = ref(false);
  const closePassword = ref('');
  const closeModal = ref<{ show: boolean; pos: any } | null>(null);
  const closePhraseInput = ref('');
  const closing = ref(false);
  const closePhraseOk = computed(() => {
    const pos = closeModal.value?.pos;
    if (!pos?.close_confirmation) return false;
    return closePhraseInput.value.trim().toUpperCase() === pos.close_confirmation;
  });
  const closeReady = computed(() => !!closePassword.value && closePhraseOk.value);

  const mx = ref<any>(null);
  const okxCredViewLive = ref(false);
  const orderMode = ref<'limit' | 'market' | 'smart'>('smart');
  const savingOrderMode = ref(false);
  const scaleOutEnabled = ref(true);
  const savingScaleOut = ref(false);
  const venueLatencies = ref<Record<string, number>>({});
  const savingOkx = ref(false);
  const probingVenue = ref<'' | 'okx'>('');
  const savingUnifiedEnv = ref(false);
  const isUnifiedLive = computed(() => config.value?.editable?.okx_environment === 'live');

  const plazaSettings = ref({
    enabled: false,
    nickname: '0xEthan',
    show_performance: true,
    show_balance: false,
    show_model: true,
    show_strategy_params: true,
    plaza_hub_url: 'https://hub.astraquant.tech',
  });
  const plazaIsLive = ref(false);
  const loadingPlaza = ref(false);
  const savingPlaza = ref(false);
  const showPlazaPreview = ref(false);
  const plazaPreviewData = ref<any>(null);
  const loadingPlazaPreview = ref(false);

  const plazaPublicUrl = computed(() => {
    if (typeof window !== 'undefined' && window.location) {
      return `${window.location.origin}/api/v1/public/plaza/profile`;
    }
    return '/api/v1/public/plaza/profile';
  });

  async function loadChannels() {
    try {
      const res = await api<any>('/api/v1/referral-channels');
      channels.value = Array.isArray(res?.channels) ? res.channels : [];
    } catch {
      channels.value = [];
    }
  }

  function applyRuntime(rt: any) {
    runtime.value = rt;
  }

  async function loadAll() {
    loading.value = true;
    loadError.value = '';
    try {
      const [cfg, rt] = await Promise.all([
        api('/api/v1/admin/config'),
        api('/api/v1/admin/okx/runtime?refresh=1').catch(() => null),
      ]);
      config.value = cfg;
      applyRuntime(rt);
      if (cfg?.editable?.okx_environment) {
        okxCredViewLive.value = cfg.editable.okx_environment === 'live';
      }
      if (cfg?.editable?.order_mode) {
        const m = String(cfg.editable.order_mode).trim().toLowerCase();
        orderMode.value = m === 'limit' || m === 'smart' ? m : 'market';
      } else {
        orderMode.value = 'smart';
      }
      scaleOutEnabled.value = cfg?.editable?.scale_out_enabled !== false;
      newCapital.value = String(cfg.editable?.initial_capital ?? '');
      manualClose.value = !!cfg.editable?.manual_close_enabled;
      const inst = await api('/api/v1/admin/instruments');
      instruments.value = inst.instruments || [];
      instLimits.value = inst.limits || instLimits.value;
    } catch (e: any) {
      loadError.value = String(e?.message || e);
      toast.err(t('admin.security.errLoadFailed', undefined, { msg: e.message }));
    } finally {
      loading.value = false;
    }
  }

  async function loadMx(preserveVenue?: string | Event) {
    try {
      const targetVenue = typeof preserveVenue === 'string' ? preserveVenue : undefined;
      mx.value = await api('/api/v1/admin/multi-exchange');
      if (mx.value?.health?.venues) {
        for (const [k, v] of Object.entries(mx.value.health.venues as Record<string, any>)) {
          if (v?.avg_ms && (!targetVenue || k !== targetVenue || !venueLatencies.value[k])) {
            venueLatencies.value[k] = v.avg_ms;
          }
        }
      }
    } catch {
      mx.value = null;
    }
  }

  async function requestUnifiedEnvSwitch(targetEnv: 'demo' | 'live') {
    if (savingUnifiedEnv.value) return;
    if (targetEnv === (isUnifiedLive.value ? 'live' : 'demo')) return;

    if (targetEnv === 'live') {
      const _ok = await ask({
        title: t('admin.security.confirmUnifiedLiveTitle'),
        desc: t('admin.security.confirmUnifiedLiveDesc'),
        detail: t('admin.security.confirmUnifiedLiveDetail'),
        danger: true,
        confirmPhrase: 'LIVE',
        okText: t('common.switchLive'),
      });
      if (!_ok) {
        toast.warn(t('admin.security.warnNotConfirmed'));
        return;
      }
    }

    savingUnifiedEnv.value = true;
    try {
      await api('/api/v1/admin/multi-exchange', {
        method: 'PUT',
        body: JSON.stringify({ okx_environment: targetEnv }),
      });
      await api('/api/v1/admin/config', {
        method: 'PUT',
        body: JSON.stringify({ okx_environment: targetEnv }),
      });
      if (config.value?.editable) {
        config.value.editable.okx_environment = targetEnv;
      }
      okxCredViewLive.value = targetEnv === 'live';
      toast.ok(t('admin.security.toastUnifiedEnvSaved', undefined, { env: targetEnv.toUpperCase() }));
      await Promise.all([loadAll(), loadMx()]);
    } catch (e: any) {
      toast.err(t('admin.security.errSaveFailed', undefined, { msg: e.message }));
    } finally {
      savingUnifiedEnv.value = false;
    }
  }

  async function saveEnvironment() {
    const environment = config.value.editable.okx_environment;
    savingOkx.value = true;
    try {
      const body: any = { okx_environment: environment };
      if (keys.value.live_key) body.okx_live_api_key = keys.value.live_key;
      if (keys.value.live_secret) body.okx_live_secret_key = keys.value.live_secret;
      if (keys.value.live_pass) body.okx_live_passphrase = keys.value.live_pass;
      if (keys.value.demo_key) body.okx_demo_api_key = keys.value.demo_key;
      if (keys.value.demo_secret) body.okx_demo_secret_key = keys.value.demo_secret;
      if (keys.value.demo_pass) body.okx_demo_passphrase = keys.value.demo_pass;
      await api('/api/v1/admin/config', { method: 'PUT', body: JSON.stringify(body) });
      keys.value = { live_key: '', live_secret: '', live_pass: '', demo_key: '', demo_secret: '', demo_pass: '' };
      toast.ok(t('admin.security.toastOkxCredsSaved'));
      await loadAll();
    } catch (e: any) {
      toast.err(t('admin.security.errSaveFailed', undefined, { msg: e.message }));
    } finally {
      savingOkx.value = false;
    }
  }

  async function saveOrderMode() {
    savingOrderMode.value = true;
    try {
      await api('/api/v1/admin/config', {
        method: 'PUT',
        body: JSON.stringify({ order_mode: orderMode.value }),
      });
      toast.ok(t('admin.security.toastOrderModeSaved'));
      await loadAll();
    } catch (e: any) {
      toast.err(t('admin.security.errSaveFailed', undefined, { msg: e.message }));
    } finally {
      savingOrderMode.value = false;
    }
  }

  async function toggleScaleOut(val: boolean) {
    savingScaleOut.value = true;
    try {
      await api('/api/v1/admin/config', {
        method: 'PUT',
        body: JSON.stringify({ scale_out_enabled: val }),
      });
      scaleOutEnabled.value = val;
      if (config.value?.editable) {
        config.value.editable.scale_out_enabled = val;
      }
      toast.ok(val ? t('admin.security.scaleOutOnToast') : t('admin.security.scaleOutOffToast'));
    } catch (e: any) {
      toast.err(t('admin.security.errSaveFailed', undefined, { msg: e?.message || e }));
    } finally {
      savingScaleOut.value = false;
    }
  }

  async function probeVenue(venue: 'okx') {
    probingVenue.value = venue;
    try {
      const isDemo = config.value?.editable?.okx_environment === 'demo';
      const env = isDemo ? 'demo' : 'live';
      const payload: Record<string, any> = { venue, environment: env };

      if (isDemo) {
        if (keys.value.demo_key.trim()) payload.api_key = keys.value.demo_key.trim();
        if (keys.value.demo_secret.trim()) payload.secret_key = keys.value.demo_secret.trim();
        if (keys.value.demo_pass.trim()) payload.passphrase = keys.value.demo_pass.trim();
      } else {
        if (keys.value.live_key.trim()) payload.api_key = keys.value.live_key.trim();
        if (keys.value.live_secret.trim()) payload.secret_key = keys.value.live_secret.trim();
        if (keys.value.live_pass.trim()) payload.passphrase = keys.value.live_pass.trim();
      }

      const res: any = await api('/api/v1/admin/multi-exchange/test-connection', {
        method: 'POST',
        body: JSON.stringify(payload),
      });

      if (res?.latency_ms) {
        venueLatencies.value[venue] = res.latency_ms;
      }
      if (res?.ok) {
        toast.ok(res.message || t('admin.security.toastProbeOk', undefined, { venue: venue.toUpperCase() }));
      } else {
        toast.err(res?.message || t('admin.security.toastProbeFail', undefined, { venue: venue.toUpperCase() }));
      }
      await loadMx(venue);
    } catch (e: any) {
      toast.err(t('admin.security.errProbeFailed', undefined, { msg: e.message }));
    } finally {
      probingVenue.value = '';
    }
  }

  async function saveCapital() {
    if (!auth.isSuperadmin) {
      toast.err(t('admin.security.errSuperadminOnly'));
      return;
    }
    if (capitalConfirm.value.trim().toUpperCase() !== 'UPDATE CAPITAL') {
      toast.err(t('admin.security.errPhraseCapital'));
      return;
    }
    savingCapital.value = true;
    try {
      const res = await api('/api/v1/admin/account-baseline', {
        method: 'PUT',
        body: JSON.stringify({
          initial_capital: parseFloat(newCapital.value),
          confirmation: capitalConfirm.value,
        }),
      });
      toast.ok(res.effect || t('admin.security.toastCapitalSet', undefined, { n: res.initial_capital }));
      capitalConfirm.value = '';
      await loadAll();
    } catch (e: any) {
      toast.err(t('admin.security.errUpdateFailed', undefined, { msg: e.message }));
    } finally {
      savingCapital.value = false;
    }
  }

  async function loadPositions() {
    snapshotState.value = t('admin.security.loadingPositions');
    snapshotError.value = false;
    try {
      const d = await api('/api/v1/admin/okx/account-snapshot');
      snapshot.value = d;
      snapshotState.value = '';
    } catch (e: any) {
      snapshotState.value = e.message;
      snapshotError.value = true;
      snapshot.value = null;
    }
  }

  async function saveManualClose() {
    try {
      const d = await api('/api/v1/admin/config', {
        method: 'PUT',
        body: JSON.stringify({ manual_close_enabled: manualClose.value }),
      });
      manualClose.value = !!(d?.editable?.manual_close_enabled ?? d?.manual_close_enabled);
      if (manualClose.value) toast.warn(t('admin.security.toastManualCloseOn'));
      else toast.ok(t('admin.security.toastManualCloseOff'));
    } catch (e: any) {
      toast.err(e.message);
    }
  }

  function openClose(pos: any) {
    if (!manualClose.value) {
      toast.err(t('admin.security.errEnableManualFirst'));
      return;
    }
    closePhraseInput.value = '';
    closeModal.value = { show: true, pos };
  }

  async function confirmClose() {
    if (closing.value) return;
    const pos = closeModal.value?.pos;
    if (!pos) return;
    if (!closePassword.value) {
      toast.err(t('admin.security.errNeedPassword'));
      return;
    }
    if (!pos.close_token || !pos.close_confirmation) {
      toast.err(t('admin.security.errCloseTokenMissing'));
      return;
    }
    if (closePhraseInput.value.trim().toUpperCase() !== pos.close_confirmation) {
      toast.err(t('admin.security.errPhraseClose', undefined, { phrase: pos.close_confirmation }));
      return;
    }
    closing.value = true;
    try {
      const d = await api('/api/v1/admin/positions/close', {
        method: 'POST',
        body: JSON.stringify({
          close_token: pos.close_token,
          admin_password: closePassword.value,
          confirmation: closePhraseInput.value.trim().toUpperCase(),
          venue: pos.venue || 'okx',
        }),
      });
      toast.ok(t('admin.security.toastCloseConfirmed', undefined, { inst: d.instId, size: d.closed_size }));
      closeModal.value = null;
      closePassword.value = '';
      await loadPositions();
    } catch (e: any) {
      toast.err(t('admin.security.errCloseFailed', undefined, { msg: e.message }));
      await loadPositions();
      const fresh = (snapshot.value?.positions || []).find(
        (x: any) =>
          x.instId === pos.instId &&
          (x.posSide || 'net') === (pos.posSide || 'net') &&
          (x.venue || 'okx') === (pos.venue || 'okx'),
      );
      if (fresh) closeModal.value = { show: true, pos: fresh };
      else {
        closeModal.value = null;
        closePassword.value = '';
      }
    } finally {
      closing.value = false;
    }
  }

  async function loadPlazaSettings() {
    loadingPlaza.value = true;
    try {
      const res = await api<any>('/api/v1/admin/plaza/settings');
      if (res?.settings) {
        plazaSettings.value = { ...plazaSettings.value, ...res.settings };
      }
      plazaIsLive.value = Boolean(res?.is_live);
    } catch {
      /* keep defaults */
    } finally {
      loadingPlaza.value = false;
    }
  }

  async function savePlazaSettings() {
    if (!isUnifiedLive.value) {
      toast.warn(t('admin.security.plazaLiveOnlyAlert'));
      return;
    }
    savingPlaza.value = true;
    try {
      await api('/api/v1/admin/plaza/settings', {
        method: 'PUT',
        body: JSON.stringify(plazaSettings.value),
      });
      toast.ok(t('admin.security.toastPlazaSaved'));
      await loadPlazaSettings();
    } catch (err: any) {
      toast.err(t('admin.security.errSaveFailed', undefined, { msg: err.message || 'Error' }));
    } finally {
      savingPlaza.value = false;
    }
  }

  function copyPlazaUrl() {
    navigator.clipboard.writeText(plazaPublicUrl.value);
    toast.ok(t('admin.security.toastPlazaCopied'));
  }

  async function openPlazaPreview() {
    showPlazaPreview.value = true;
    loadingPlazaPreview.value = true;
    try {
      plazaPreviewData.value = await api<any>('/api/v1/public/plaza/profile');
    } catch {
      plazaPreviewData.value = null;
    } finally {
      loadingPlazaPreview.value = false;
    }
  }

  function copyStrategyCloneData() {
    if (!plazaPreviewData.value?.strategy_clone_payload) return;
    navigator.clipboard.writeText(JSON.stringify(plazaPreviewData.value.strategy_clone_payload, null, 2));
    toast.ok(t('admin.security.plazaCloneSuccess'));
  }

  function openExternal(url: string) {
    window.open(url, '_blank', 'noopener,noreferrer');
  }

  function ensurePositionsLoaded() {
    if (!positionsLoadedOnce.value) {
      positionsLoadedOnce.value = true;
      void loadPositions();
    }
  }

  const okxLinked = computed(() => deriveOkxLinked(runtime.value));
  const mxHealthChips = computed(() => deriveMxHealthChips(mx.value));
  const okxEnvText = computed(() => okxEnvTextOf(config.value?.editable?.okx_environment, t));
  const healthAllOk = computed(() => {
    const chips = mxHealthChips.value || [];
    return chips.length > 0 && chips.every((h: any) => h.allOk);
  });
  const healthUnknownTotal = computed(() =>
    (mxHealthChips.value || []).reduce((sum: number, h: any) => sum + (h.unknown || 0), 0),
  );

  const bandFacts = computed(() => [
    {
      icon: ShieldCheck,
      label: t('admin.security.okxApi'),
      value: okxLinked.value ? t('admin.security.okxReady') : t('admin.security.okxNotReady'),
      foot: envBadge(runtime.value?.environment),
      tone: okxLinked.value ? 'is-up' : 'is-down',
    },
    {
      icon: Layers,
      label: t('admin.security.activePool'),
      value: t('admin.security.poolCount', undefined, {
        count: instruments.value.length,
        max: instLimits.value.maximum,
      }),
      foot: t('admin.security.usdtPerp'),
      tone: '',
    },
    {
      icon: Zap,
      label: t('admin.security.orderModeTitle'),
      value:
        orderMode.value === 'smart'
          ? t('admin.security.optSmart')
          : orderMode.value === 'market'
            ? t('admin.security.optMarket')
            : t('admin.security.optLimit'),
      foot:
        orderMode.value === 'smart'
          ? t('admin.security.orderModeFootSmart')
          : orderMode.value === 'market'
            ? t('admin.security.orderModeFootMarket')
            : t('admin.security.orderModeFootLimit'),
      tone: '',
    },
    {
      icon: Wallet,
      label: t('admin.security.capitalTitle'),
      value: `${config.value?.editable?.initial_capital ?? '--'} USDT`,
      foot: t('admin.security.capitalBandFoot'),
      tone: '',
    },
  ]);

  onMounted(() => {
    void loadAll();
    void loadMx();
    void loadChannels();
    void loadPlazaSettings();
  });

  return {
    activeTab,
    auth,
    bandFacts,
    capitalAmountOk,
    capitalConfirm,
    capitalConfirmOk,
    channelOf,
    closeModal,
    closePassword,
    closePhraseInput,
    closePhraseOk,
    closeReady,
    closing,
    config,
    confirmClose,
    copyPlazaUrl,
    copyStrategyCloneData,
    ensurePositionsLoaded,
    healthAllOk,
    healthUnknownTotal,
    instLimits,
    instruments,
    isUnifiedLive,
    keys,
    loadAll,
    loadError,
    loadMx,
    loadPositions,
    loading,
    loadingPlaza,
    loadingPlazaPreview,
    manualClose,
    mxHealthChips,
    newCapital,
    okxCredViewLive,
    okxEnvText,
    okxLinked,
    openClose,
    openExternal,
    openPlazaPreview,
    orderMode,
    plazaIsLive,
    plazaPreviewData,
    plazaPublicUrl,
    plazaSettings,
    probeVenue,
    probingVenue,
    requestUnifiedEnvSwitch,
    runtime,
    saveCapital,
    saveEnvironment,
    saveManualClose,
    saveOrderMode,
    savePlazaSettings,
    savingCapital,
    savingOkx,
    savingOrderMode,
    savingPlaza,
    savingScaleOut,
    savingUnifiedEnv,
    scaleOutEnabled,
    showPlazaPreview,
    snapshot,
    snapshotError,
    snapshotState,
    toggleScaleOut,
    venueLatencies,
  };
}

export type SecurityAdminCtx = ReturnType<typeof useSecurityAdmin>;
export const SECURITY_KEY: InjectionKey<SecurityAdminCtx> = Symbol('SECURITY_KEY');
export function useSecurityCtx(): SecurityAdminCtx {
  const ctx = inject(SECURITY_KEY);
  if (!ctx) throw new Error('useSecurityCtx() called without provider');
  return ctx;
}
