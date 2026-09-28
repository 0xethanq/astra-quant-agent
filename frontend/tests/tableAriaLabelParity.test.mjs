/**
 * 数据表格（table）可访问性名称准确性与杜绝错位复制守卫闸（批 124）。
 *
 * ## 实测发现的 3 处表格 aria-label 复制错位缺陷：
 *
 * 1–2. （2026-10 更新：`RadarDrawer` 的跨所基差价差表与 `FactorDrawer` 的淘汰候选表
 *    已随「全站收口 OKX」整体删除。原先那两条错位缺陷随之消失，判据改为
 *    **"这两张表不得回潮"** 的反向守卫，仍然盯住同一批文件。）
 *
 * 3. `CouncilPage.vue` 六标的点位矩阵表格复制了上一张席位表的标题：
 *    - 表格内容：BTC/ETH/SOL/DOGE/XRP/ADA 六标的推演点位与止盈止损矩阵；
 *    - 修复前：`:aria-label="t('admin.council.seatsTitle')"`（"投委会席位编排"）；
 *    - 修复后：`:aria-label="t('admin.council.matrixTitle')"`（"六标的点位矩阵"）。
 *
 * 运行：`node --test tests/*.test.mjs`
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import path from 'node:path';

const SRC = path.resolve(import.meta.dirname, '..', 'src');

test('RadarDrawer 跨所证据表格已移除，且不得带着错误 aria-label 回潮', () => {
  const vue = readFileSync(path.join(SRC, 'components/dashboard/RadarDrawer.vue'), 'utf8');
  assert.doesNotMatch(vue, /xvenue/i, 'RadarDrawer 又出现了跨所（xvenue）页签或表格');
  assert.doesNotMatch(vue, /cross_venue/, 'RadarDrawer 又去读 cross_venue 载荷了');
  // 真删除（而不是"留着表只删了标签"）：跨所行情字段一个都不该再被引用
  for (const f of ['bin_last', 'bin_basis_pct', 'gate_last', 'gate_basis_pct', 'bin_ls', 'gate_ls']) {
    assert.ok(!vue.includes(f), `RadarDrawer 仍在引用跨所字段 ${f}`);
  }
});

test('FactorDrawer 选所决策与跨所区块已移除，且不得回潮', () => {
  const vue = readFileSync(path.join(SRC, 'components/dashboard/FactorDrawer.vue'), 'utf8');
  assert.doesNotMatch(vue, /venue_decision/, 'FactorDrawer 又去读 venue_decision 载荷了');
  assert.doesNotMatch(vue, /venueLabel|venueColor|decisionBadgeCls/, 'FactorDrawer 又引用了已删除的 venueMeta 助手');
  for (const f of ['rejectedTitle', 'crossTitle', 'preferred_venue', 'crossVenue']) {
    assert.ok(!vue.includes(f), `FactorDrawer 仍在引用选所/跨所字段 ${f}`);
  }
});

test('CouncilPage 六标的点位矩阵表格必须绑定 matrixTitle（严禁复制 seatsTitle）', () => {
  const vue = readFileSync(path.join(SRC, 'views/admin/CouncilPage.vue'), 'utf8');
  const matrixBlockMatch = vue.match(/<!-- 六标的点位矩阵 -->[\s\S]*?<table\b([^>]*)>/);
  assert.ok(matrixBlockMatch, '找不到六标的点位矩阵表格');
  const tableAttrs = matrixBlockMatch[1];
  assert.doesNotMatch(
    tableAttrs,
    /:aria-label="t\('admin\.council\.seatsTitle'\)"/,
    '六标的点位矩阵表格错误复制了席位表 seatsTitle 的 aria-label',
  );
  assert.match(
    tableAttrs,
    /:aria-label="t\('admin\.council\.matrixTitle'\)"/,
    '六标的点位矩阵表格缺少 matrixTitle 的 aria-label',
  );
});
