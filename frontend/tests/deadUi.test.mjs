/**
 * 「不可能出现的界面」守卫闸（批 107）。
 *
 * ## 判据
 *
 * 一个 `ref`（或其它同形态的响应式开关）如果：
 *
 *   1. **初值是假值**（`null` / `false` / `''` / `0` / `undefined`），
 *   2. 全文件里**所有赋值都还是假值**（包括模板里的 `@click="x = null"` 与 `x.value = null`），
 *   3. 却被 `v-if="x"` 当作**布尔开关**，
 *
 * 那么这段模板**永远不会渲染** —— 它是「建好了但到不了」的死界面。
 * 这类代码不会报错、不会影响测试、视觉上也看不出来，
 * 只能靠静态判据抓（批 106 之前一直是靠人肉读代码发现的）。
 *
 * ## 这一闸是怎么建起来的（两次仪器 bug，别再写回去）
 *
 * - 第一版只匹配 `x.value = rhs`，于是**模板风格**的
 *   `@click="open = !open"`（不带 `.value`）全部漏掉 → 一次报了 13 处，
 *   其中 `SettingsPopover.open`、`ChartWorkstation.isFullscreen` 等
 *   **都是能正常打开的**，全是假阳性。
 * - 第二版改成只匹配 `x = rhs`，于是**脚本风格**的 `x.value = rhs` 全部漏掉
 *   → 一次报了 51 处（`loadError`、`loading`、`status`…… 全是真在赋值的）。
 * - 第三版两种风格都覆盖后，全仓**恰好 1 处**真阳性，且与手工核对一致。
 *
 * ⚠️ 还有第三个坑：把**声明自身**也算成赋值。
 * `const zoomImage = ref<string | null>(null)` 会被 `x = rhs` 匹配到，
 * 右侧 `ref<...>(null)` 不是字面假值 → 真阳性被误判成「有真值赋值」而漏掉。
 * 所以必须记录声明区间并排除，同时排除右侧以 `ref(`/`computed(`/`shallowRef(`/`reactive(` 开头的命中。
 *
 * ## 已知且**接受**的一项（不是待修 bug）
 *
 * `DocsView.vue` 的 `zoomImage`（文档正文图片放大弹层）：文档正文是**硬编码的
 * `sections` 数组**，全篇没有 `<img>`（批 107 实测：`src/views/docs/` 下无
 * `v-html`、除该弹层自身外无图片），所以这个弹层**打不开**。
 * 它的关闭/焦点管理都是齐的，留着是为了将来正文能放图时直接可用 ——
 * **属于产品决定，不由本闸擅自删除**。若将来接通（正文加图 + 点击赋
 * `zoomImage`），把下面 `KNOWN_DEAD_UI` 里这一条删掉即可；本闸会因「豁免空转」而提醒。
 *
 * 运行：`node --test tests/*.test.mjs`
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import path from 'node:path';

const SRC = path.resolve(import.meta.dirname, '..', 'src');

const FALSY = /^(null|undefined|false|''|""|``|0)$/;
const DECL = /\bconst\s+(\w+)\s*=\s*ref\s*(?:<[^>]*>)?\s*\(\s*([^)]*?)\s*\)/gs;

/**
 * 归一化赋值右侧：去掉尾部的 `}`/`)`/`,`/空白。
 * ⚠️ 不归一化会把 `function f() { x = null }` 的右侧读成 `null }`，
 * 于是「假值赋值」被当成真值 → 真阳性漏掉（自检 ① 当场抓到的就是这个）。
 */
const normRhs = (r) => r.trim().replace(/[\s})]+$/g, '');

/** 右侧里出现 `||`/`&&`/`?`/`??` 时保守当成「可能为真」，宁可漏判也不误报。 */
const mayBeTruthy = (r) => /[|&?]/.test(r);

/** 收集 .vue 源文件（递归，跳过 node_modules 之类不可能出现的目录）。 */
function vueFiles(dir, out = []) {
  for (const n of readdirSync(dir)) {
    const p = path.join(dir, n);
    if (statSync(p).isDirectory()) vueFiles(p, out);
    else if (n.endsWith('.vue')) out.push(p);
  }
  return out;
}

/**
 * 扫描一份源码，返回「只可能为假、却被 v-if 当开关」的 ref 名。
 * 导出是为了让本文件底部的**判据自检**能用合成代码验证它真的会红 / 真的会绿。
 */
export function scanDeadSwitches(source, { selfName = '(合成)' } = {}) {
  const found = [];
  for (const m of source.matchAll(DECL)) {
    const name = m[1];
    const init = m[2].trim();
    if (!FALSY.test(init)) continue;

    const declStart = m.index;
    const declEnd = m.index + m[0].length;
    const assigns = [];

    // ① 脚本风格：NAME.value = rhs
    for (const a of source.matchAll(new RegExp('\\b' + name + '\\.value\\s*=(?!=)\\s*([^\\n;]*)', 'g'))) {
      assigns.push(a[1]);
    }
    // ② 模板风格：NAME = rhs（排除声明自身、排除 x.NAME 与比较运算符）
    for (const a of source.matchAll(new RegExp('(?<![\\w.=!<>])' + name + '\\s*=(?!=)\\s*([^\\n;"]*)', 'g'))) {
      if (a.index >= declStart && a.index <= declEnd) continue;
      const rhs = normRhs(a[1]);
      if (/^(ref|computed|shallowRef|reactive)\s*[(<]/.test(rhs)) continue;
      assigns.push(rhs);
    }
    // ③ 双向绑定：用户输入可以把它变成真值
    if (new RegExp('v-model(?::[\\w.]+)?="' + name + '"').test(source)) assigns.push('(v-model)');

    if (assigns.some((a) => !FALSY.test(normRhs(a)) || mayBeTruthy(normRhs(a)))) continue;

    // 只关心「当布尔闸」的用法：带 === / !== 的是取值比较，不算开关
    const gates = [...source.matchAll(/v-if="([^"]*)"/g)]
      .map((g) => g[1])
      .filter((g) => new RegExp('\\b' + name + '\\b').test(g) && !g.includes('===') && !g.includes('!=='));
    if (gates.length) found.push({ file: selfName, name, gates: gates.slice(0, 2) });
  }
  return found;
}

/** 全仓扫描。 */
function scanRepo() {
  const out = [];
  for (const f of vueFiles(SRC)) {
    const rel = path.relative(path.resolve(SRC, '..'), f).split(path.sep).join('/');
    out.push(...scanDeadSwitches(readFileSync(f, 'utf8'), { selfName: rel }));
  }
  return out;
}

/**
 * 已知死 UI 豁免表：空（DocsView.vue 已接入 /images/v920_*.png 点击放大灯箱）。
 */
const KNOWN_DEAD_UI = [];

test('不得存在「永远不会渲染」的界面开关（批 107 新增）', () => {
  const found = scanRepo().map((h) => `${h.file}: ${h.name}`);
  const unexpected = found.filter((f) => !KNOWN_DEAD_UI.includes(f));
  assert.deepEqual(
    unexpected,
    [],
    '这些 ref 初值为假、且所有赋值都还是假值，却被 v-if 当开关 —— 对应模板永远不会渲染：\n  ' +
      unexpected.join('\n  ') +
      '\n要么把它接通（给它一个真值来源），要么删掉那段死模板。',
  );
});

test('已知死界面的登记不得空转（接通/删除后必须同步删掉登记）', () => {
  const found = new Set(scanRepo().map((h) => `${h.file}: ${h.name}`));
  const stale = KNOWN_DEAD_UI.filter((k) => !found.has(k));
  assert.deepEqual(
    stale,
    [],
    '这些登记项已经不再是死界面了（被接通或删除），请从 KNOWN_DEAD_UI 里删掉：\n  ' + stale.join('\n  '),
  );
});

test('判据自检：两种赋值风格都要认，声明自身不能被当成赋值', () => {
  // ① 真·死界面：初值 null，只被赋 null（两种风格各一次）
  const dead = `
    const panel = ref<string | null>(null)
    function close() { panel.value = null }
    function close2() { panel = null }
  ` + '<div v-if="panel">内容</div>';
  assert.deepEqual(
    scanDeadSwitches(dead).map((h) => h.name),
    ['panel'],
    '真正的死界面没被认出来',
  );

  // ② 声明自身不得被误当赋值（曾经因此漏判）
  const declOnly = `
    const only = ref<Foo | null>(null)
  ` + '<div v-if="only">x</div>';
  assert.deepEqual(scanDeadSwitches(declOnly).map((h) => h.name), ['only'], '声明自身被误当成赋值了');

  // ③ 模板风格赋值（不带 .value）也要能识别为「有真值」
  const templateAssign = `
    const open = ref(false)
  ` + '<button @click="open = !open">x</button><div v-if="open">y</div>';
  assert.deepEqual(scanDeadSwitches(templateAssign), [], '模板风格赋值没被认出来（会造成假阳性）');

  // ④ 脚本风格赋真值
  const scriptAssign = `
    const err = ref('')
    function f(e) { err.value = e.message }
  ` + '<div v-if="err">y</div>';
  assert.deepEqual(scanDeadSwitches(scriptAssign), [], '脚本风格赋值没被认出来（会造成假阳性）');

  // ⑤ v-model 双向绑定不算死
  const modeled = `
    const q = ref('')
  ` + '<input v-model="q"><div v-if="q">z</div>';
  assert.deepEqual(scanDeadSwitches(modeled), [], 'v-model 双向绑定被误判成死界面');

  // ⑥ 取值比较不算布尔开关
  const compared = `
    const v = ref('')
  ` + '<div v-if="v !== \'\'">z</div>';
  assert.deepEqual(scanDeadSwitches(compared), [], '把取值比较当成了布尔闸');
});
