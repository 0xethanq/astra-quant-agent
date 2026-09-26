/**
 * `src/api/http.ts` 行为契约（结构优化阶段 4·B3 第五十四刀）。
 *
 * ⚠️ 前端此前**没有任何被执行的自动化测试**：`frontend/tests/` 只有两个 `.mjs`，
 * 无人运行；`package.json` 也没有 `test` 脚本。本文件补上 HTTP 层的行为验证，
 * 并由后端 `tests/test_frontend_http_single_source.py` 主动执行（见该文件的
 * `NodeBehaviourTest`），这样它不会再次变成"没人跑的测试"。
 *
 * 运行方式（Node ≥ 22.6，本仓为 v24）：
 *     node --experimental-strip-types tests/http.test.mjs
 *
 * 为什么需要 `--experimental-strip-types`：`http.ts` 是 TypeScript，
 * Node 24 能直接剥类型执行；但它的 `import ... from '../stores/auth'`
 * **没写扩展名**，Node 的 ESM 解析器不接受，故下面用 `module.registerHooks`
 * 给"相对且无扩展名"的 import 补 `.ts`。
 */
import { registerHooks } from 'node:module';
import { pathToFileURL, fileURLToPath } from 'node:url';
import path from 'node:path';
import fs from 'node:fs';

// ① 解析钩子：相对、无扩展名 → 补 .ts（并在存在时优先 .ts）
//
// 批 76：还必须处理**目录导入**。`src/locales/zh/index.ts` 里写的是 `./dash`，
// Vite 能解析成 `./dash/index.ts`，Node 的 ESM 解析器直接抛
// `ERR_UNSUPPORTED_DIR_IMPORT`。此前 `http.ts` 不依赖 i18n 所以碰不到；
// 一旦某模块（间接）依赖 i18n，任何加载它的 node 测试都会在**解析阶段**就挂掉 ——
// 补上目录 → `/index.ts` 这一档，比要求整个 locale 树改成显式 `/index` 更稳妥。
registerHooks({
  resolve(specifier, context, nextResolve) {
    if (specifier.startsWith('.') && !path.extname(specifier) && context.parentURL) {
      const base = path.dirname(fileURLToPath(context.parentURL));
      for (const ext of ['.ts', '.js']) {
        const cand = path.join(base, specifier + ext);
        if (fs.existsSync(cand)) {
          return { url: pathToFileURL(cand).href, shortCircuit: true };
        }
      }
      for (const ext of ['.ts', '.js']) {
        const cand = path.join(base, specifier, 'index' + ext);
        if (fs.existsSync(cand)) {
          return { url: pathToFileURL(cand).href, shortCircuit: true };
        }
      }
    }
    return nextResolve(specifier, context);
  },
});

// ② 把 `../stores/auth` 的 pinia store 换成受控替身。
//    做法：读源码，把 `import { useAuthStore } ...` 换成注入的全局桩。
const AUTH = 'src/stores/auth.ts';
const authPath = pathToFileURL(path.resolve(AUTH)).href;
const realAuth = fs.readFileSync(AUTH, 'utf8');
registerHooks({
  load(url, context, nextLoad) {
    if (url === authPath) {
      return {
        format: 'module',
        shortCircuit: true,
        source: `
          export const __authStub = { token: null, loggedOut: 0 };
          export function useAuthStore() {
            return {
              get token() { return __authStub.token },
              logout() { __authStub.loggedOut++ },
            };
          }
        `,
      };
    }
    return nextLoad(url, context);
  },
});

const { http, HttpError, normalizeDetail, get, post, del } =
  await import(pathToFileURL(path.resolve('src/api/http.ts')).href);
const { __authStub } = await import(authPath);

let pass = 0, fail = 0;
function check(name, cond, extra = '') {
  if (cond) { pass++; console.log('  ok   ' + name); }
  else { fail++; console.log('  FAIL ' + name + (extra ? '  → ' + extra : '')); }
}

function stubFetch(impl) { globalThis.fetch = impl; }

// ---------------- normalizeDetail ----------------
console.log('normalizeDetail:');
check('字符串 detail 原样', normalizeDetail({ detail: '出错了' }, 400) === '出错了');
check('422 数组转中文', normalizeDetail({ detail: [{ loc: ['body', 'x'], msg: '必填' }] }, 422)
      === 'x：必填');
check('无 detail 回落 HTTP 状态', normalizeDetail({}, 500) === 'HTTP 500');
check('message 兜底', normalizeDetail({ message: 'm' }, 400) === 'm');

// ---------------- http() 成功路径 ----------------
console.log('http() 成功路径:');
__authStub.token = 'tok-1';
stubFetch(async (url, opts) => {
  if (url === '/echo') {
    return new Response(new Headers([['content-type', 'application/json']]),
      { status: 200, headers: { 'content-type': 'application/json' } });
  }
  return new Response(JSON.stringify({ ok: 1 }), { status: 200 });
});
let captured = null;
stubFetch(async (url, opts) => {
  captured = { url, opts };
  return new Response(JSON.stringify({ ok: 1 }), { status: 200 });
});
const got = await http('/api/x');
check('返回解析后的 JSON', got && got.ok === 1, JSON.stringify(got));
check('带上会话头 X-Astra-Session', captured.opts.headers['X-Astra-Session'] === 'tok-1');
check('带上 Content-Type', captured.opts.headers['Content-Type'] === 'application/json');
check('默认无 method（GET）', captured.opts.method === undefined);

// ---------------- 401 登出 ----------------
console.log('http() 401:');
__authStub.token = 'tok-2'; __authStub.loggedOut = 0;
stubFetch(async () => new Response('{}', { status: 401 }));
let err = null;
try { await http('/api/y'); } catch (e) { err = e; }
check('抛 HttpError', err instanceof HttpError, String(err));
check('文案=会话已过期', err && err.message === '会话已过期，请重新登录', err && err.message);
check('status=401', err && err.status === 401);
check('触发了 logout()', __authStub.loggedOut === 1, String(__authStub.loggedOut));

// ---------------- 401 但无 token → 不登出，走普通错误 ----------------
console.log('http() 401 无 token:');
__authStub.token = null; __authStub.loggedOut = 0;
stubFetch(async () => new Response(JSON.stringify({ detail: '未授权' }), { status: 401 }));
err = null;
try { await http('/api/z'); } catch (e) { err = e; }
check('不触发 logout()', __authStub.loggedOut === 0);
check('走 detail 文案', err && err.message === '未授权', err && err.message);

// ---------------- 非 2xx 与 422 ----------------
console.log('http() 错误归一:');
stubFetch(async () => new Response(JSON.stringify({ detail: [{ loc: ['body', 'p'], msg: '非法' }] }), { status: 422 }));
err = null;
try { await http('/api/w'); } catch (e) { err = e; }
check('422 → HttpError', err instanceof HttpError);
check('422 文案= p：非法', err && err.message === 'p：非法', err && err.message);
check('422 status 保留', err && err.status === 422);

// ---------------- 网络层失败（本刀修的那条漂移） ----------------
console.log('http() 网络失败（旧 useApi 会漏出浏览器原文）:');
stubFetch(async () => { throw new TypeError('Failed to fetch'); });
err = null;
try { await http('/api/net'); } catch (e) { err = e; }
check('抛的是 HttpError 而非裸 TypeError', err instanceof HttpError, String(err));
check('文案=网络错误，请稍后重试', err && err.message === '网络错误，请稍后重试', err && err.message);
check('status=0', err && err.status === 0);

// ---------------- 空响应体 ----------------
console.log('http() 空响应体:');
stubFetch(async () => new Response('', { status: 200 }));
let empty = null, emptyErr = null;
try { empty = await http('/api/empty'); } catch (e) { emptyErr = e; }
check('不抛异常', emptyErr === null, String(emptyErr));
check('返回 null', empty === null, JSON.stringify(empty));

// ---------------- 动词助手 ----------------
console.log('动词助手:');
for (const [fn, method] of [[get, undefined], [post, 'POST'], [del, 'DELETE']]) {
  let m = 'unset';
  stubFetch(async (u, o) => { m = o.method; return new Response('{}', { status: 200 }); });
  await fn('/api/v', method === 'POST' ? { a: 1 } : undefined);
  check(`${fn.name || 'helper'} → method=${method}`, m === method, String(m));
}

// ---------------- 导入面 ----------------
console.log('导入面:');
const mod = await import(pathToFileURL(path.resolve('src/api/http.ts')).href);
check('不再导出 useHttp', !('useHttp' in mod));
check('导出 get/post/put/patch/del', ['get','post','put','patch','del'].every(k => k in mod));
check('导出 HttpError/normalizeDetail/http', ['HttpError','normalizeDetail','http'].every(k => k in mod));

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail === 0 ? 0 : 1);
