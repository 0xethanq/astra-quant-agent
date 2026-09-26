# ASTRA 前端（Vue 3 + TypeScript + Vite）

交易台 Web 界面。**只做展示与交互**：所有业务判定最终以后端接口为准；
但"怎么把后端给的数画出来"的判定规则确实活在这里，故有下面那套纯模块约定。

## 目录

| 路径 | 内容 |
|---|---|
| `src/views/dashboard/` | 交易台主页面（K 线工位、台账、AI 委员会、策略、进化日志…） |
| `src/views/admin/` | 管理页（LLM 配置、密钥、巡检等） |
| `src/components/dashboard/` | 交易台组件 + **`chart*.ts` 纯判定模块**（见下） |
| `src/components/base/` | 通用基础组件（`DataTable`、`BaseSegmented` 等，被 6+ 页面复用） |
| `src/composables/` | 组合式逻辑（主题、i18n、轮询等） |
| `src/stores/` | Pinia 状态（`dashboard` 等） |
| `src/utils/` | 纯工具（`format.ts` 时间格式化、`instId.ts` 标的换算） |
| `src/api/` | 后端接口封装 |
| `src/locales/{zh,en}/` | 中英文案（两侧同 key 成对维护） |
| `tests/` | 行为契约测试（`node:test` + 自检文件，见下） |

## 常用命令

| 命令 | 作用 |
|---|---|
| `npm run dev` | 本地开发服务（热更新） |
| `npm run build` | 生产构建，产物在 `dist/`（**已 gitignore，不入库**） |
| `node --test tests/*.test.mjs` | 跑全部测试（**必须显式列文件**，见踩坑 1） |
| `npx vue-tsc --noEmit` | 类型检查（含 `.vue` 模板类型） |

## 测试基线（2026-09-15）

- `node --test tests/*.test.mjs` ⇒ **全部通过**：8 个 `node:test` 用例文件 +
  5 个自检文件（`chartCandles` / `councilLogic` / `http` / `llmLogic` / `useLlmConfig`，
  共 **136 条断言**）。
- `npx vue-tsc --noEmit` ⇒ 干净无输出。
- `npx vite build` ⇒ 成功。

改动前端后请把这三条都过一遍；**只跑测试不跑类型检查**会漏掉模板里的类型错误。

## ⚠️ 两个踩坑（都花过时间）

1. **`node --test tests/` 会假红**：目录形式下 Node 会把目录本身当作一个测试条目并报
   `test failed`（用例其实全过）。必须写 `tests/*.test.mjs`（或显式列文件名）。
2. **改了源码要重新 `npm run build`**：`dist/` 不在版本库里，服务端读到的是构建产物，
   源码改动不会自动生效（开发时用 `npm run dev` 才热更）。

## 结构约定：判定逻辑抽成 `chart*.ts` 纯模块

`src/components/dashboard/ChartWorkstation.vue`（原 1285 行）是最大的单文件。
**凡是不需要组件上下文的判定/换算，一律抽到同级纯模块**，组件里只留响应式壳
（读 ref → 调纯函数 → 返回）。这样规则可以被 `node --test` 直接钉住，
而不是只能靠肉眼看组件源码确认。

| 模块 | 负责 |
|---|---|
| `chartMath.ts` | 风险收益比、标的价格精度 |
| `chartOverlays.ts` | 开仓/止损/止盈价格线规划 |
| `chartCountdown.ts` | 收盘倒计时文案 |
| `chartCandles.ts` | 蜡烛取数（URL 形状、字段映射、错误分级） |
| `chartIndicators.ts` | 主图/副图指标清单与默认值 |
| `chartLiveLevels.ts` | 从活动持仓/挂单推导**入场价、方向、止损、止盈** |
| `chartStyles.ts` | 图表样式（主题/CVD 联动） |

新增此类模块时，**同时加一个 `tests/<模块名>.test.mjs`** 钉住它的规则
（尤其是"看起来该优化、其实不能动"的地方 —— 例如 `chartLiveLevels.ts` 里
空值合并 `??` 的截断只作用于持仓层、以及字符串 `"0"` 是真值这两条）。
