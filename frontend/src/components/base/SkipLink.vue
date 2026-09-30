<script setup lang="ts">
/**
 * SkipLink.vue · "跳到主内容"（批 45）
 * ---------------------------------------------------------------------------
 * ## 为什么需要
 *
 * 两套外壳都有常驻侧边栏（前台 6 项 + 文档、后台 11 项）和顶栏动作组。
 * 键盘用户每翻一页都得先 Tab 穿过它们才能到正文 —— 页数越多、这个成本越荒唐。
 * WCAG 2.4.1（Bypass Blocks）要求的正是这种"跳过重复块"的机制。
 *
 * ## 为什么不用原生锚点跳转
 *
 * 外壳跑在 `createWebHistory` 下：`<a href="#main-content">` 会被 vue-router
 * 当成一次**路由跳转**（路径变成 `/`），在 `/factors`、`/admin/risk` 上点击会直接
 * 把用户送回首页 —— 比没有这个链接更糟。所以这里 `@click.prevent` 自己接管：
 * 聚焦目标并滚动到它，不动路由。
 *
 * 目标元素需要 `tabindex="-1"`（否则不可聚焦，焦点会留在链接上，读屏器也不会开始念正文）。
 */
import { useI18n } from '../../composables/useI18n';

const props = withDefaults(defineProps<{ target?: string }>(), { target: 'main-content' });

const { t } = useI18n();

function skip() {
  const el = document.getElementById(props.target);
  if (!el) return;
  el.focus({ preventScroll: true });
  el.scrollIntoView({ block: 'start' });
}
</script>

<template>
  <a class="skip-link" :href="`#${target}`" @click.prevent="skip">
    {{ t('common.skipToContent') }}
  </a>
</template>
