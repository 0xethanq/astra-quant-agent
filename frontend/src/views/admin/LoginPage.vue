<script setup lang="ts">
/**
 * LoginPage.vue · 系统管理员鉴权入口
 * ---------------------------------------------------------------------------
 * 极简高端、通透精致的开发者控制台质感（参考 Linear / Vercel / DeepSeek）：
 *   - 居中微发光悬浮毛玻璃工位卡片
 *   - 严谨、专业、克制的排版与信息层级
 *   - 真实高精度控件与平滑交互反馈
 *
 * 行为契约：
 *   auth.login(username, password) → 成功后 router.push('/admin/overview')
 *   失败时呈现 auth.error 提示；提交中禁用并显示「正在验证…」
 */
import { ref } from 'vue';
import { useRouter } from 'vue-router';
import {
  LogIn,
  AlertCircle,
  Loader2,
  Eye,
  EyeOff,
  ArrowLeft,
  ShieldCheck
} from 'lucide-vue-next';
import { useAuthStore } from '../../stores/auth';
import { useI18n } from '../../composables/useI18n';
import { APP_VERSION } from '../../config/version';

const auth = useAuthStore();
const router = useRouter();
const { t, currentLocale, setLocale, LOCALE_OPTIONS } = useI18n();

const username = ref('');
const password = ref('');
const showPwd = ref(false);
const loading = ref(false);

async function handleLogin() {
  if (!username.value || !password.value || loading.value) return;
  loading.value = true;
  const ok = await auth.login(username.value, password.value);
  loading.value = false;
  if (ok) router.push('/admin/overview');
}
</script>

<template>
  <div class="auth-page">
    <!-- 顶部极简操作条 -->
    <header class="auth-topbar">
      <button type="button" class="auth-back-btn" @click="router.push('/')">
        <ArrowLeft :size="14" />
        <span>{{ t('admin.login.backToScreen') }}</span>
      </button>

      <!-- 批 75：语言名此前硬编码在模板里（`中文` / `EN`），与设置面板的
           `中文` / `English` 不一致。现按 useI18n 导出的唯一常量渲染。 -->
      <div class="auth-lang-pill" role="group" :aria-label="t('common.language')">
        <template v-for="(opt, i) in LOCALE_OPTIONS" :key="opt.value">
          <span v-if="i > 0" class="auth-lang-sep" />
          <button type="button"
            class="auth-lang-opt"
            :class="{ 'is-active': currentLocale === opt.value }"
            :aria-pressed="currentLocale === opt.value"
            @click="setLocale(opt.value)"
          >
            {{ opt.label }}
          </button>
        </template>
      </div>
    </header>

    <!-- 登录工位核心卡片 -->
    <main class="auth-card-wrap">
      <div class="auth-card">
        <!-- 品牌标识与标题区 -->
        <div class="auth-header">
          <div class="auth-logo-box">
            <img src="/favicon.svg" class="auth-logo" alt="" />
          </div>
          <h1 class="auth-title">{{ t('brand.name') }}</h1>
          <p class="auth-subtitle">
            <span>{{ t('admin.login.panelTitle') }}</span>
            <span class="auth-version-tag mono">{{ APP_VERSION }}</span>
          </p>
        </div>

        <!-- 错误提示横幅 -->
        <div v-if="auth.error" class="auth-alert" role="alert">
          <AlertCircle :size="15" class="auth-alert-icon" />
          <span>{{ auth.error }}</span>
        </div>

        <!-- 登录表单 -->
        <form class="auth-form" @submit.prevent="handleLogin">
          <div class="field-stack">
            <label class="auth-label" for="login-user">
              {{ t('admin.login.username') }}
            </label>
            <input
              id="login-user"
              v-model="username"
              type="text"
              autocomplete="username"
              class="auth-input"
              :placeholder="t('admin.shell.common.inputPlaceholder')"
              required
            />
          </div>

          <div class="field-stack">
            <div class="auth-label-row">
              <label class="auth-label" for="login-pwd">
                {{ t('admin.login.password') }}
              </label>
            </div>
            <div class="auth-input-pwd-wrap">
              <input
                id="login-pwd"
                v-model="password"
                :type="showPwd ? 'text' : 'password'"
                autocomplete="current-password"
                class="auth-input"
                placeholder="••••••••••••"
                required
              />
              <button
                type="button"
                class="auth-eye-btn"
                :title="showPwd ? t('admin.login.hidePwd') : t('admin.login.showPwd')"
                :aria-label="showPwd ? t('admin.login.hidePwd') : t('admin.login.showPwd')"
                @click="showPwd = !showPwd"
              >
                <EyeOff v-if="showPwd" :size="14" />
                <Eye v-else :size="14" />
              </button>
            </div>
          </div>

          <!-- 登录主按钮 -->
          <button
            type="submit"
            class="auth-submit-btn"
            :disabled="loading || !username || !password"
          >
            <LogIn v-if="!loading" :size="15" />
            <Loader2 v-else :size="15" class="animate-spin shrink-0" />
            <span>{{ loading ? t('admin.login.submitting') : t('admin.login.submit') }}</span>
          </button>
        </form>

        <!-- 安全警示说明 -->
        <div class="auth-footer">
          <ShieldCheck :size="13" class="auth-shield" />
          <span>{{ t('admin.login.rateHint') }}</span>
        </div>
      </div>

      <!-- 底部安全状态 -->
      <div class="auth-meta-bar mono">
        <span class="auth-meta-dot" aria-hidden="true" />
        <span>ENCRYPTED ACCESS</span>
      </div>
    </main>
  </div>
</template>

<style scoped>
.auth-page {
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 100vh;
  padding: 24px;
  background-color: var(--ds-color-bg-page);
  overflow: hidden;
}

/* 顶部操作条 */
.auth-topbar {
  position: absolute;
  top: 20px;
  left: 24px;
  right: 24px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  z-index: 20;
}

.auth-back-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  border-radius: var(--r-ctl);
  background: transparent;
  border: 1px solid transparent;
  color: var(--ds-color-text-description);
  font-size: var(--text-xs);
  cursor: pointer;
  transition: all var(--dur-fast) var(--ease-out);
}
.auth-back-btn:hover {
  background: var(--ds-color-bg-hover);
  border-color: var(--ds-color-border-hover);
  color: var(--ds-color-text-primary);
}

.auth-lang-pill {
  display: inline-flex;
  align-items: center;
  padding: var(--sp-1) var(--sp-4);
  border-radius: var(--r-pill);
  background: var(--surface-2);
  border: 1px solid var(--line-1);
}
.auth-lang-opt {
  border: 0;
  background: transparent;
  font-size: var(--text-3xs);
  color: var(--ds-color-text-placeholder);
  cursor: pointer;
  /* 批 18：热区提到 24px 高（原 29×21 / 22×21） */
  display: inline-flex;
  align-items: center;
  min-height: 24px;
  padding: 2px 6px;
  border-radius: var(--r-xs);
  transition: color var(--dur-fast), background-color var(--dur-fast);
}
.auth-lang-opt:hover {
  color: var(--ds-color-text-secondary);
  background: var(--ds-color-bg-hover);
}
.auth-lang-opt.is-active {
  color: var(--ds-color-text-primary);
  font-weight: 600;
}
.auth-lang-sep {
  width: 1px;
  height: 10px;
  margin: 0 4px;
  background: var(--line-1);
}

/* 卡片本体 */
.auth-card {
  padding: var(--ds-space-6) var(--ds-space-5);
  /* 批 94：原为 `14px` —— **整个半径刻度（4/8/10/12/16/胶囊）里没有这个值**，
     是全站唯一的 14px 圆角。登录卡也是「卡片」，收敛到 `--r-card`(10px)，
     与其余 9 处卡片一致。⚠️ 这是本批唯一的**可见变化**（卡片圆角 14px→10px）。 */
  border-radius: var(--r-card);
  background: var(--ds-color-bg-surface-card);
  backdrop-filter: blur(24px);
  -webkit-backdrop-filter: blur(24px);
  border: 1px solid var(--ds-color-border-default);
  box-shadow: var(--shadow-card);
}

/* 头部品牌 */
.auth-header {
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  margin-bottom: 24px;
}
.auth-logo-box {
  width: 44px;
  height: 44px;
  /* 批 94：10px 就是 `--r-card` 的值，改用令牌（渲染完全相同）。 */
  border-radius: var(--r-card);
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid rgba(255, 255, 255, 0.12);
  margin-bottom: 12px;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.4);
}
.auth-logo {
  width: 22px;
  height: 22px;
}
.auth-title {
  font-size: var(--text-xl);
  font-weight: 600;
  letter-spacing: -0.01em;
  color: var(--ds-color-text-primary);
  margin: 0;
}
.auth-subtitle {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: var(--text-xs);
  color: var(--ds-color-text-description);
  margin-top: var(--sp-2);
}
.auth-version-tag {
  font-size: var(--text-4xs);
  padding: var(--sp-hair) var(--sp-2);
  border-radius: var(--r-xs);
  background: var(--surface-2);
  color: var(--ds-color-text-placeholder);
}

/* 错误横幅 */
.auth-alert {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 12px;
  border-radius: var(--r-ctl);
  background: var(--down-bg);
  border: 1px solid var(--down-line);
  color: var(--down);
  font-size: var(--text-xs);
  margin-bottom: var(--ds-space-4);
}
.auth-alert-icon {
  flex-shrink: 0;
}

/* 表单主体 */
.auth-form {
  display: flex;
  flex-direction: column;
  gap: 16px;
}


.auth-label-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.auth-label {
  font-size: var(--text-2xs);
  font-weight: 500;
  color: var(--ds-color-text-secondary);
}

.auth-input {
  width: 100%;
  height: 38px;
  padding: 0 12px;
  border-radius: var(--r-ctl);
  background: var(--ds-color-bg-input);
  border: 1px solid var(--ds-color-border-input);
  color: var(--ds-color-text-primary);
  font-size: var(--text-xs);
  outline: none;
  transition: all var(--dur-fast) var(--ease-out);
}
.auth-input:focus {
  background: var(--ds-color-bg-input);
  border-color: var(--ds-color-border-input-focus);
  box-shadow: 0 0 0 3px rgba(16, 185, 129, 0.18);
}
.auth-input::placeholder {
  color: var(--ds-color-text-placeholder);
}

.auth-input-pwd-wrap {
  position: relative;
  display: flex;
  align-items: center;
}
/* 批 97：36px = 右侧 `.auth-eye-btn`（absolute right 6）+ 按钮宽 24 + 间隙 6
   —— 推导几何，刻意离格。实测按钮 24×24、距右 6。 */
.auth-input-pwd-wrap .auth-input {
  padding-right: 36px;
}
.auth-eye-btn {
  position: absolute;
  right: 6px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  padding: 0;
  border: 0;
  border-radius: var(--r-xs);
  background: transparent;
  color: var(--ds-color-text-placeholder);
  cursor: pointer;
  transition: color var(--dur-fast), background-color var(--dur-fast);
}
.auth-eye-btn:hover {
  color: var(--ds-color-text-primary);
  background-color: var(--ds-color-bg-hover);
}

/* 提交主按钮 */
.auth-submit-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  width: 100%;
  height: 40px;
  margin-top: 8px;
  border-radius: var(--r-ctl);
  background: var(--ds-btn-primary-bg);
  border: 1px solid var(--ds-btn-primary-bg);
  color: var(--ds-btn-primary-text);
  font-size: var(--text-xs);
  font-weight: 600;
  cursor: pointer;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.2), 0 4px 14px rgba(16, 185, 129, 0.2);
  transition: all var(--dur-fast) var(--ease-out);
}
.auth-submit-btn:hover:not(:disabled) {
  background: var(--ds-btn-primary-hover-bg);
  border-color: var(--ds-btn-primary-hover-bg);
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.3), 0 6px 20px rgba(16, 185, 129, 0.3);
  transform: translateY(-1px);
}
.auth-submit-btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
  box-shadow: none;
}

/* 底部防线说明 */
.auth-footer {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 20px;
  padding-top: var(--sp-6);
  border-top: 1px solid var(--line-1);
  font-size: var(--text-4xs);
  color: var(--ds-color-text-placeholder);
  line-height: 1.4;
}
.auth-shield {
  color: var(--ds-color-brand);
  flex-shrink: 0;
}

/* 下方微型状态条 */
.auth-meta-bar {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: var(--sp-3) var(--sp-7);
  border-radius: var(--r-pill);
  background: rgba(255, 255, 255, 0.035);
  border: 1px solid rgba(255, 255, 255, 0.06);
  font-size: var(--text-4xs);
  letter-spacing: 0.05em;
  color: var(--ds-color-text-description);
}
.auth-meta-dot {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: var(--up);
  box-shadow: 0 0 6px var(--up);
}

</style>
