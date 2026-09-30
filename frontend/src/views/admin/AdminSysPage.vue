<script setup lang="ts">
/**
 * `embedded`（2026-09-30 后台精简）：本页被吸收为宿主页的一个页签时为真。
 * 宿主页负责大标题与页签标签，本页 PageHeader 降级为紧凑行（说明收起），
 * 但 #actions 里的按钮原样渲染 —— 被吸收页的按钮一个都不能丢。
 */
const props = withDefaults(defineProps<{ embedded?: boolean }>(), { embedded: false })
/**
 * AdminSysPage.vue · 管理员账号与权限工位
 * ---------------------------------------------------------------------------
 * 骨架（推倒重来）：
 *   旧 = 一张改密卡 + 一张账号 DataTable 卡（**6 处内联三元样式**）
 *        + **手写 fixed 遮罩新建弹窗** + 非超管的虚线占位块
 *        + 无骨架、无错误态、无空态
 *   新 = 共享 PageHeader（治理徽章 + 刷新）
 *        → **账号状态带**（账号总数 / 正常启用 / 已停用 / 已锁定）
 *        → **修改密码面板**（3 字段 + 会话说明）
 *        → **管理员账号行式清单**（账号 · 角色 · 状态 · 最近登录 · 操作）
 *        → **BaseDialog 新建管理员**
 *
 * 后端契约（逐字未改）：
 *   GET  /api/v1/admin/users                    → { users:[...], current_user_id }
 *   POST /api/v1/admin/users                     { username, password, role }
 *   PUT  /api/v1/admin/users/{id}/password       { current_password, new_password }
 *   PUT  /api/v1/admin/users/{id}/enabled        { enabled }
 *   POST /api/v1/admin/users/{id}/unlock         { confirmation: 'UNLOCK ADMIN {id}' }
 *
 * ⚠️ 权限门禁逐字保留：`load()` 对非超管**直接 return**（不请求）；列表与新建入口同样受 `isSuperadmin` 约束。
 * ⚠️ 输入校验逐字保留：新密码 ≥12 位；创建时账号名 ≥3 位且初始密码 ≥12 位。
 */
import { fmtDateTime } from '../../utils/format';
import { useToast } from '../../composables/useToast'
import { useConfirm } from '../../composables/useConfirm'
const toast = useToast()
const { ask } = useConfirm()
import { ref, computed, onMounted } from 'vue'
import PageHeader from '../../components/admin/PageHeader.vue'
import BaseDialog from '../../components/base/BaseDialog.vue'
import BaseEmpty from '../../components/base/BaseEmpty.vue'
import { useI18n } from '../../composables/useI18n'
const { t } = useI18n()
import { useApi } from '../../composables/useApi'
import { useAsyncAction } from '../../composables/useAsyncAction'
import { useAuthStore } from '../../stores/auth'
import { UserCog, KeyRound, Plus, Lock, Unlock, ShieldCheck, ShieldAlert,
  RefreshCw, Loader2, Users, UserCheck, UserX, AlertTriangle } from 'lucide-vue-next'

const { api } = useApi()
const auth = useAuthStore()

const users = ref<any[]>([])
/** 批 24：账号列表拉取失败的原因（页面上保留错误 + 重试，不再只靠 toast） */
const loadError = ref('')
const currentUserId = ref<number>(0)
// Password form
const pwdUserId = ref<number>(0)
const currentPassword = ref('')
const newPassword = ref('')
const changingPwd = ref(false)
const pwdReady = computed(() => !!currentPassword.value && newPassword.value.length >= 12)

// Create form
const createVisible = ref(false)
const newUsername = ref('')
const newRole = ref('admin')
const newPasswordForCreate = ref('')
const creating = ref(false)
const createError = ref('')
const createReady = computed(() => newUsername.value.trim().length >= 3 && newPasswordForCreate.value.length >= 12)

// F2：统一错误出口（error → toast，与原实现一致）。
// 批 71：原实现的 `loading` 是**死状态**（模板从不渲染，故此前只取 run）。
// 现在错误块的重试按钮真的需要忙碌态了 —— 不绑会让用户连点两次、
// 发出两个并发请求，且期间界面毫无反馈 —— 所以把 busy 取回来并绑到按钮上。
const { run: load, busy: loading } = useAsyncAction(async () => {
  if (!auth.isSuperadmin) return
  loadError.value = ''
  const res = await api<any>('/api/v1/admin/users')
  users.value = res.users || []
  currentUserId.value = res.current_user_id
  pwdUserId.value = res.current_user_id
}, { onError: (e) => { loadError.value = String(e?.message || e); toast.err(e.message) } })

async function changePassword() {
  if (newPassword.value.length < 12) {
    toast.err(t('admin.adminsys.msgs.pwdTooShort'))
    return
  }
  changingPwd.value = true
  try {
    await api(`/api/v1/admin/users/${pwdUserId.value}/password`, {
      method: 'PUT',
      body: JSON.stringify({ current_password: currentPassword.value, new_password: newPassword.value }),
    })
    toast.ok(t('admin.adminsys.msgs.pwdChanged'))
    currentPassword.value = ''
    newPassword.value = ''
  } catch (e: any) {
    toast.err(t('admin.adminsys.msgs.pwdFailed', undefined, { msg: e.message }))
  } finally {
    changingPwd.value = false
  }
}

async function createUser() {
  if (creating.value) return
  createError.value = ''
  if (newUsername.value.length < 3 || newPasswordForCreate.value.length < 12) {
    toast.err(t('admin.adminsys.msgs.createTooShort'))
    return
  }
  creating.value = true
  try {
    await api('/api/v1/admin/users', {
      method: 'POST',
      body: JSON.stringify({ username: newUsername.value, password: newPasswordForCreate.value, role: newRole.value }),
    })
    toast.ok(t('admin.adminsys.msgs.created', undefined, { name: newUsername.value }))
    createVisible.value = false
    newUsername.value = ''
    newPasswordForCreate.value = ''
    await load()
  } catch (e: any) {
    createError.value = e.message
    toast.err(t('admin.adminsys.msgs.createFailed', undefined, { msg: e.message }))
  } finally {
    creating.value = false
  }
}

async function toggleEnabled(u: any) {
  try {
    await api(`/api/v1/admin/users/${u.id}/enabled`, { method: 'PUT', body: JSON.stringify({ enabled: !u.enabled }) })
    await load()
  } catch (e: any) {
    toast.err(e.message)
  }
}

async function unlockUser(u: any) {
  // 批C(2026-09-13)：prompt() → 项目确认服务，短语逐字输入（对齐后端 `UNLOCK ADMIN {user_id}`）
  const _ok = await ask({
    title: t('admin.adminsys.msgs.unlockPrompt', undefined, { name: u.username, id: u.id }),
    danger: true,
    confirmPhrase: `UNLOCK ADMIN ${u.id}`,
    okText: t('common.unlock'),
  })
  if (!_ok) return
  try {
    await api(`/api/v1/admin/users/${u.id}/unlock`, { method: 'POST', body: JSON.stringify({ confirmation: `UNLOCK ADMIN ${u.id}` }) })
    toast.ok(t('admin.adminsys.msgs.unlocked', undefined, { name: u.username }))
    await load()
  } catch (e: any) {
    toast.err(e.message)
  }
}

/** 账号状态判定（与原实现的三元链逐字对应：locked_until → 已锁定；!enabled → 已停用；否则正常） */
function statusOf(u: any): { label: string; tone: string } {
  if (u.locked_until) return { label: t('admin.adminsys.users.statusLocked'), tone: 'badge-warn' }
  if (!u.enabled) return { label: t('admin.adminsys.users.statusDisabled'), tone: 'badge-down' }
  return { label: t('admin.adminsys.users.statusActive'), tone: 'badge-up' }
}

/** 账号状态带（4 项事实；非超管不展示，因为 `load()` 对非超管直接 return） */
const bandFacts = computed(() => [
  {
    icon: Users,
    label: t('admin.adminsys.bandTotal'),
    value: String(users.value.length),
    foot: auth.isSuperadmin ? auth.user?.username || '' : '',
    tone: '',
  },
  {
    icon: UserCheck,
    label: t('admin.adminsys.users.statusActive'),
    value: String(users.value.filter((u) => u.enabled && !u.locked_until).length),
    foot: '',
    tone: 'is-up',
  },
  {
    icon: UserX,
    label: t('admin.adminsys.users.statusDisabled'),
    value: String(users.value.filter((u) => !u.enabled).length),
    foot: '',
    tone: users.value.some((u) => !u.enabled) ? 'is-warn' : 'is-off',
  },
  {
    icon: Lock,
    label: t('admin.adminsys.users.statusLocked'),
    value: String(users.value.filter((u) => !!u.locked_until).length),
    foot: '',
    tone: users.value.some((u) => !!u.locked_until) ? 'is-warn' : 'is-off',
  },
])

function openCreate() {
  createError.value = ''
  createVisible.value = true
}

onMounted(load)
</script>

<template>
  <div class="as">
    <PageHeader :embedded="props.embedded" :title="t('admin.adminsys.title')">
      <template #actions>
        <span class="badge badge-accent mono">{{ t('admin.adminsys.governanceBadge') }}</span>
        <button type="button" class="btn btn-ghost btn-sm" :disabled="!auth.isSuperadmin" @click="load">
          <RefreshCw :size="14" />
          <span>{{ t('common.refresh') }}</span>
        </button>
      </template>
    </PageHeader>

    <!-- ══ 账号状态带（仅超管有意义） ══ -->
    <section v-if="auth.isSuperadmin" class="card band">
      <div v-for="f in bandFacts" :key="f.label" class="fact">
        <span class="fact-label"><component :is="f.icon" :size="12" />{{ f.label }}</span>
        <span class="fact-value" :class="f.tone">{{ f.value }}</span>
        <span class="fact-foot truncate">{{ f.foot }}</span>
      </div>
    </section>

    <!-- ══ 修改密码 ══ -->
    <section class="card">
      <header class="card-head">
        <div>
          <h2 class="card-title"><KeyRound :size="14" />{{ t('admin.adminsys.password.title') }}</h2>
          <p class="card-sub">
            {{ t('admin.adminsys.password.currentAccount', undefined, { name: auth.user?.username || '--' }) }}
          </p>
        </div>
      </header>

      <div class="as-pwd">
        <label class="field-stack">
          <span class="form-label">{{ t('admin.adminsys.password.currentPassword') }}</span>
          <input v-model="currentPassword" type="password" autocomplete="current-password" class="field" />
        </label>

        <label class="field-stack">
          <span class="form-label">{{ t('admin.adminsys.password.newPassword') }}</span>
          <input
            v-model="newPassword"
            type="password"
            autocomplete="new-password"
            class="field"
            :class="{ 'is-bad': !!newPassword && newPassword.length < 12 }"
            :aria-invalid="!!newPassword && newPassword.length < 12 ? 'true' : undefined"
            :placeholder="t('admin.adminsys.msgs.pwdTooShort')"
          />
        </label>

        <div class="as-pwd-submit">
          <button type="button" class="btn btn-primary btn-sm" :disabled="changingPwd || !pwdReady" @click="changePassword">
            <Loader2 v-if="changingPwd" :size="13" class="animate-spin shrink-0" />
            <KeyRound v-else :size="13" />
            <span>{{ changingPwd ? t('admin.adminsys.password.updating') : t('admin.adminsys.password.submit') }}</span>
          </button>
        </div>
      </div>

      <p v-if="auth.isSuperadmin" class="as-hint">{{ t('admin.adminsys.password.superadminHint') }}</p>
    </section>

    <!-- ══ 管理员账号 ══ -->
    <section class="card">
      <header class="card-head">
        <h2 class="card-title"><UserCog :size="14" />{{ t('admin.adminsys.users.title') }}</h2>
        <span v-if="auth.isSuperadmin" class="badge mono">{{ users.length }}</span>
        <button type="button" v-if="auth.isSuperadmin" class="btn btn-primary btn-sm" @click="openCreate">
          <Plus :size="14" />
          <span>{{ t('admin.adminsys.users.create') }}</span>
        </button>
      </header>

      <!-- 非超管：无权限视图 -->
      <BaseEmpty v-if="!auth.isSuperadmin" :text="t('admin.adminsys.users.superadminOnly')" :icon="ShieldAlert" />

      <!-- 批 24：取账号列表失败时，此前只弹一个转瞬即逝的 toast，
           users 保持 []，于是页面显示「暂无管理员账号」——把**接口故障**说成**没有账号**，
           超管回到这个页面会以为账号被清空了，且没有重试入口。 -->
      <div v-else-if="loadError" role="alert" class="state-block is-error">
        <span class="state-icon"><AlertTriangle :size="17" /></span>
        <p class="state-title">{{ t('common.loadFailed') }}</p>
        <p class="state-desc">{{ loadError }}</p>
        <button type="button" class="btn btn-ghost btn-sm mt-1" :disabled="loading" @click="load">
          <Loader2 v-if="loading" :size="14" class="animate-spin shrink-0" />
          <RefreshCw v-else :size="14" />
          <span>{{ t('common.retry') }}</span>
        </button>
      </div>

      <BaseEmpty v-else-if="!users.length" :text="t('admin.adminsys.noUsers')" />

      <div v-else class="as-rows">
        <div class="as-row as-row-head">
          <span>{{ t('admin.adminsys.users.colAccount') }}</span>
          <span>{{ t('admin.adminsys.users.colRole') }}</span>
          <span>{{ t('admin.adminsys.users.colStatus') }}</span>
          <span>{{ t('admin.adminsys.users.colLastLogin') }}</span>
          <span class="as-right">{{ t('admin.adminsys.users.colActions') }}</span>
        </div>

        <article v-for="u in users" :key="u.id" class="as-row" :class="{ 'is-off': !u.enabled }">
          <span class="as-account">
            <b class="as-name">{{ u.username }}</b>
            <span v-if="u.id === currentUserId" class="badge badge-accent">
              {{ t('admin.adminsys.users.currentSession') }}
            </span>
          </span>

          <span class="as-role">
            <span class="badge" :class="u.role === 'superadmin' ? 'badge-accent' : ''">
              <ShieldCheck v-if="u.role === 'superadmin'" :size="11" />
              {{ u.role === 'superadmin' ? t('admin.adminsys.users.roleSuperadmin') : t('admin.adminsys.users.roleAdmin') }}
            </span>
          </span>

          <span class="as-status">
            <span class="badge" :class="statusOf(u).tone">{{ statusOf(u).label }}</span>
          </span>

          <span class="as-login mono num">
            {{ u.last_login ? fmtDateTime(u.last_login) : t('admin.adminsys.users.neverLoggedIn') }}
          </span>

          <span class="as-actions">
            <button type="button"
              v-if="u.id !== currentUserId"
              class="btn btn-ghost btn-sm"
              @click="toggleEnabled(u)"
            >
              <component :is="u.enabled ? Lock : Unlock" :size="12" />
              <span>{{ u.enabled ? t('admin.adminsys.users.disable') : t('admin.adminsys.users.enable') }}</span>
            </button>

            <button type="button"
              v-if="u.locked_until"
              class="btn btn-quiet btn-sm is-warn"
              @click="unlockUser(u)"
            >
              <Unlock :size="12" />
              <span>{{ t('admin.adminsys.users.unlock') }}</span>
            </button>
          </span>
        </article>
      </div>
    </section>

    <!-- ══ 新建管理员 ══ -->
    <BaseDialog
      :open="createVisible"
      :title="t('admin.adminsys.users.create')"
      size="md"
      @close="createVisible = false"
    >
      <div v-if="createError" class="as-dlg-error" role="alert">
        <ShieldAlert :size="13" />
        <span>{{ createError }}</span>
      </div>

      <form id="as-create-form" class="as-create" @submit.prevent="createUser">
        <label class="field-stack">
          <span class="form-label">{{ t('admin.adminsys.create.account') }}</span>
          <input
            v-model="newUsername"
            type="text"
            class="field mono"
            :class="{ 'is-bad': !!newUsername && newUsername.trim().length < 3 }"
            :aria-invalid="!!newUsername && newUsername.trim().length < 3 ? 'true' : undefined"
            autocomplete="off"
            placeholder="admin"
          />
        </label>

        <label class="field-stack">
          <span class="form-label">{{ t('admin.adminsys.create.role') }}</span>
          <select v-model="newRole" class="field" :aria-label="t('admin.adminsys.create.role')">
            <option value="admin">{{ t('admin.adminsys.create.roleAdmin') }}</option>
            <option value="superadmin">{{ t('admin.adminsys.create.roleSuperadmin') }}</option>
          </select>
        </label>

        <label class="field-stack">
          <span class="form-label">{{ t('admin.adminsys.create.password') }}</span>
          <input
            v-model="newPasswordForCreate"
            type="password"
            autocomplete="new-password"
            class="field"
            :class="{ 'is-bad': !!newPasswordForCreate && newPasswordForCreate.length < 12 }"
            :aria-invalid="!!newPasswordForCreate && newPasswordForCreate.length < 12 ? 'true' : undefined"
            :placeholder="t('admin.adminsys.msgs.pwdTooShort')"
          />
        </label>
      </form>

      <template #footer>
        <button type="button" class="btn btn-ghost btn-sm" @click="createVisible = false">
          {{ t('admin.adminsys.create.cancel') }}
        </button>
        <!-- 批 115：表单已挂 @submit.prevent="createUser"，type="submit" 按钮无需再挂 @click，避免单次点击触发两次创建请求 -->
        <button class="btn btn-primary btn-sm" type="submit" form="as-create-form" :disabled="creating || !createReady">
          <Loader2 v-if="creating" :size="13" class="animate-spin shrink-0" />
          <Plus v-else :size="13" />
          <span>{{ t('admin.adminsys.create.submit') }}</span>
        </button>
      </template>
    </BaseDialog>
  </div>
</template>

<style scoped>
.as {
  display: flex;
  flex-direction: column;
  gap: var(--ds-space-4);
}

/* ══ 状态带 ══ */










/* ══ 改密 ══ */
.as-pwd {
  display: grid;
  grid-template-columns: 1fr;
  gap: var(--ds-space-3);
  align-items: end;
  padding: var(--ds-space-4);
}
@media (min-width: 900px) {
  .as-pwd {
    grid-template-columns: minmax(0, 1fr) minmax(0, 1fr) auto;
  }
}

.as-pwd-submit {
  display: flex;
  padding-bottom: 1px;
}
.as-hint {
  padding: var(--ds-space-3) var(--ds-space-4);
  border-top: 1px solid var(--ds-color-border-default);
  font-size: var(--text-4xs);
  line-height: var(--leading-body);
  color: var(--ds-color-text-placeholder);
}

/* ══ 账号清单 ══ */
.as-rows {
  display: flex;
  flex-direction: column;
}
.as-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 150px 110px minmax(0, 1fr) auto;
  align-items: center;
  gap: var(--ds-space-3);
  padding:12px var(--ds-space-4);
  border-bottom: 1px solid var(--ds-color-border-default);
  transition: background-color var(--dur-fast);
}
.as-row:last-child {
  border-bottom: 0;
}
.as-row:not(.as-row-head):hover {
  background-color: var(--ds-color-bg-hover);
}
.as-row.is-off {
  opacity: 0.62;
}
.as-row-head {
  min-height: 30px;
  padding-top: 0;
  padding-bottom: 0;
  background-color: var(--ds-color-bg-surface-inset);
  font-size: var(--text-3xs);
  font-weight: 500;
  letter-spacing: var(--track-label);
  text-transform: uppercase;
  color: var(--ds-color-text-placeholder);
}
.as-account {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  min-width: 0;
}
.as-name {
  font-size: var(--text-xs);
  font-weight: 600;
  color: var(--ds-color-text-primary);
}
.as-role,
.as-status {
  display: flex;
  min-width: 0;
}
.as-login {
  font-size: var(--text-4xs);
  color: var(--ds-color-text-placeholder);
}
.as-actions {
  display: flex;
  align-items: center;
  gap: var(--ds-space-2);
  justify-content: flex-end;
  flex-shrink: 0;
}
.as-right {
  text-align: right;
}

@media (max-width: 1000px) {
  .as-row {
    grid-template-columns: minmax(0, 1fr) auto;
  }
  .as-row-head {
    display: none;
  }
  .as-role,
  .as-status,
  .as-login {
    grid-column: 1;
  }
  .as-actions {
    grid-column: 2;
    grid-row: 1 / span 3;
  }
}

/* ══ 新建弹窗 ══ */
.as-create {
  display: flex;
  flex-direction: column;
  gap: var(--ds-space-4);
}
.as-dlg-error {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  margin-bottom: var(--ds-space-3);
  padding: 8px 10px;
  border-radius: var(--r-ctl);
  background-color: var(--down-bg);
  color: var(--down);
  font-size: var(--text-3xs);
  overflow-wrap: anywhere;
}
.as-dlg-error > svg {
  flex-shrink: 0;
  margin-top: 1px;
}
</style>
