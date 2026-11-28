# AstraQuant 紧急恢复与排查指南 (v9.2.0)

本文档用于发生服务器重启、网络中断、API 限流或策略异常后的快速止损、状态检查与手动恢复。

---

## 1. 最快安全停盘方式（推荐优先通过网页控制面）

1. **只暂停新开仓（保留现有持仓止损与分批止盈守护）**：
   - 登录 `/admin/agent`（**AI 助手**），在右侧「策略状态 → 快捷开关」打开 **暂停新开仓**；
   - 或在 `/admin/strategy`（**策略配置**）右上角关闭 **开仓开关**。
2. **极端行情一键紧急平仓与撤单**：
   - 前往 `/admin/security`（**账户与应急**），执行「撤销所有挂单」或「全平持仓」（需输入二次确认口令）。
3. **环境变量物理熔断**：
   - 在 `backend/.env` 中设置 `ASTRA_TRADING_PAUSED=true`，然后重启服务使其立即生效。

---

## 2. 一键重启 Docker 服务

当容器异常退出或健康检查报错时，按以下步骤恢复：

```bash
cd /opt/astra-quant-agent   # 或你的实际部署目录

# 1. 拉起容器并检查健康状态
docker compose up -d
docker compose ps

# 2. 查看后端与交易引擎实时日志
docker compose logs -f --tail=120 astraquant-backend

# 3. 验证端口与接口响应
curl -sS http://127.0.0.1:8080/api/v1/health
```

> **提示**：切勿删除持久化挂载目录 `backend/data`、`backend/logs` 和 `backend/backups`。如误删除 `backend/.env`，`docker-entrypoint.sh` 会阻断挂载目录异常并提示修复命令；请使用：
> `rm -rf backend/.env && cp backend/env.example backend/.env && chmod 600 backend/.env` 后再启动。

---

## 3. 策略回滚与模型/账户排查

- **策略误改一键回滚**：
  - 在 `/admin/agent` 中找到已应用的配置 Diff 卡片，点击 **回滚（Rollback）** 即可恢复到该次改动前自动保存的策略快照；
  - 或在 AI 助手右侧 Inspector「快照（Snapshots）」标签页点击恢复任意历史策略包。
- **LLM 接口超时 / 降级**：
  - 前往 `/admin/llm`（**模型连接**）测试激活模型连通性，并配置备用降级模型（Fallback）。当主模型连续超时时引擎会自动切换备用模型。
- **OKX API 鉴权报错（50111 / 50119 等）**：
  - 前往 `/admin/security` 确认当前模式（`DEMO` 模拟盘 vs `LIVE` 实盘）与填入的三件套（API Key / Secret Key / Passphrase）匹配；模拟盘必须使用在 OKX 模拟交易页面申请的 Demo API Key。
  - 若宿主机系统时间漂移超过 30 秒，会导致 OKX V5 签名失败，请启用 NTP 时间同步（`chronyc tracking` / `timedatectl`）。

---

## 4. 手工单次执行与对账命令

在宿主机或容器内 (`docker exec -it astraquant-backend bash`) 可运行以下脚本诊断：

- **查看后端健康快照**：
  `curl -s http://127.0.0.1:8080/api/v1/health`
- **手工运行一轮市场因子快照**：
  `cd /app/backend && python3 scripts/market_radar.py`
- **手工单次执行 AI 决策周期**：
  `cd /app/backend && python3 scripts/ai_brain_trader.py`
- **手工同步 OKX 历史台账与资金费率**：
  `cd /app/backend && python3 scripts/sync_full_ledger.py`
- **手工运行一次闭环策略复盘**：
  `cd /app/backend && python3 scripts/self_improvement_engine.py`
- **手工触发全量多通道加密备份**：
  `cd /app/backend && python3 scripts/nightly_backup_and_clean.py --all-enabled`
- **磁盘空间与日志轮转清理**：
  `cd /app/backend && python3 scripts/cleanup_disk.py`

> **注意**：`backend/.env` 与 `backend/data/.secrets*` 包含管理员凭据与交易密钥，请定期通过 `/admin/notify` 和 `/admin/backup` 确认离线加密备份通道（WebDAV / S3 / Telegram / 邮箱）可用。
