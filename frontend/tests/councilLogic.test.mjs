/**
 * `src/views/admin/council/councilLogic.ts` 行为契约
 * （结构优化阶段 4·B3 第六十刀）。
 *
 * ## 背景
 *
 * `views/admin/CouncilPage.vue`（873 行，script 302 行）此前**没有任何行为测试**
 * —— 唯一既有断言 `test_ui_slots_are_real_variables` 只是对 `{ k: '…' }`
 * 做正则扫描。本刀把无状态逻辑搬进 `councilLogic.ts` 后即可直接跑测试。
 *
 * ## 运行
 *     node --experimental-strip-types tests/councilLogic.test.mjs
 */
import { pathToFileURL } from 'node:url';
import path from 'node:path';

const M = await import(
  pathToFileURL(path.resolve('src/views/admin/council/councilLogic.ts')).href
);

let pass = 0, fail = 0;
function check(name, cond, extra = '') {
  if (cond) { pass++; console.log('  ok   ' + name); }
  else { fail++; console.log('  FAIL ' + name + (extra ? '  → ' + extra : '')); }
}
const eq = (name, got, want) =>
  check(name, JSON.stringify(got) === JSON.stringify(want),
        'got=' + JSON.stringify(got) + ' want=' + JSON.stringify(want));

// ------------------------------------------------------------ 零依赖
console.log('模块形态:');
{
  const src = await import('node:fs').then(fs =>
    fs.readFileSync(path.resolve('src/views/admin/council/councilLogic.ts'), 'utf8'));
  check('不 import 任何东西（纯逻辑模块）', !/^\s*import\s/m.test(src), '出现了 import');
  check('不含 vue 依赖', !src.includes("from 'vue'"));
  check('不含 fetch/网络调用', !src.includes('fetch('));
}

// ------------------------------------------------------------ 共识模式
console.log('CONSENSUS_MODES:');
{
  eq('三个模式', M.CONSENSUS_MODES.length, 3);
  eq('id 顺序与取值（必须与后端 consensus_mode 一致）',
     M.CONSENSUS_MODES.map(m => m.id), ['standard', 'cross_examination', 'debate']);
  for (const m of M.CONSENSUS_MODES) {
    check(`${m.id} 四个字段都非空`,
          !!(m.id && m.name && m.tag && m.desc));
  }
  check('standard 排在第一个（默认模式）', M.CONSENSUS_MODES[0].id === 'standard');
}

// ------------------------------------------------------------ 席位识别
console.log('isCioSeat / isBuiltinTrader:');
{
  const C = M.isCioSeat;
  check('is_arbitrator=true → CIO', C({ is_arbitrator: true }, 'x') === true);
  check("roleId === 'cio' → CIO", C({}, 'cio') === true);
  check("is_arbitrator=true 且 id 是 cio → CIO", C({ is_arbitrator: true }, 'cio') === true);
  check('普通交易员 → 否', C({ is_arbitrator: false }, 'trader_trend') === false);
  check('undefined role 但 id=cio → CIO', C(undefined, 'cio') === true);
  check('null role 且 id 普通 → 否', C(null, 'trader_x') === false);
  // 真值化：后端可能给 1/0
  check('is_arbitrator=1 → CIO（真值化）', C({ is_arbitrator: 1 }, 'x') === true);
  check('is_arbitrator=0 → 否', C({ is_arbitrator: 0 }, 'x') === false);
  check('返回值恒为 boolean', typeof C({ is_arbitrator: 1 }, 'x') === 'boolean');

  eq('内置交易员列表（与后端 ALL_AVAILABLE_PRESETS 对齐）',
     M.BUILTIN_TRADER_IDS, ['trader_trend', 'trader_momentum', 'trader_quant']);
  for (const id of M.BUILTIN_TRADER_IDS) {
    check(`${id} 是内置`, M.isBuiltinTrader(id) === true);
  }
  check('cio 不是交易员', M.isBuiltinTrader('cio') === false);
  check('自定义席位不是内置', M.isBuiltinTrader('trader_lz3k9') === false);
  check('非字符串入参不崩', M.isBuiltinTrader(undefined) === false);
  eq('CIO_ROLE_ID', M.CIO_ROLE_ID, 'cio');
}

// ------------------------------------------------------------ roleIdOf
console.log('roleIdOf:');
{
  check('前缀 trader_', M.roleIdOf(1000).startsWith('trader_'));
  eq('base36 编码', M.roleIdOf(1000), 'trader_' + (1000).toString(36));
  check('两次调用（不同 ms）不同 id', M.roleIdOf(1000) !== M.roleIdOf(1001));
  // ⚠️ 已知缺陷，原实现即如此：同毫秒撞 id
  eq('⚠️ 同一毫秒撞 id（原实现即如此，本刀保持等价）',
     M.roleIdOf(1000), M.roleIdOf(1000));
}

// ------------------------------------------------------------ 配色 / 图标键
console.log('roleColorOf / roleIconKeyOf:');
{
  eq('trader_trend 配色', M.roleColorOf('trader_trend'),
     'text-emerald-400 border-emerald-500/30 bg-emerald-500/10');
  eq('cio 配色', M.roleColorOf('cio'),
     'text-purple-400 border-purple-500/30 bg-purple-500/10');
  eq('未知席位 → 兜底档', M.roleColorOf('trader_lz3k9'), M.CUSTOM_ROLE_COLOR);
  eq('custom 本身 → 兜底档', M.roleColorOf('custom'), M.CUSTOM_ROLE_COLOR);
  eq('空串 → 兜底档', M.roleColorOf(''), M.CUSTOM_ROLE_COLOR);
  eq('undefined → 兜底档', M.roleColorOf(undefined), M.CUSTOM_ROLE_COLOR);
  check('全部内置席位都有专属配色',
        M.BUILTIN_TRADER_IDS.every(id => M.roleColorOf(id) !== M.CUSTOM_ROLE_COLOR));
  // 表里不含 custom —— 避免"永远不会被命中"的项
  check('ROLE_COLORS 不含 custom（否则那项永不命中）', !('custom' in M.ROLE_COLORS));

  eq('trader_trend 图标键 = 自身', M.roleIconKeyOf('trader_trend'), 'trader_trend');
  eq('cio 图标键 = 自身', M.roleIconKeyOf('cio'), 'cio');
  eq('未知席位 → custom', M.roleIconKeyOf('trader_lz3k9'), 'custom');
  eq('custom → custom', M.roleIconKeyOf('custom'), 'custom');
  eq('undefined → custom', M.roleIconKeyOf(undefined), 'custom');
}

// ------------------------------------------------------------ 数据槽位
console.log('DATA_SLOTS:');
{
  const ks = M.DATA_SLOTS.map(s => s.k);
  // ★ 2026-10：`market_regime`（全市场宏观体制）随退役数理引擎一并移除 —— 该插槽
  //   恒为空（后端不再签发），列在可选变量里只会让用户插出一个永远为空的占位符。
  eq('8 个槽位', M.DATA_SLOTS.length, 8);
  eq('顺序与取值', ks, ['market_matrix', 'account_balance', 'account_positions',
                        'pending_orders', 'risk_budget', 'active_instruments',
                        'news_intelligence', 'trading_memory']);
  eq('无重复', new Set(ks).size, ks.length);
  check('每项都有非空 label', M.DATA_SLOTS.every(s => !!s.label));
  // ⚠️ 审计 P1-4d 的核心：这 5 个曾是非法变量，必须**不再出现**
  for (const bad of ['macro_4h', 'calculus_1h', 'smart_money', 'orderbook_depth', 'sentiment']) {
    check(`⚠️ 非法变量 ${bad} 不得出现在槽位表里`, !ks.includes(bad));
  }
}

// ------------------------------------------------------------ isModelMissing
console.log('isModelMissing（审计 P1-4b）:');
{
  const models = [{ id: 'm1' }, { id: 'm2' }];
  check('在库 → false', M.isModelMissing({ model_id: 'm1' }, models) === false);
  check('不在库 → true', M.isModelMissing({ model_id: 'm9' }, models) === true);
  check('空 model_id → false（跟随主脑，合法状态）',
        M.isModelMissing({ model_id: '' }, models) === false);
  check('缺 model_id → false', M.isModelMissing({}, models) === false);
  check('纯空白 model_id → false', M.isModelMissing({ model_id: '   ' }, models) === false);
  check('undefined role → false', M.isModelMissing(undefined, models) === false);
  check('models 为空数组 + 有 id → true', M.isModelMissing({ model_id: 'm1' }, []) === true);
  check('models 为 null + 有 id → true', M.isModelMissing({ model_id: 'm1' }, null) === true);
  check('models 为 undefined + 有 id → true', M.isModelMissing({ model_id: 'm1' }, undefined) === true);
  check('数字 id 也按字符串比（后端可能给数字）',
        M.isModelMissing({ model_id: 1 }, [{ id: '1' }]) === false);
  check('name 相同但 id 不同 → 仍算缺失',
        M.isModelMissing({ model_id: 'x' }, [{ id: 'y', name: 'x' }]) === true);
}

// ------------------------------------------------------------ 展示名
console.log('consensusModeName / roleDisplayName / roleTitleOf:');
{
  eq('standard → 标准提案模式',
     M.consensusModeName('standard', 'FALLBACK'), '标准提案模式');
  eq('cross_examination', M.consensusModeName('cross_examination', 'FB'), '交叉质询模式');
  eq('debate', M.consensusModeName('debate', 'FB'), '对抗辩论模式');
  eq('未知模式 → 回落', M.consensusModeName('nope', '标准提案模式'), '标准提案模式');
  eq('空串 → 回落', M.consensusModeName('', 'FB'), 'FB');
  eq('undefined → 回落', M.consensusModeName(undefined, 'FB'), 'FB');

  eq('有 name → 用 name', M.roleDisplayName({ name: '宏观派' }, 'trader_trend'), '宏观派');
  eq('无 name → 用 id', M.roleDisplayName({}, 'trader_trend'), 'trader_trend');
  eq('name 为空串 → 用 id', M.roleDisplayName({ name: '' }, 'r1'), 'r1');
  eq('role 为 undefined → 用 id', M.roleDisplayName(undefined, 'r1'), 'r1');

  eq('有 role_title → 用它', M.roleTitleOf({ role_title: 'CIO' }, 'FB'), 'CIO');
  eq('无 role_title → 回落', M.roleTitleOf({}, 'Senior Trader'), 'Senior Trader');
  eq('role_title 为空串 → 回落', M.roleTitleOf({ role_title: '' }, 'FB'), 'FB');
}

// ------------------------------------------------------------ 保存 / 导入载荷
console.log('buildCouncilSavePayload:');
{
  const full = M.buildCouncilSavePayload({
    enabled: true, consensus_mode: 'debate', timeout_seconds: 300, roles: { a: 1 } });
  eq('完整配置', full, { enabled: true, consensus_mode: 'debate',
                        timeout_seconds: 300, roles: { a: 1 } });
  eq('字段顺序', Object.keys(full),
     ['enabled', 'consensus_mode', 'timeout_seconds', 'roles']);
  const empty = M.buildCouncilSavePayload({});
  eq('consensus_mode 回落 standard', empty.consensus_mode, 'standard');
  eq('timeout 回落 240', empty.timeout_seconds, 240.0);
  // ⚠️ 与页面初始值一致（页面 ref 初值也是 240）——
  //    两处若不一致，用户不改超时也会被静默改成另一个值
  eq('timeout 回落值与页面初始值一致',
     M.buildCouncilSavePayload({ timeout_seconds: undefined }).timeout_seconds, 240.0);
  eq('timeout=0（falsy）也回落 240', M.buildCouncilSavePayload({ timeout_seconds: 0 }).timeout_seconds, 240.0);
  eq('timeout 字符串被 Number 化',
     M.buildCouncilSavePayload({ timeout_seconds: '450' }).timeout_seconds, 450);
  eq('timeout 非数字回落 240',
     M.buildCouncilSavePayload({ timeout_seconds: 'abc' }).timeout_seconds, 240.0);
  eq('cfg 为 null 不崩', M.buildCouncilSavePayload(null),
     { enabled: undefined, consensus_mode: 'standard', timeout_seconds: 240.0, roles: undefined });
  check('roles 原样透传（不深拷贝 —— 后端要完整席位）',
        M.buildCouncilSavePayload({ roles: { z: 9 } }).roles.z === 9);
}

console.log('buildCouncilImportPayload:');
eq('包成 { payload }', M.buildCouncilImportPayload({ roles: {} }), { payload: { roles: {} } });
eq('null 也能包', M.buildCouncilImportPayload(null), { payload: null });
eq('只此一个键', Object.keys(M.buildCouncilImportPayload(1)), ['payload']);

// ------------------------------------------------------------ nextExpandedRole
console.log('nextExpandedRole:');
eq('当前不在列表 → 展开第一个',
   M.nextExpandedRole(['a', 'b'], 'zz'), 'a');
eq('当前在列表 → 不变', M.nextExpandedRole(['a', 'b'], 'b'), 'b');
eq('空列表 → 不变（保持原值）', M.nextExpandedRole([], 'trader_trend'), 'trader_trend');
eq('undefined 列表 → 不变', M.nextExpandedRole(undefined, 'x'), 'x');
eq('单元素且不匹配 → 取它', M.nextExpandedRole(['only'], 'x'), 'only');
eq('列表含空串时取空串（原实现即如此）',
   M.nextExpandedRole([''], 'x'), '');

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail === 0 ? 0 : 1);
