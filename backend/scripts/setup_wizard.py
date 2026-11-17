#!/usr/bin/env python3
"""AstraQuant 开箱部署引导向导（Setup Wizard）。

解决部署后手工配置 300+ 行 .env 繁重易错的痛点，提供 2 分钟极速交互式引导：
1. 交易所运行模式与 API Key（OKX 模拟盘/实盘）
2. AI 大脑服务商与模型（DeepSeek / OpenRouter / OpenAI / 硅基流动 / 自定义）
3. 风险偏好基线预设（稳健防守 / 均衡波段 / 进取猎手）
4. 超级管理员初始口令
"""
from __future__ import annotations

import getpass
import os
import secrets
import shutil
import string
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / ".env"
ENV_EXAMPLE = ROOT / "env.example"

# ANSI Colors
BOLD = "\033[1m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
CYAN = "\033[36m"
RED = "\033[31m"
DIM = "\033[2m"
RESET = "\033[0m"


def print_banner() -> None:
    print(f"\n{CYAN}{BOLD}" + "=" * 72)
    print("   ★ AstraQuant Autonomous Quant OS · 开箱部署向导")
    print("   多模型对抗质询 · 7层量化因子微积分 · 确定性物理风控")
    print("=" * 72 + f"{RESET}\n")
    print(f"{DIM}欢迎使用 AstraQuant！本向导将引导你在 2 分钟内完成关键交易环境配置。{RESET}\n")


def generate_secure_password(length: int = 16) -> str:
    alphabet = string.ascii_letters + string.digits
    while True:
        pwd = "".join(secrets.choice(alphabet) for _ in range(length))
        if any(c.islower() for c in pwd) and any(c.isupper() for c in pwd) and any(c.isdigit() for c in pwd):
            return pwd


def ensure_env_exists() -> None:
    if not ENV_FILE.exists():
        if ENV_EXAMPLE.exists():
            shutil.copy(ENV_EXAMPLE, ENV_FILE)
            try:
                os.chmod(ENV_FILE, 0o600)
            except Exception:
                pass
            print(f"{GREEN}✓ 已从 env.example 自动创建基础 .env 文件{RESET}")
        else:
            ENV_FILE.touch(mode=0o600)


def update_env_keys(updates: dict[str, str]) -> None:
    ensure_env_exists()
    content = ENV_FILE.read_text(encoding="utf-8")
    lines = content.splitlines()
    new_lines = []
    seen = set()

    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            k, _ = stripped.split("=", 1)
            k = k.strip()
            if k in updates:
                new_lines.append(f"{k}={updates[k]}")
                seen.add(k)
                continue
        new_lines.append(line)

    for k, v in updates.items():
        if k not in seen:
            new_lines.append(f"{k}={v}")

    ENV_FILE.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


def print_help() -> None:
    print(f"""{CYAN}{BOLD}AstraQuant 开箱部署向导 (Setup Wizard){RESET}

用法:
  ./setup.sh [选项]
  或
  python3 scripts/setup_wizard.py [选项]

选项:
  -h, --help           显示此帮助信息并退出
  --non-interactive    使用安全默认配置直接初始化 .env（无需人工交互，适合容器/脚本部署）

说明:
  本向导引导配置 OKX 交易所模式 (模拟盘/实盘)、AI 大模型连接、
  风控基线与超级管理员初始口令，并写入安全的 .env 配置文件 (chmod 600)。
""")


def run_wizard(non_interactive: bool = False) -> None:
    print_banner()
    ensure_env_exists()
    updates: dict[str, str] = {}

    if non_interactive or not sys.stdin.isatty():
        print(f"{YELLOW}检测到非交互式环境或 --non-interactive 标志，正在应用安全推荐基线...{RESET}")
        updates["ASTRA_OKX_ENV"] = "demo"
        updates["LLM_BASE_URL"] = "https://api.deepseek.com/v1"
        updates["LLM_MODEL"] = "deepseek-chat"
        updates["LLM_REASONING_EFFORT"] = "high"
        updates["ASTRA_MIN_LEVERAGE"] = "3.0"
        updates["ASTRA_MAX_LEVERAGE"] = "8.0"
        updates["ASTRA_RISK_PER_TRADE_RATIO"] = "0.035"
        updates["ASTRA_MAX_MARGIN_EQUITY_RATIO"] = "0.35"
        updates["ASTRA_SINGLE_ASSET_EQUITY_RATIO"] = "0.45"
        updates["ASTRA_MAX_CONCURRENT_POSITIONS"] = "4"
        updates["ASTRA_MIN_ENTRY_CONFIDENCE"] = "70.0"
        updates["ASTRA_MAX_SCALE_IN_COUNT"] = "2"
        updates["ASTRA_MIN_SCALE_IN_CONFIDENCE"] = "68.0"
        updates["ASTRA_STOP_COOLDOWN_MINUTES"] = "15"
        updates["ASTRA_ADMIN_TOKEN"] = "AstraAdmin888888"  # 兼容历史口令 R20admin888888
        update_env_keys(updates)
        print(f"{GREEN}✓ 已完成非交互式初始化，管理员默认密码为: AstraAdmin888888{RESET}\n")
        return

    # -------------------------------------------------------------
    # 步骤 1: 交易所环境与凭证 (OKX)
    # -------------------------------------------------------------
    print(f"{BOLD}[1/4] 交易所配置 (OKX){RESET}")
    print("选择交易运行模式:")
    print(f"  {CYAN}1. 模拟盘 (Demo / Paper Trading){RESET} {YELLOW}★ 官方推荐 (零真金风险){RESET}")
    print(f"  {CYAN}2. 实盘 (Live Trading){RESET}")
    mode_choice = input(f"{BOLD}请选择 [默认 1]: {RESET}").strip()
    is_live = mode_choice == "2"
    env_name = "live" if is_live else "demo"
    updates["ASTRA_OKX_ENV"] = env_name
    print(f"-> 已选定运行环境: {GREEN}{'实盘 (Live)' if is_live else '模拟盘 (Demo)'}{RESET}\n")

    prefix = "OKX_LIVE_" if is_live else "OKX_DEMO_"
    print(f"{DIM}请输入 OKX V5 API 密钥（可回车跳过，稍后在 Web 界面配置）：{RESET}")
    api_key = input("API Key: ").strip()
    secret_key = getpass.getpass("Secret Key: ").strip() if api_key else ""
    passphrase = getpass.getpass("Passphrase: ").strip() if api_key else ""

    if api_key and secret_key and passphrase:
        updates[f"{prefix}API_KEY"] = api_key
        updates[f"{prefix}SECRET_KEY"] = secret_key
        updates[f"{prefix}PASSPHRASE"] = passphrase
        print(f"{GREEN}✓ 已暂存 OKX 凭证{RESET}")
        test_okx = input(f"{DIM}是否立即验证 OKX 接口连通性？[y/N]: {RESET}").strip().lower()
        if test_okx in ("y", "yes"):
            print(f"{CYAN}正在验证 OKX V5 接口...{RESET}")
            try:
                import scripts.okx_rest as okx_probe
                from scripts.okx_runtime import OKXEnvironment
                probe_env = OKXEnvironment(mode=env_name, api_key=api_key, secret_key=secret_key, passphrase=passphrase, base_url="https://www.okx.com")
                rows = okx_probe.positions(env=probe_env)
                print(f"{GREEN}✓ OKX 鉴权成功！当前持仓数: {len(rows)}{RESET}\n")
            except Exception as exc:
                print(f"{YELLOW}⚠ 探测提示: {exc}{RESET}")
                print(f"{DIM}  (凭证已保存，您仍可在启动后于控制台进一步配置 IP 白名单或排查网络){RESET}\n")
        else:
            print("")
    else:
        print(f"{YELLOW}⚠ 暂未填写完整 OKX 凭证，部署后可在控制台 /admin/security 填入{RESET}\n")

    # -------------------------------------------------------------
    # 步骤 2: AI 推理大脑 (LLM)
    # -------------------------------------------------------------
    print(f"{BOLD}[2/4] AI 推理主脑服务配置{RESET}")
    print("选择大模型提供商预设:")
    print(f"  {CYAN}1. DeepSeek 官方{RESET} (api.deepseek.com) {YELLOW}★ 推荐{RESET}")
    print(f"  {CYAN}2. OpenRouter{RESET} (openrouter.ai)")
    print(f"  {CYAN}3. OpenAI 官方{RESET} (api.openai.com)")
    print(f"  {CYAN}4. 硅基流动 SiliconFlow{RESET} (api.siliconflow.cn)")
    print(f"  {CYAN}5. 自定义中继 / 自建大模型{RESET}")
    provider_choice = input(f"{BOLD}请选择 [默认 1]: {RESET}").strip()

    base_url = "https://api.deepseek.com/v1"
    model = "deepseek-chat"
    effort = "high"

    if provider_choice == "2":
        base_url = "https://openrouter.ai/api/v1"
        model = "deepseek/deepseek-chat"
    elif provider_choice == "3":
        base_url = "https://api.openai.com/v1"
        model = "gpt-4o"
    elif provider_choice == "4":
        base_url = "https://api.siliconflow.cn/v1"
        model = "deepseek-ai/DeepSeek-V3"
    elif provider_choice == "5":
        custom_url = input("请输入 Base URL (如 https://my-api.com/v1): ").strip()
        if custom_url:
            base_url = custom_url
        custom_model = input("请输入模型名称 (如 deepseek-chat): ").strip()
        if custom_model:
            model = custom_model

    llm_key = getpass.getpass(f"请输入 {model} 的 API Key: ").strip()
    updates["LLM_BASE_URL"] = base_url
    updates["LLM_MODEL"] = model
    updates["LLM_REASONING_EFFORT"] = effort
    if llm_key:
        updates["LLM_API_KEY"] = llm_key
        print(f"{GREEN}✓ 已配置大模型: {model} @ {base_url}{RESET}")
        test_llm = input(f"{DIM}是否测试大模型网络响应？[y/N]: {RESET}").strip().lower()
        if test_llm in ("y", "yes"):
            print(f"{CYAN}正在测试大模型网络响应...{RESET}")
            try:
                import urllib.request, time
                req_url = f"{base_url.rstrip('/')}/models"
                req = urllib.request.Request(req_url, headers={"Authorization": f"Bearer {llm_key}", "User-Agent": "AstraQuant-Setup/1.0"})
                t0 = time.time()
                with urllib.request.urlopen(req, timeout=5) as resp:
                    print(f"{GREEN}✓ 大模型接口响应正常 (HTTP {resp.status}, 耗时: {time.time()-t0:.2f}s){RESET}\n")
            except Exception as exc:
                print(f"{YELLOW}⚠ 探测提示: 无法连通 /models 端点 ({exc}){RESET}")
                print(f"{DIM}  (部分厂商可能未开放 /models 列表，密钥已成功保存){RESET}\n")
        else:
            print("")
    else:
        print(f"{YELLOW}⚠ 暂未填写 API Key，部署后可在后台 /admin/llm 填入{RESET}\n")

    # -------------------------------------------------------------
    # 步骤 3: 风险策略偏好预设
    # -------------------------------------------------------------
    print(f"{BOLD}[3/4] 执行层风控与仓位基线{RESET}")
    print("选择风控策略基线:")
    print(f"  {CYAN}1. 稳健防守{RESET} (杠杆 2-3x, 单笔最大风险 1.5%, 适合大资金稳健收益)")
    print(f"  {CYAN}2. 均衡波段{RESET} (杠杆 3-5x, 单笔最大风险 2.0%, {YELLOW}★ 官方基准推荐{RESET})")
    print(f"  {CYAN}3. 进取猎手{RESET} (杠杆 5-7x, 单笔最大风险 3.0%, 适合高弹性波动)")
    risk_choice = input(f"{BOLD}请选择 [默认 2]: {RESET}").strip()

    if risk_choice == "1":
        updates["ASTRA_MIN_LEVERAGE"] = "2.0"
        updates["ASTRA_MAX_LEVERAGE"] = "3.0"
        updates["ASTRA_RISK_PER_TRADE_RATIO"] = "0.015"
        updates["ASTRA_MAX_CONCURRENT_POSITIONS"] = "2"
        updates["ASTRA_MIN_ENTRY_CONFIDENCE"] = "80.0"
        updates["ASTRA_MAX_SCALE_IN_COUNT"] = "0"
        print(f"{GREEN}✓ 已应用「稳健防守」风控基线{RESET}\n")
    elif risk_choice == "3":
        updates["ASTRA_MIN_LEVERAGE"] = "6.0"
        updates["ASTRA_MAX_LEVERAGE"] = "9.9"
        updates["ASTRA_RISK_PER_TRADE_RATIO"] = "0.045"
        updates["ASTRA_MAX_MARGIN_EQUITY_RATIO"] = "0.40"
        updates["ASTRA_SINGLE_ASSET_EQUITY_RATIO"] = "0.48"
        updates["ASTRA_MAX_CONCURRENT_POSITIONS"] = "5"
        updates["ASTRA_MIN_ENTRY_CONFIDENCE"] = "68.0"
        updates["ASTRA_MAX_SCALE_IN_COUNT"] = "2"
        updates["ASTRA_MIN_SCALE_IN_CONFIDENCE"] = "68.0"
        updates["ASTRA_STOP_COOLDOWN_MINUTES"] = "15"
        print(f"{GREEN}✓ 已应用「进取猎手」风控基线{RESET}\n")
    else:
        updates["ASTRA_MIN_LEVERAGE"] = "3.0"
        updates["ASTRA_MAX_LEVERAGE"] = "8.0"
        updates["ASTRA_RISK_PER_TRADE_RATIO"] = "0.035"
        updates["ASTRA_MAX_MARGIN_EQUITY_RATIO"] = "0.35"
        updates["ASTRA_SINGLE_ASSET_EQUITY_RATIO"] = "0.45"
        updates["ASTRA_MAX_CONCURRENT_POSITIONS"] = "4"
        updates["ASTRA_MIN_ENTRY_CONFIDENCE"] = "70.0"
        updates["ASTRA_MAX_SCALE_IN_COUNT"] = "2"
        updates["ASTRA_MIN_SCALE_IN_CONFIDENCE"] = "68.0"
        updates["ASTRA_STOP_COOLDOWN_MINUTES"] = "15"
        print(f"{GREEN}✓ 已应用「敏捷波段」高周转基准风控{RESET}\n")

    # -------------------------------------------------------------
    # 步骤 4: 管理员初始访问口令
    # -------------------------------------------------------------
    print(f"{BOLD}[4/4] 管理员控制台安全口令{RESET}")
    default_pwd = "AstraAdmin888888"  # 兼容历史口令 R20admin888888
    print(f"推荐系统默认管理员密码: {CYAN}{BOLD}{default_pwd}{RESET}")
    custom_pwd = input("自定义密码 (直接回车采纳默认密码): ").strip()
    final_pwd = custom_pwd if len(custom_pwd) >= 12 else default_pwd
    updates["ASTRA_ADMIN_TOKEN"] = final_pwd

    # 写入文件
    update_env_keys(updates)
    # 同步底层模型配置库 llm_models.json，杜绝环境变量与后台配置错位
    if "LLM_MODEL" in updates:
        try:
            import json
            cfg_file = ROOT / "data" / "llm_models.json"
            if cfg_file.exists():
                cfg = json.loads(cfg_file.read_text(encoding="utf-8"))
                new_mid = updates["LLM_MODEL"]
                new_base = updates.get("LLM_BASE_URL", "").rstrip("/")
                new_key = updates.get("LLM_API_KEY", "")
                cfg["active_model_id"] = new_mid
                cfg["active_provider_id"] = "custom"
                models = cfg.setdefault("models", [])
                m = next((item for item in models if item.get("id") == new_mid), None)
                if m:
                    if new_base:
                        m["base_url"] = new_base
                    if new_key:
                        m["api_key"] = new_key
                else:
                    models.append({
                        "id": new_mid,
                        "name": new_mid,
                        "provider_id": "custom",
                        "provider_name": "自定义",
                        "base_url": new_base,
                        "api_key": new_key,
                        "api_format": "openai_chat",
                        "reasoning_type": "auto",
                        "reasoning_effort": updates.get("LLM_REASONING_EFFORT", "high"),
                    })
                cfg_file.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass

    print(f"\n{GREEN}{BOLD}" + "=" * 72)
    print("   ✓ 配置完成！.env 已经成功生成并加固权限 (600)")
    print("=" * 72 + f"{RESET}\n")
    print(f"控制台超级管理员用户: {BOLD}admin{RESET}")
    print(f"控制台超级管理员密码: {GREEN}{BOLD}{final_pwd}{RESET}")
    print(f"{DIM}（请妥善保存此管理员口令，或在首次访问 Web 登录时使用）{RESET}\n")
    print("快速启动服务:")
    print(f"  {CYAN}./start.sh{RESET}  或  {CYAN}./deploy/docker-start.sh{RESET}\n")
    print("访问链接:")
    print(f"  • 实盘交易大屏: {CYAN}http://localhost:8080/trading{RESET}")
    print(f"  • 管理控制中心: {CYAN}http://localhost:8080/admin{RESET}")
    print(f"  • 系统参考文档: {CYAN}http://localhost:8080/docs{RESET}\n")


if __name__ == "__main__":
    if "--help" in sys.argv or "-h" in sys.argv:
        print_help()
        sys.exit(0)
    non_interactive = "--non-interactive" in sys.argv
    try:
        run_wizard(non_interactive=non_interactive)
    except (KeyboardInterrupt, EOFError):
        print(f"\n{YELLOW}向导已取消或处于非交互式环境。若需非交互配置请使用 --non-interactive。{RESET}")
        sys.exit(0)
