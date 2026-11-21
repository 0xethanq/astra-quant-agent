## 改动摘要 (Summary of Changes)
<!-- 简要概括本次 Pull Request 的核心修改与解决的问题 -->

## 关联 Issue (Related Issue)
<!-- 例如: Fixes #123 或 Relates to #456 -->

## 改动范围 (Scope of Changes)
- [ ] 后端核心引擎 (`backend/astra_backend/`)
- [ ] 量化调度网关 (`backend/astra_gateway/`)
- [ ] 执行与策略脚本 (`backend/scripts/`)
- [ ] Vue 3 操盘看板与控制面 (`frontend/`)
- [ ] 部署编排与守护 (`backend/deploy/`, `Dockerfile`)
- [ ] 系统文档与资产 (`backend/docs/`, `README.md`)

## 门禁验证清单 (Gate Verification Checklist)
在提交 PR 前，请确保已跑通以下对应门禁：
- [ ] **后端全量套件（与 CI 一致）**: `cd backend && .venv/bin/pytest tests -n auto -q && cd ..`
- [ ] **Tier 0 核心量化业务门**: `backend/.venv/bin/pytest backend/tests/trading backend/tests/venues backend/tests/risk backend/tests/backtest -n auto -q`
- [ ] **Tier 1 模型与前端集成门**: `backend/.venv/bin/pytest backend/tests/llm backend/tests/ui backend/tests/core -n auto -q`
- [ ] **前端类型检查、构建与测试**: `cd frontend && npm run typecheck && npm run build && npm test && cd ..`
- [ ] **Python 静态检查**: `backend/.venv/bin/ruff check backend`
- [ ] **Tier 2 全量架构审计门**: `backend/.venv/bin/pytest backend/tests/audit backend/tests/extraction backend/tests/ops -n auto -q`
- [ ] **敏感凭证防泄漏确认**: 确认无任何 API Key、私钥或生产数据混入提交
