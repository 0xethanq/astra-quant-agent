"""部署脚本与 Docker 交付物必须"真的能起来"（2026-09-30 新增）。

## 为什么值得一条门

部署脚本是**唯一一类"坏了就完全用不了、但单测全绿"**的文件：它们不在 Python
导入图里，`pytest` 也不会加载它们。实测在本仓踩过一次真问题：

    `start.sh` 硬要求 PATH 里有 `python3`，没有就打 "python3 is not installed" 退出。
    但本仓**刻意不依赖全局 Python**（AGENTS.md：所有 Python 命令走 `.venv`）。
    于是在"只有 .venv、没有全局 python3"的机器上（例如本项目自己的开发容器），
    `./start.sh` **直接起不来**，而报错还是错的 —— 解释器明明就在 `.venv` 里。
    更微妙的是同一个文件里已经有一处用了 `.venv/bin/python`：脚本**自我矛盾**。

这类问题静态就能查，且查一次能挡住整类回归，故在此钉住。

## 本文件守住的不变量

| 不变量 | 失败后果 |
|---|---|
| 启动脚本自适应解释器（venv 优先） | 用户"依赖装好了却起不来"，且被误导去装全局 Python |
| 所有 shell 脚本语法正确 | 脚本根本跑不到第一行 |
| Dockerfile 的 COPY 源都存在 | `docker build` 中途失败 |
| `.dockerignore` 排除凭证/运行态、放行提示词基线 | 把密钥打进镜像 / 镜像里没有出厂提示词 |
| compose 两个服务都有健康探测、gateway 依赖 backend 健康 | "看板正常但不下单"，静默停摆 |
| entrypoint 对 `.env` 被挂成目录 fail-closed | 配置永远存不上，用户以为改了其实没改 |
"""
from __future__ import annotations

import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

START_SH = ROOT / "start.sh"
START_PS1 = ROOT / "start.ps1"
DOCKERFILE = ROOT / "Dockerfile"
DOCKERIGNORE = ROOT / ".dockerignore"
COMPOSE = ROOT / "docker-compose.yml"
ENTRYPOINT = ROOT / "deploy" / "docker-entrypoint.sh"
DOCKER_START = ROOT / "deploy" / "docker-start.sh"
WATCHDOG = ROOT / "scripts" / "astra_watchdog.sh"

#: 启动脚本里**不许**出现的裸解释器调用（会绕过 .venv）。
_BARE_PYTHON = re.compile(r"(?<![\w/.\"-])python3(?![\w/])")


def _strip_comments(text: str) -> str:
    """去掉整行注释，避免"注释里提到 python3"被当成真调用。"""
    return "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("#"))


class StartupScriptsResolveInterpreterTests(unittest.TestCase):
    """★ 核心回归：启动脚本必须自适应解释器，不得硬依赖全局 python3。"""

    def test_start_sh_prefers_the_project_venv(self):
        src = _strip_comments(START_SH.read_text(encoding="utf-8"))
        self.assertIn(".venv/bin/python", src,
                      "start.sh 必须优先使用项目 .venv 的解释器")
        # 出现在"候选列表"里，而不是只在注释里被提及
        self.assertRegex(src, r"for\s+cand\s+in\s+.*\.venv/bin/python",
                         "start.sh 应把 .venv/bin/python 作为首选的候选解释器")

    def test_start_sh_does_not_hard_require_global_python3(self):
        src = _strip_comments(START_SH.read_text(encoding="utf-8"))
        # 旧实现是 `if ! command -v python3 ...; then echo "python3 is not installed"; exit 1`
        self.assertNotRegex(
            src, r"command -v python3[\s\S]{0,80}exit 1",
            "start.sh 不得因为 PATH 里没有 python3 就直接退出 —— 本仓刻意不依赖全局 Python")

    def test_start_sh_launches_with_the_resolved_interpreter(self):
        src = _strip_comments(START_SH.read_text(encoding="utf-8"))
        launch = [ln for ln in src.splitlines() if "uvicorn" in ln and "exec" in ln]
        self.assertTrue(launch, "start.sh 里找不到启动 uvicorn 的那一行")
        for ln in launch:
            self.assertNotRegex(ln, _BARE_PYTHON,
                                f"启动行绕过了 .venv 解释器: {ln.strip()}")
            self.assertIn('"$PY"', ln, f"启动行必须用解析出的 $PY: {ln.strip()}")

    def test_start_sh_reports_the_interpreter_it_chose(self):
        """不能静默选择：出错时要能一眼看出用的是哪个解释器。"""
        src = START_SH.read_text(encoding="utf-8")
        self.assertRegex(src, r'echo\s+"[^"]*\$PY',
                         "start.sh 必须回显它选中的解释器（排障要用）")

    def test_windows_launcher_uses_the_venv_too(self):
        src = START_PS1.read_text(encoding="utf-8")
        self.assertIn(r".venv\Scripts\python.exe", src,
                      "start.ps1 必须使用 .venv 的解释器")
        self.assertNotRegex(_strip_comments(src), _BARE_PYTHON,
                            "start.ps1 不得调用裸 python3")

    def test_every_shell_script_is_syntactically_valid(self):
        scripts = sorted(ROOT.glob("*.sh")) + sorted((ROOT / "deploy").glob("*.sh")) \
            + sorted((ROOT / "scripts").glob("*.sh"))
        self.assertGreater(len(scripts), 3, "没扫到 shell 脚本 —— 本用例会空转")
        for path in scripts:
            proc = subprocess.run(["bash", "-n", str(path)],
                                  capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0,
                             f"{path.relative_to(ROOT)} 语法错误:\n{proc.stderr}")


class DockerfileTests(unittest.TestCase):
    def test_copy_sources_exist(self):
        text = DOCKERFILE.read_text(encoding="utf-8")
        missing = []
        for m in re.finditer(r"^COPY\s+(?:--from=\S+\s+)?(.+)$", text, re.M):
            for src in m.group(1).split()[:-1]:
                if src.startswith("--") or src.startswith("/") or "*" in src:
                    continue
                if not (ROOT / src).exists():
                    missing.append(src)
        self.assertEqual(missing, [], f"Dockerfile 的 COPY 源不存在: {missing}")

    def test_image_ships_the_prompt_baseline(self):
        """出厂提示词基线必须进镜像，否则容器里提示词是空的。"""
        text = DOCKERFILE.read_text(encoding="utf-8")
        self.assertIn("data/prompt_library.json", text,
                      "镜像必须带上 data/prompt_library.json（提示词正文的唯一事实源）")
        di = DOCKERIGNORE.read_text(encoding="utf-8").splitlines()
        self.assertIn("!data/prompt_library.json", di,
                      ".dockerignore 必须为提示词基线开例外（data/ 整目录被排除了）")

    def test_build_and_entrypoint_are_wired(self):
        text = DOCKERFILE.read_text(encoding="utf-8")
        self.assertIn("EXPOSE 8080", text)
        self.assertIn("deploy/docker-entrypoint.sh", text, "Dockerfile 必须带上 entrypoint")
        self.assertRegex(text, r"ENTRYPOINT\s+\[", "必须用 exec 形式的 ENTRYPOINT（信号要能透传）")


class DockerignoreTests(unittest.TestCase):
    def test_secrets_and_runtime_state_never_enter_the_image(self):
        lines = [ln.strip() for ln in DOCKERIGNORE.read_text(encoding="utf-8").splitlines()]
        for must in (".env", ".venv", "data/", "logs/", "backups/"):
            self.assertIn(must, lines, f".dockerignore 必须排除 {must}")

    def test_the_prompt_baseline_exception_is_after_the_exclusion(self):
        """`.dockerignore` 是**顺序敏感**的：例外必须排在排除之后才生效。"""
        lines = [ln.strip() for ln in DOCKERIGNORE.read_text(encoding="utf-8").splitlines()]
        self.assertLess(lines.index("data/"), lines.index("!data/prompt_library.json"),
                        "例外必须写在 data/ 排除规则**之后**，否则不生效")


class ComposeTests(unittest.TestCase):
    """不依赖 pyyaml（它不是本仓依赖）—— 用结构化文本断言，够用且更稳。"""

    def setUp(self):
        self.text = COMPOSE.read_text(encoding="utf-8")

    def test_both_services_are_declared(self):
        for svc in ("backend:", "gateway:"):
            # ⚠️ 必须带 (?m)：不带多行标志时 `^` 只匹配**整个字符串**的开头，
            # 这种写法会永远失败（我第一版就踩了，记在这里免得后人重写一遍）。
            self.assertRegex(self.text, rf"(?m)^  {re.escape(svc)}", f"缺少服务 {svc}")

    def test_every_service_has_a_healthcheck(self):
        # 用缩进层级数 healthcheck：compose 里服务缩进 2 空格，其子键 4 空格
        blocks = re.split(r"\n  (?=\w[\w-]*:)", self.text)
        checked = 0
        for block in blocks[1:]:
            name = block.split(":")[0]
            self.assertIn("healthcheck:", block,
                          f"服务 {name} 没有健康探测 —— 挂了会静默停摆")
            checked += 1
        self.assertGreaterEqual(checked, 2, "没解析到服务块 —— 本用例会空转")

    def test_gateway_waits_for_a_healthy_backend(self):
        self.assertIn("service_healthy", self.text,
                      "gateway 必须等 backend 健康后再起（否则调度会打到没准备好的控制面）")

    def test_credentials_and_state_are_mounted_not_baked(self):
        for mount in ("./.env", "./data", "./logs", "./backups"):
            self.assertIn(mount, self.text, f"compose 必须挂载 {mount}")


class EntrypointTests(unittest.TestCase):
    def setUp(self):
        self.text = ENTRYPOINT.read_text(encoding="utf-8")

    def test_env_mounted_as_a_directory_fails_closed(self):
        """经典陷阱：宿主机没有 .env 时 Docker 会建同名**目录**挂进来。"""
        self.assertRegex(self.text, r'if\s+\[\s+-d\s+"\$ROOT_DIR/\.env"\s+\]',
                         "entrypoint 必须检测 .env 被挂成目录的情况")
        block = self.text[self.text.index('-d "$ROOT_DIR/.env"'):]
        self.assertIn("exit 1", block[:1200],
                      "检测到 .env 是目录时必须 fail-closed（静默跑半个程序更糟）")

    def test_supports_the_modes_compose_and_docs_reference(self):
        for mode in ("backend", "gateway", "all"):
            # 同理需要 (?m)：`case` 的分支在文件中部，不在字符串开头。
            self.assertRegex(self.text, rf"(?m)^\s*{mode}\|?\w*\)",
                             f"entrypoint 应支持 {mode} 模式（compose/docs 在用它）")

    def test_referenced_helper_files_exist(self):
        refs = set(re.findall(r'"\$ROOT_DIR/(scripts/[\w./-]+)"', self.text))
        self.assertTrue(refs, "没解析到 entrypoint 引用的辅助脚本 —— 本用例会空转")
        for rel in refs:
            if rel.endswith("migrate_r20_to_astra.py"):
                continue  # 该脚本按存在与否可选，缺失即跳过检查
            self.assertTrue((ROOT / rel).exists(), f"entrypoint 引用了不存在的 {rel}")

    def test_watchdog_fallback_is_adaptive(self):
        """看门狗解释器自适应 —— 这是 start.sh 该学的正确范式。"""
        src = WATCHDOG.read_text(encoding="utf-8")
        self.assertIn(".venv/bin/python3", src)
        self.assertIn("python3", src)


class OneClickLauncherTests(unittest.TestCase):
    def test_docker_launcher_corrects_the_env_directory_trap(self):
        text = DOCKER_START.read_text(encoding="utf-8")
        self.assertRegex(text, r'if\s+\[\s+-d\s+"\$ROOT_DIR/\.env"\s+\]',
                         "docker-start.sh 必须能纠正 .env 被误建为目录的情况")
        self.assertIn("rm -rf", text)

    def test_docker_launcher_verifies_compose_is_available(self):
        text = DOCKER_START.read_text(encoding="utf-8")
        self.assertIn("docker compose", text)
        self.assertIn("docker-compose", text, "应兼容独立的 docker-compose 命令")


if __name__ == "__main__":
    unittest.main()
