import type { InjectionKey } from 'vue'
import { inject } from 'vue'
import type { useLlmConfig } from '../../../composables/useLlmConfig'

/** LlmPage 的状态与动作集合（就是 composable 的返回值） */
export type LlmCtx = ReturnType<typeof useLlmConfig>

/**
 * 为什么用 provide/inject 而不是 prop/emit：
 *
 * 拆分前 LlmPage.vue 是 1762 行。这些视图块共享几十个状态与动作绑定，
 * 若按 prop/emit 下传，父页要写 60+ 个绑定、子组件再声明 60+ 个 props ——换汤不换药。
 * provide/inject 保持**同一个状态对象**，拆分后子组件拿到的 ref 与父页是同一个，
 * 行为零变化。
 *
 * 也不在子组件里直接调 `useLlmConfig()`：composable 每次调用都会新建一份 ref，
 * 那样各视图块会各持一份互不相干的"配置状态"，看起来能跑、实际全错。
 * 故必须由父页 provide，子组件 inject —— `useLlmCtx()` 在缺提供者时**直接抛错**，
 * 而不是静默返回 undefined。
 */
export const LLM_KEY: InjectionKey<LlmCtx> = Symbol('astra.llmCtx')

export function useLlmCtx(): LlmCtx {
  const ctx = inject(LLM_KEY)
  if (!ctx) {
    throw new Error('useLlmCtx() 必须在 <LlmPage> 内使用：父页需 provide(LLM_KEY, useLlmConfig())')
  }
  return ctx
}
