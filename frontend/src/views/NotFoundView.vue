<script setup lang="ts">
/**
 * NotFoundView.vue · 404 兜底页（批 45）
 * ---------------------------------------------------------------------------
 * ## 为什么必须存在
 *
 * 路由表此前**没有 catch-all**，所以任何拼错的地址都渲染出**一整页空白**：
 * 实测 `/admin/nope-does-not-exist` → `document.body.innerText` 长度 **0**、
 * 一个标题都没有、没有任何回退入口。用户唯一的出路是自己改地址栏。
 *
 * ## 为什么不复用某个布局
 *
 * 404 可能落在任何路径下（`/admin/...`、`/whatever`），挂 AdminLayout 会触发鉴权跳转、
 * 挂 DashboardLayout 会把 404 当成一个"页签"，都不对。故本页自成一屏，
 * 但仍使用设计系统语汇（`.dsh-card` / `.state-block` / `.btn`），观感与全站一致。
 *
 * 页面本身是 `noindex` —— 404 不该被搜索引擎收录（SEO 细节）。
 */
import { computed, onMounted } from 'vue';
import { useRoute } from 'vue-router';
import { Compass } from 'lucide-vue-next';
import { useI18n } from '../composables/useI18n';

const route = useRoute();
const { t } = useI18n();

/** 只展示路径本身，不把 query/hash 也糊上去（避免超长串撑破卡片） */
const shownPath = computed(() => route.path);

onMounted(() => {
  let tag = document.querySelector<HTMLMetaElement>('meta[name="robots"]');
  if (!tag) {
    tag = document.createElement('meta');
    tag.name = 'robots';
    document.head.appendChild(tag);
  }
  tag.content = 'noindex, follow';
});
</script>

<template>
  <main class="nf-wrap">
    <div class="dsh-card nf-card">
      <div class="state-block nf-state">
        <span class="state-icon">
          <Compass :size="18" />
        </span>
        <h1 class="state-title">{{ t('common.notFound.title') }}</h1>
        <p class="state-desc">
          {{ t('common.notFound.desc', undefined, { path: shownPath }) }}
        </p>
        <div class="state-action nf-actions">
          <RouterLink class="btn btn-primary" to="/">
            {{ t('common.notFound.home') }}
          </RouterLink>
          <RouterLink class="btn btn-quiet" to="/docs">
            {{ t('common.notFound.docs') }}
          </RouterLink>
        </div>
      </div>
    </div>
  </main>
</template>

<style scoped>
.nf-wrap {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: var(--ds-space-4);
  background-color: var(--ds-color-bg-page);
}

.nf-card {
  width: 100%;
  max-width: 460px;
}

.nf-state {
  gap: var(--ds-space-3);
}

.nf-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: center;
  gap: var(--ds-space-2);
}
</style>
