/**
 * `src/views/admin/securityLogic.ts::deriveMxHealthChips` 行为契约（2026-09-30）。
 *
 * ## 背景（真机事故）
 *
 * 「OKX 行情健康容灾」卡片显示 `9/9 币`全绿，而标的池只有 8 个（后收敛为 6 个）——
 * 名单来自 `data/venue_health.json`，而写这份名单的 `scripts/brain/xvenue.py` 已在
 * 「OKX 专用化」提交里删除 ⇒ 名单冻结（含早已移出池的 UNI），两个路由只把
 * `avg_ms/testnet/updated_utc` 叠写在旧 blob 上，于是"看着新鲜、名单是上个月的"。
 *
 * 修复后的契约（本文件逐条钉住）：
 *   1. `total` 取后端给的**池容量**（`v.total`），不再由 `ok/failed` 长度推算；
 *      后端没给（旧响应）才回落到 `ok + failed`；
 *   2. `unknown`（快照缺失/过期而未核实）必须透出，且 `allOk` 在 `unknown > 0` 时**恒假**
 *      —— 读不到 ≠ 就绪，界面不得把未知渲染成绿；
 *   3. `failed` 兼容旧形状（对象键数）与新形状（数组长度）；
 *   4. 缺 `health.venues` → `null`（"没有数据"与"没有失败"必须可区分）。
 *
 * ## 运行
 *     node --test tests/securityHealthChips.test.mjs
 */
import { pathToFileURL } from 'node:url';
import path from 'node:path';

const M = await import(
  pathToFileURL(path.resolve('src/views/admin/securityLogic.ts')).href
);

let pass = 0, fail = 0;
function check(name, cond, extra = '') {
  if (cond) { pass++; console.log('  ok   ' + name); }
  else { fail++; console.log('  FAIL ' + name + (extra ? '  → ' + extra : '')); }
}
const eq = (name, got, want) =>
  check(name, JSON.stringify(got) === JSON.stringify(want),
        'got=' + JSON.stringify(got) + ' want=' + JSON.stringify(want));

// ------------------------------------------------------------ 空态
console.log('空态：');
check('缺 health → null（不是空数组）', M.deriveMxHealthChips(null) === null);
check('缺 venues → null', M.deriveMxHealthChips({ health: {} }) === null);
check('空 venues → 空数组', JSON.stringify(M.deriveMxHealthChips({ health: { venues: {} } })) === '[]');

// ------------------------------------------------------------ total 取池容量
console.log('total = 池容量（后端投影），不再由名单长度推算：');
const pool6 = M.deriveMxHealthChips({
  health: { venues: { okx: { ok: ['BTC', 'ETH', 'SOL'], failed: ['XRP'], unknown: ['DOGE', 'ARB'], total: 6, avg_ms: 120, testnet: true } } },
});
eq('单条 chip', pool6.length, 1);
eq('ok 条数', pool6[0].ok, 3);
eq('failed 条数（数组形状）', pool6[0].failed, 1);
eq('unknown 条数', pool6[0].unknown, 2);
eq('total 用后端给的 6（而非 3+1=4）', pool6[0].total, 6);
eq('延迟透传', pool6[0].avg_ms, 120);
eq('沙盒标记透传', pool6[0].testnet, true);
check('未核实 > 0 ⇒ 不得全绿', pool6[0].allOk === false);

console.log('全绿只在这种形状下出现：');
const green = M.deriveMxHealthChips({
  health: { venues: { okx: { ok: ['BTC', 'ETH', 'SOL', 'XRP', 'DOGE', 'ARB'], failed: [], unknown: [], total: 6 } } },
});
check('ok=total 且 unknown=0 ⇒ allOk', green[0].allOk === true);

console.log('回归：僵尸名单 9/9 不再可能被渲染成全绿：');
const zombie = M.deriveMxHealthChips({
  // 后端现在按池容量给 total=6，即便遗留清单里写着 UNI 也只体现为 ok 列表内容
  health: { venues: { okx: { ok: ['ADA', 'UNI', 'XRP', 'BTC', 'ETH', 'SOL'], failed: {}, total: 6 } } },
});
eq('total 仍是池容量 6', zombie[0].total, 6);
check('unknown 缺省按 0 处理（后端老响应兼容）', zombie[0].unknown === 0);

// ------------------------------------------------------------ 兼容与兜底
console.log('兼容旧形状与兜底：');
const legacyShape = M.deriveMxHealthChips({
  health: { venues: { okx: { ok: ['A', 'B'], failed: { C: 'err', D: 'err' }, avg_ms: 0 } } },
});
eq('failed 对象形状按键数计', legacyShape[0].failed, 2);
eq('后端没给 total ⇒ 回落 ok+failed', legacyShape[0].total, 4);
check('后端没给 total 且 ok<total ⇒ 不全绿（无证据不升级）', legacyShape[0].allOk === false);
const noArrays = M.deriveMxHealthChips({ health: { venues: { okx: { avg_ms: 30 } } } });
eq('字段全缺 ⇒ 0/0', [noArrays[0].ok, noArrays[0].failed, noArrays[0].unknown, noArrays[0].total], [0, 0, 0, 0]);
check('0/0 不算全绿（避免空名单被读成健康）', noArrays[0].allOk === false);
eq('多个场所各成一条', M.deriveMxHealthChips({
  health: { venues: { okx: { ok: ['A'], total: 1 }, other: { ok: [], total: 0 } } },
}).map((c) => c.name), ['okx', 'other']);

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail === 0 ? 0 : 1);
