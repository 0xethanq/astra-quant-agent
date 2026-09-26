/**
 * `useApi()` —— 后台页面的统一取数入口（结构优化阶段 4·B3 第五十四刀）。
 *
 * ## 本刀改了什么
 *
 * 原先本文件**内联复刻**了 `src/api/http.ts` 里的整个 fetch 流程
 * （拼 `X-Astra-Session` 会话头 → 解析响应 → 401 登出 → FastAPI `detail` 归一）。
 * 两者是同一段逻辑的两份拷贝，且**已经漂移**：
 *
 * | 行为 | `api/http.ts` | 旧 `useApi` |
 * |---|---|---|
 * | 网络层失败（DNS/断网/CORS） | `HttpError('网络错误，请稍后重试', 0)` | **原样抛出** `TypeError: Failed to fetch` 之类浏览器原文 |
 * | 错误类型 | `HttpError`（带 `status`） | 裸 `Error` |
 *
 * 网络失败那条会影响**所有后台页面**的报错文案 —— 用户看到的是浏览器英文原文。
 * 现改为**委托** `http.ts` 的 `http()`，删除本地复刻（47 → 61 行，其中 34 行是文档）。
 *
 * ## ⚠️ 为什么委托而不是反过来
 *
 * `useResource.ts` 的注释已经解释过：`useApi()` 的 `loading`/`error` 是
 * **该实例共享**的，多请求会互相覆盖，所以各页才要自己再写一份。
 * 也就是说这两个 ref **在设计上就不该被消费** —— 实测也确认：
 * 全仓 20 处调用**无一例外**都是 `const { api } = useApi()`，
 * **没有任何地方解构或读取 `loading` / `error`**。
 *
 * 故本刀只统一"真正在被使用的那部分"（`api`），
 * 并把 `loading` / `error` 标注为**兼容保留、勿用**。
 *
 * ## ⚠️ 界面契约（本刀刻意保持不变）
 *
 * 委托后抛出的异常从裸 `Error` 变成 `HttpError`——但 `HttpError extends Error`，
 * 且非网络失败的 `message` 文案**逐字相同**（401 为「会话已过期，请重新登录」，
 * 其余为 `normalizeDetail(...)` 的产出 —— 与旧实现的内联归一逻辑等价）。
 * 各页都是 `catch (e) { toast(e.message) }` 形态，故这些路径**零行为变化**；
 * 唯一实质差异是上表里的"网络失败文案"，而那正是本次要修的漂移。
 */
import { ref } from 'vue'
import { http } from '../api/http'

export function useApi() {
  // ⚠️ 兼容保留：`http.ts` 不维护这个实例级的 loading 态，
  //    而 `useResource` 的注释已说明它**按设计不可消费**（多请求互相覆盖）。
  //    全仓实测无消费方。**新代码请用 `useResource`。**
  const loading = ref(false)
  const error = ref<string | null>(null)

  async function api<T = any>(path: string, options: RequestInit = {}): Promise<T> {
    loading.value = true
    error.value = null
    try {
      return await http<T>(path, options)
    } catch (e: any) {
      error.value = e?.message || String(e)
      throw e
    } finally {
      loading.value = false
    }
  }

  return { loading, error, api }
}
