/**
 * 状态指示点与动态脉冲标识无障碍规范守卫闸（批 57）。
 *
 * ## 守什么
 *
 * 1. **状态点语义明确性（WCAG 1.1.1 Non-text Content）**：
 *    全站所有状态指示圆点与脉冲点（如 `.dsh-status-dot`、`.pulse-dot`、`.ov-live-dot`、`.ov-pipe-dot`、`.ov-ar-dot`）：
 *    - 当作为文本伴生修饰时，必须声明 `aria-hidden="true"`，防止读屏器遇到空节点产生杂音；
 *    - 当独立作为状态指示器使用时（如 PromptStudio 当前激活方案指示点），必须显式声明 `:aria-label` 与 `:title`。
 *
 * 2. **PromptStudio 激活方案可访问性**：
 *    `PromptStudioPage.vue` 侧栏中的当前激活提示点必须声明可访问名（如 `admin.promptStudio.profiles.active`），
 *    确保视障用户可准确获知哪个方案处于生效状态。
 *
 * 运行：`node --test tests/*.test.mjs`
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import path from 'node:path';

const SRC = path.resolve(import.meta.dirname, '..', 'src');
const DOT_CLASS_RE = /(?:dsh-status-dot|pulse-dot|ov-live-dot|ov-pipe-dot|ov-ar-dot|auth-meta-dot|nf-card-dot)/;

function vueFiles(dir, out = []) {
  for (const n of readdirSync(dir)) {
    const p = path.join(dir, n);
    if (statSync(p).isDirectory()) vueFiles(p, out);
    else if (n.endsWith('.vue')) out.push(p);
  }
  return out;
}

const stripComments = (t) => t.replace(/<!--[\s\S]*?-->/g, '');

test('所有状态点与脉冲标识必须具备 aria-hidden 或 aria-label/title 语义', () => {
  const badDots = [];

  for (const file of vueFiles(SRC)) {
    const rel = path.relative(SRC, file);
    const text = stripComments(readFileSync(file, 'utf8'));
    const tm = text.match(/<template>([\s\S]*)<\/template>/);
    if (!tm) continue;
    const body = tm[1];

    for (const m of body.matchAll(/<([a-zA-Z][\w.-]*)\b([^>]*)>/g)) {
      const tag = m[1];
      const attrs = m[2];

      if (DOT_CLASS_RE.test(attrs)) {
        const isHidden = attrs.includes('aria-hidden="true"');
        const hasA11yName = attrs.includes('aria-label') || attrs.includes(':aria-label') || attrs.includes('title=') || attrs.includes(':title=');

        if (!isHidden && !hasA11yName) {
          const line = text.slice(0, tm.index).split('\n').length + body.slice(0, m.index).split('\n').length;
          badDots.push(`${rel}:${line} <${tag}> 状态点既无 aria-hidden 亦无 aria-label/title 描述`);
        }
      }
    }
  }

  assert.deepEqual(badDots, [], `发现未配置无障碍语义的状态指示点：\n  ${badDots.join('\n  ')}`);
});

test('闸自检：能准确拦截无语义状态点并放行合规状态点', () => {
  const badDot = '<span class="dsh-status-dot active" />';
  const goodDot1 = '<span class="dsh-status-dot active" aria-hidden="true" />';
  const goodDot2 = '<span class="dsh-status-dot active" :aria-label="activeText" :title="activeText" />';

  const isBad = (html) => {
    const m = html.match(/<span\b([^>]*)>/);
    if (!m) return false;
    const attrs = m[1];
    return DOT_CLASS_RE.test(attrs) && !attrs.includes('aria-hidden="true"') && !attrs.includes('aria-label') && !attrs.includes('title');
  };

  assert.equal(isBad(badDot), true, '应拦截裸状态点');
  assert.equal(isBad(goodDot1), false, '应放行 aria-hidden 修饰点');
  assert.equal(isBad(goodDot2), false, '应放行独立具名状态点');
});
