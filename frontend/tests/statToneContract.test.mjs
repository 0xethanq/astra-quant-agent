/**
 * KPI 副值的「色」必须跟随它实际展示的指标（批 83）。
 *
 * ## 背景：BaseStat 只有副值（delta）会被上色
 *
 * `BaseStat.vue` 的模板里，数值永远是中性色 `--ink-strong`，**只有** delta 走
 * `deltaTone`：
 *
 *     <span class="num … text-[var(--ink-strong)]">{{ value }}</span>
 *     <span v-if="delta" :style="{ color: toneVar[deltaTone] }">{{ delta }}</span>
 *
 * 于是有两类静默失效：
 *
 * ### ① 传了 `delta-tone` 却没有 `delta` → 色完全无效（死属性）
 *
 * 实测 3 处：`EvolutionView` 的胜率（意图"≥50 转绿"**从未生效**）、
 * `LedgerView` 的净额（意图"≥0 转绿"从未生效）、`LedgerView` 的手续费
 * （静态 `muted`，恰好等于默认值）。已删除 —— 数值保持全站中性是 BaseStat 的既定设计
 * （16 个使用点无一例外），给其中两个上色反而破坏一致性。
 *
 * ### ② `delta` 展示 A 指标，`delta-tone` 却由 B 指标决定 → 颜色误导
 *
 * 实测 1 处：`KpiRibbon` 的「今日已实现」——
 *
 *     :delta="`${todayTrades} 笔 · ${todayWinRate}%`"      ← 展示**胜率**
 *     :delta-tone="todayNet >= 0 ? 'up' : 'down'"          ← 却按**今日净盈亏**上色
 *
 * 后果：今日净亏 0.10 时，**67% 的健康胜率被涂成红色**；反之胜率 30% 也会因
 * 当日盈利而转绿。仓内**已有正确先例**：`EvolutionView.vue` 的 profit_factor /
 * win_rate 单元一律"tone 跟被展示的那个指标"（`win_rate >= 50 ? 'up' : 'down'`）。
 * 已改为 `todayWinRate === null ? 'muted' : todayWinRate >= 50 ? 'up' : 'down'`。
 *
 * 本闸把 11 个 `delta-tone` 使用点**逐一登记**（含每个的"色由谁决定"），
 * 新增或改动必须先在这里登记理由 —— 与 `.icon-box` / `.fact` 的清单式闸同构。
 *
 * 运行：`node --test tests/*.test.mjs`
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readdirSync, readFileSync, statSync } from 'node:fs';
import path from 'node:path';

const SRC = path.resolve(import.meta.dirname, '..', 'src');

/**
 * 所有 `delta-tone` 使用点的登记表。
 * 键 = `<相对路径>::<i18n label 键>`；值 = { tone, why }。
 * `tone` 必须是 tone 表达式里**确实出现**的标识符（用于校验"色由谁决定"）。
 */
export const TONE_INVENTORY = {
  'components/dashboard/KpiRibbon.vue::dash.matrix.kpi.todayPnl': {
    tone: 'todayWinRate',
    why: '副值展示"笔数 · 胜率"，故色由胜率决定（批 83 修：原先误按 todayNet 上色，会把健康胜率涂红）',
  },
  'components/dashboard/KpiRibbon.vue::dash.matrix.kpi.floatPnl': {
    tone: 'floatPnl',
    why: '副值是浮动 ROI%，与浮动盈亏同向，色由 floatPnl 决定',
  },
  'components/dashboard/KpiRibbon.vue::dash.matrix.kpi.margin': {
    tone: 'marginUsage',
    why: '副值是已用保证金，与保证金占用率同族，色由占用率分档决定',
  },
  'components/dashboard/KpiRibbon.vue::dash.matrix.kpi.oco': {
    tone: 'ocoCoverage',
    why: '副值是云端防线覆盖文案，色由覆盖率决定',
  },
  'views/dashboard/EvolutionView.vue::dash.evolution.hud.pf': {
    tone: 'profit_factor',
    why: '副值与色都由 profit_factor 决定',
  },
  'views/dashboard/LedgerView.vue::dash.ledger.summary.winRate': {
    tone: 'muted',
    why: '静态 muted：副值是"wins / 总数"，本身就是中性统计量，刻意不上色',
  },
  'views/dashboard/LedgerView.vue::dash.ledger.summary.fundingNet': {
    tone: 'fundingSum',
    why: '副值是资金费收支，色由净额方向决定',
  },
  'views/dashboard/LedgerView.vue::dash.ledger.summary.pf': {
    tone: 'muted',
    why: '静态 muted：副值说明利润因子的数据口径，非方向性指标',
  },
};

function vueFiles(dir, out = []) {
  for (const n of readdirSync(dir)) {
    const p = path.join(dir, n);
    if (statSync(p).isDirectory()) vueFiles(p, out);
    else if (n.endsWith('.vue')) out.push(p);
  }
  return out;
}

/** 提取 `<Name …>` 的属性文本；按引号配对跳到标签结束（否则会被 `>=` 里的 `>` 截断）。 */
export function tagBodies(tpl, name) {
  const out = [];
  for (const m of tpl.matchAll(new RegExp(`<${name}\\b`, 'g'))) {
    let i = m.index + m[0].length;
    let q = null;
    const start = i;
    while (i < tpl.length) {
      const ch = tpl[i];
      if (q) {
        if (ch === q) q = null;
      } else if (ch === '"' || ch === "'") q = ch;
      else if (ch === '>') {
        out.push(tpl.slice(start, i));
        break;
      }
      i += 1;
    }
  }
  return out;
}

const TPL = (t) => (t.includes('<style') ? t.slice(0, t.indexOf('<style')) : t);

function collect() {
  const sites = [];
  for (const f of vueFiles(SRC)) {
    const rel = path.relative(SRC, f);
    const tpl = TPL(readFileSync(f, 'utf8'));
    for (const body of tagBodies(tpl, 'BaseStat')) {
      const tone = /(?<!:)\bdelta-tone="([^"]*)"/.exec(body) || /:delta-tone="([^"]*)"/.exec(body);
      if (!tone) continue;
      const label = /:label="t\('([^']+)'\)"/.exec(body);
      sites.push({
        key: `${rel}::${label ? label[1] : '?'}`,
        tone: tone[1],
        hasDelta: /:delta="/.test(body),
        body,
      });
    }
  }
  return sites;
}

test('每个 delta-tone 使用点都必须在登记表里，且色由登记的指标决定', () => {
  const sites = collect();
  const seen = new Set();
  const problems = [];

  for (const s of sites) {
    const entry = TONE_INVENTORY[s.key];
    if (!entry) {
      problems.push(`未登记：${s.key}  tone=${s.tone}`);
      continue;
    }
    seen.add(s.key);
    // tone 表达式必须真的引用登记的那个指标
    const decl = entry.tone;
    if (decl === 'muted') {
      if (!/muted/.test(s.tone)) problems.push(`${s.key} 登记为 muted，但表达式是 ${s.tone}`);
    } else if (!s.tone.includes(decl)) {
      problems.push(`${s.key} 登记色由 ${decl} 决定，但表达式 ${s.tone} 没有引用它`);
    }
  }
  for (const k of Object.keys(TONE_INVENTORY)) {
    if (!seen.has(k)) problems.push(`登记表里的 ${k} 已不存在，请删除该条`);
  }
  assert.deepEqual(problems, [], `delta-tone 契约被破坏：\n  ${problems.join('\n  ')}`);
});

test('「今日已实现」的色必须由胜率决定，不得再由今日净盈亏决定（回归锚点）', () => {
  const sites = collect();
  const today = sites.find((s) => s.key === 'components/dashboard/KpiRibbon.vue::dash.matrix.kpi.todayPnl');
  assert.ok(today, '找不到「今日已实现」KPI 单元');
  // 副值展示的是胜率
  assert.match(today.body, /todayWinRate/, '副值应展示胜率');
  // 色必须跟胜率
  assert.match(today.tone, /todayWinRate/, '色应由胜率决定');
  // 不得再由当日净盈亏决定 —— 这正是批 83 修的误导（67% 胜率被涂红）
  assert.doesNotMatch(
    today.tone,
    /todayNet/,
    '色不该再由 todayNet 决定：副值展示胜率时按盈亏上色会把健康胜率涂红',
  );
});

test('delta-tone 必须伴随 delta —— 否则颜色完全不生效（死属性）', () => {
  const inert = collect().filter((s) => !s.hasDelta).map((s) => `${s.key}  tone=${s.tone}`);
  assert.deepEqual(
    inert,
    [],
    `以下 BaseStat 传了 delta-tone 却没有 delta（BaseStat 只给 delta 上色，该色永不渲染）：\n  ${inert.join('\n  ')}`,
  );
});

test('顶部权益不得同时使用 $ 前缀与 U 后缀（币种记号冗余）', () => {
  const src = readFileSync(path.join(SRC, 'components/dashboard/KpiRibbon.vue'), 'utf8');
  // 2026-10：顶部权益不再是"聚合多所"的字符串插值，改为 BaseStat 的 :value 绑定；
  // 判据保留原意 —— **不得用 `$` 前缀**，**必须带 ` U` 后缀**。
  assert.doesNotMatch(src, /\$\s*\{\{/, '顶部权益又出现 `$ {{ … }}`');
  assert.match(src, /\$\{fmtNum\(totalEquityNum\.value, 2\)\} U/, '顶部权益应保留后缀 ` U`');
});

test('useHotkeys 不得再有"两支相同"的三元，且须兜底 e.key', () => {
  // ⚠️ 必须先去掉注释：本次修复的**说明注释里就写着**那个坏签名，
  // 不去注释会自己把自己判红（此坑本会话已第 4 次遇到）。
  const src = readFileSync(path.join(SRC, 'composables/useHotkeys.ts'), 'utf8')
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/^[ \t]*\/\/.*$/gm, '');
  // 死代码签名：同一表达式写在 ? 与 : 两侧
  assert.doesNotMatch(
    src,
    /\?\s*([A-Za-z_$][\w.$]*\([^()?]*\))\s*:\s*\1/,
    'comboOf 里又出现两支完全相同的三元（压缩后只剩逗号表达式）',
  );
  // 必须对 e.key 缺失兜底：全局 keydown 处理器抛错会打断其它监听者
  assert.match(src, /\(e\.key \|\| ''\)\.toLowerCase\(\)/, 'e.key 缺少兜底，非常规事件会在全局处理器里抛错');
});

test('闸自检：属性提取不被 >= 截断、登记校验能识别偏移', () => {
  const tpl = `<BaseStat :value="x" :delta="a ? 'b' : c" :delta-tone="todayNet >= 0 ? 'up' : 'down'" :hint="t('h')" />`;
  const [body] = tagBodies(tpl, 'BaseStat');
  assert.match(body, /:hint=/, '属性提取被 >= 里的 > 截断了');
  assert.equal(/delta-tone="([^"]*)"/.exec(body)[1], "todayNet >= 0 ? 'up' : 'down'");
  // 登记校验：表达式不引用登记的指标 → 应判为问题
  const decl = 'todayWinRate';
  assert.equal("todayNet >= 0 ? 'up' : 'down'".includes(decl), false, '偏移应能被识破');
  // 无 delta 判定：该样例**含** :delta=，故应为 true
  assert.equal(/:delta="/.test(body), true, '样例含 :delta=，应判为有效色');
  const noDelta = tagBodies(`<BaseStat :value="x" :delta-tone="muted" />`, 'BaseStat')[0];
  assert.equal(/:delta="/.test(noDelta), false, '无 :delta= 的样例应判为死属性');
});
