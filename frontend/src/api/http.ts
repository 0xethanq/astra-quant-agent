/**
 * 全局 HTTP 层 —— fetch 封装 + 会话头 + 错误归一
 * 迁移自旧 useApi()，行为保持：401 登出、FastAPI 422 detail 数组转中文提示。
 */
import { useAuthStore } from '../stores/auth';
import { useI18n } from '../composables/useI18n';

export class HttpError extends Error {
  status: number;
  constructor(message: string, status = 0) {
    super(message);
    this.name = 'HttpError';
    this.status = status;
  }
}

/**
 * 把 FastAPI 的 detail（字符串或 422 数组）归一为人话。
 *
 * 批 76：拼接串此前硬编码中文（`请求` / `：` / `；`），英文界面下会混进中文标点。
 * 这里做成**参数可注入**（默认取当前语言），既满足 i18n，也让纯函数可被测试直接调用。
 */
export function normalizeDetail(data: any, status: number, t?: (key: string) => string): string {
  const tr = t || useI18n().t;
  const detail = data?.detail ?? data?.message;
  if (Array.isArray(detail)) {
    const colon = tr('common.punct.colon');
    const sep = tr('common.punct.semicolon');
    return detail
      .map((x: any) => `${(x.loc || []).slice(1).join('.') || tr('common.requestFailed')}${colon}${x.msg}`)
      .join(sep);
  }
  if (typeof detail === 'string' && detail) return detail;
  return `HTTP ${status}`;
}

export async function http<T = any>(path: string, options: RequestInit = {}): Promise<T> {
  const auth = useAuthStore();
  let resp: Response;
  try {
    resp = await fetch(path, {
      ...options,
      headers: {
        'Content-Type': 'application/json',
        ...(auth.token ? { 'X-Astra-Session': auth.token } : {}),
        ...(options.headers || {}),
      },
    });
  } catch (e: any) {
    throw new HttpError(useI18n().t('common.networkRetry'), 0);
  }

  let data: any = null;
  try {
    data = await resp.json();
  } catch {
    /* 空响应体 */
  }

  if (resp.status === 401 && auth.token) {
    auth.logout();
    throw new HttpError(useI18n().t('common.sessionExpired'), 401);
  }
  if (!resp.ok) {
    throw new HttpError(normalizeDetail(data, resp.status), resp.status);
  }
  return data as T;
}

export const get = <T = any>(path: string) => http<T>(path);
export const post = <T = any>(path: string, body?: unknown) =>
  http<T>(path, { method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) });
export const put = <T = any>(path: string, body?: unknown) =>
  http<T>(path, { method: 'PUT', body: body === undefined ? undefined : JSON.stringify(body) });
export const patch = <T = any>(path: string, body?: unknown) =>
  http<T>(path, { method: 'PATCH', body: body === undefined ? undefined : JSON.stringify(body) });
export const del = <T = any>(path: string) => http<T>(path, { method: 'DELETE' });

