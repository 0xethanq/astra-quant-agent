## 改动摘要 (Summary of Changes)
<!-- 简要概括本次 Pull Request 的核心修改与解决的问题 -->

## 关联 Issue (Related Issue)
<!-- 例如: Fixes #123 或 Relates to #456 -->

## 改动范围 (Scope of Changes)
- [ ] 后端核心引擎 (`astra_backend/`)
- [ ] 量化调度网关 (`astra_gateway/`)
- [ ] 执行与策略脚本 (`scripts/`)
- [ ] Vue 3 操盘看板与控制面 (`frontend/`)
- [ ] 部署编排与守护 (`deploy/`, `Dockerfile`)
- [ ] 系统文档与资产 (`docs/`, `README.md`)

## 门禁验证清单 (Gate Verification Checklist)
在提交 PR 前，请确保已跑通以下对应门禁：
- [ ] **Tier 0 核心量化业务门**: `.venv/bin/pytest tests/trading tests/venues tests/risk tests/backtest -n auto -q`
- [ ] **Tier 1 模型与前端集成门**: `.venv/bin/pytest tests/llm tests/ui tests/core -n auto -q`
- [ ] **前端构建与类型检查**: `cd frontend && npm run build && npx vue-tsc --noEmit && node --test tests/*.test.mjs && cd ..`
- [ ] **Tier 2 全量架构审计门**: `.venv/bin/pytest tests/audit tests/extraction tests/ops -n auto -q`
- [ ] **敏感凭证防泄漏确认**: 确认无任何 API Key、私钥或生产数据混入提交
