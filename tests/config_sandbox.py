"""Per-test configuration sandbox: patch source constants AND imported path aliases."""
import importlib
import os
import shutil
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch


def skip_if_offline_suite(test, reason='本用例以 spawn 子进程/网络栈为**被测行为**，'
                                       '离线守护下无法验证（skip ≠ fail，如实反映环境能力）'):
    """离线套件（`OFFLINE_SUITE_RUNNING`）下跳过"以 spawn 为被测对象"的用例。

    第六十一刀立规矩（守卫必须在 spawn **之前**）、第七十八刀推广成共享 helper：
    护栏挡子进程是**本职**，这类用例与护栏天然冲突 —— 在离线环境它们
    "测不了"而非"测不过"，如实 skip 才不污染守护基线。
    """
    if os.environ.get("OFFLINE_SUITE_RUNNING"):
        test.skipTest(reason)


#: 沙箱**负责**的模块白名单（原先是内联在 `isolate_config` 里的字面元组）。
#: 为什么提出来：`tests/audit/test_sandbox_is_fixture_complete.py` 需要按**同一份**清单
#: 去核查"哪些生产配置在沙箱里被静默清空"。此前那道门扫的是 `sys.modules` 里所有
#: 命中前缀的模块 ⇒ 清空集合随**测试收集顺序**变化，门禁自己变成"单跑绿、全量红"
#: （实测）。清单同源之后，"被清空的配置"是确定的。
#: 增删本清单 = 改变沙箱管辖范围，请同时更新上述门禁的声明桶。
SANDBOXED_MODULES = (
    'astra_backend.llm_manager',
    'astra_backend.council_manager',
    'astra_backend.policy_snapshot',
    'astra_backend.interceptor_manager',
    'scripts.prompt_library',
    'scripts.evolution_shield',
    'astra_gateway.secrets',
    'astra_backend.dashboard_cache',
    'astra_backend.risk_reservation',
    'astra_backend.account_baseline',
    'astra_backend.admin_auth',
    'astra_backend.backup_secrets',
    'astra_backend.backup_store',
    'astra_backend.exchanges.env_profiles',
    'astra_backend.exchanges.routing_policy',
    'astra_backend.qq_gateway_daemon',
    'astra_backend.routers.dashboard',
    'astra_backend.routers.strategy',
    'astra_backend.schedule_store',
    'scripts.archive_ledger',
    'astra_gateway.agents',
    'astra_gateway.publisher',
    'astra_gateway.supervisor',
    'astra_gateway.worker',
)


def isolate_config(test):
    temp = tempfile.TemporaryDirectory(prefix='astra-test-config-')
    test.addCleanup(temp.cleanup)
    root = Path(temp.name)
    project = Path(__file__).resolve().parents[1]
    # ⚠️ 第七十六刀：让**子进程**也被沙箱接管。
    # `run_script`（astra_backend/spawn.py）不传 env → 子进程继承父进程 os.environ。
    # 设置 ASTRA_DATA_DIR 后，尊重它的脚本（factor_library / news_sentiment_harvester /
    # sync_full_ledger，均实测为被测试拉起的 data/ 写入者）把写入指向沙箱。
    # **生产从不设置该变量** ⇒ 行为逐位不变（见各脚本注释）。
    # 修复的是 §88/§91.6 登记的"测试经后台子进程写生产文件"泄漏。
    import os as _os
    _env_key = "ASTRA_DATA_DIR"
    _prev = _os.environ.get(_env_key)
    _os.environ[_env_key] = str(root / "data")

    def _restore_env():
        if _prev is None:
            _os.environ.pop(_env_key, None)
        else:
            _os.environ[_env_key] = _prev
    test.addCleanup(_restore_env)
    # ⚠️⚠️ 第二百三十六刀（2026-09-27）：沙箱必须**夹具完整**，不能只是"目录可写"。
    #
    # 本函数此前只把 data/ 路径重定向到一个**空**目录。于是任何"按 `PATH.exists()`
    # 分支、或按配置值走不同分支"的生产代码，在隔离窗口里会静默落到**内置默认**。
    # 实测（探针留在 `tests/audit/test_sandbox_is_fixture_complete.py`）：
    #   `routing_policy.ROUTING_FILE` 从会话沙箱的夹具（exists=True）
    #   变成 `<per-test>/data/venue_routing.json`（exists=False），
    #   于是 `load_venue_pool("gate")` 从 `dry_run=False, assets=8`
    #   变成 `dry_run=True, assets=0` —— **实盘姿态被判成本地演算**。
    # 那不是隔离，那是**悄悄换了一套配置**；本仓那批"stage 漂移"红例
    #   （`venue_dry_run != protective/leverage/sizing`）就是踩在这个坑上。
    #
    # 修法：把**会话级配置沙箱**里的夹具文件原样继承到本沙箱的同名相对路径。
    # 为什么是"继承夹具"而不是"复制生产"：本仓既有政策是**把形状/常量抄成
    # 固定夹具，而不是每次去读生产**（见 `tests/__init__.py` 里池夹具的注释）——
    # 复制生产会让用例随线上配置漂移而红。夹具是静态的：继承它既确定、又不丢语义。
    try:
        from tests import session_sandbox_roots
        for _sroot in session_sandbox_roots():
            for _src in _sroot.rglob("*"):
                if not _src.is_file():
                    continue
                _rel = _src.relative_to(_sroot)
                # ⚠️ 两个沙箱**布局不同**，必须都补：会话沙箱是**扁平**放的
                #    （`<sroot>/venue_routing.json`），而本函数把生产 `project/data`
                #    映射成 `<root>/data/…`。第一版只按 `_rel` 复制 ⇒ 夹具落在
                #    `<root>/venue_routing.json`，而被重定向的常量指向
                #    `<root>/data/venue_routing.json` —— 于是"补了等于没补"，
                #    探针复现依旧是 `dry_run=True, assets=0`（实测）。
                for _dst in (root / "data" / _rel, root / _rel):
                    if _dst.exists():
                        continue    # 本沙箱已有的（用例自己写的）优先，绝不覆盖
                    _dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(_src, _dst)
    except Exception:
        # 沙箱继承失败不该把用例炸掉：会话沙箱未启用（ALLOW_REAL_DATA）时本就为空。
        pass
    # ⚠️⚠️ 第八十刀（顺序即 bug）：必须发生在**下面的白名单 import 之前** ——
    # `astra_backend/dashboard_cache.py` 模块**顶层末尾**就有 `start_dashboard_background_worker()`
    # （L549，实测），于是"import astra_backend.dashboard_cache"这个动作本身就点起
    # **每 2 秒跑一次 `update_cache_cycle()` 的 daemon worker**：
    #   · 非离线：worker 在**任何测试的 patch 窗口之外**真外呼
    #     www.okx.com（balances/positions/pending_orders ×每 2s）——
    #     这是 11+ 个路由测试文件"按文件扫全泄漏"的共同源头，
    #     连不碰 dashboard 的用例（如 test_config_sandbox）都被波及；
    #   · 离线：socket 守护把它拦成 fail-soft ⇒ 多年无人察觉。
    # 压制 `_fetch_json` 只盖住 patch 存活的窗口；**根治 = 关掉 worker 循环**
    # （`_BG_WORKER_RUNNING` 每轮检查，stop 后 ≤2s 线程自然退出）。
    # 生产不受影响：web 进程经 astra_backend/app.py 的 lifespan 启动它，
    # 且测试进程里这个 worker 从来不是被测对象。
    # 要真测 fetch 的文件自己再 patch.object 覆盖（mock 栈 LIFO，后装优先）。
    try:
        import astra_backend.dashboard_cache as _dash_mod
    except Exception:
        _dash_mod = None
    if _dash_mod is not None:
        try:
            _dash_mod.stop_dashboard_background_worker()
        except Exception:
            pass
        if callable(getattr(_dash_mod, "_fetch_json", None)):
            _p_fetch = patch.object(
                _dash_mod, "_fetch_json",
                lambda *a, **k: (False, None, "tests 沙箱已压制出站取数（isolate_config）"))
            _p_fetch.start(); test.addCleanup(_p_fetch.stop)
    for name in SANDBOXED_MODULES:
        importlib.import_module(name)
    # Patch every already-bound alias, not just the defining module (law 2).
    # 白名单必须覆盖**顶层名**形式的兄弟模块：`scripts/` 在 sys.path 上，脚本以
    # `import ai_brain_trader` 引入的是与 `scripts.ai_brain_trader` 不同的模块实例，
    # 不在白名单里就完全不被重定向 → 测试会写生产 data/（如 ai_brain_last_prompt.txt、
    # system_prompt_override.txt）。批2 P1-3 回归测试就是被这条断言抓出来的。
    for name, module in list(sys.modules.items()):
        if not module or name.startswith('tests'):
            continue
        if not (name.startswith(('astra_backend.', 'astra_gateway.', 'scripts.',
                                 'dashboard.')) or
                name in ('prompt_library', 'evolution_shield', 'ai_brain_trader', 'ai_factor_trader')):
            continue
        for key, value in list(vars(module).items()):
            if not key.isupper() or not isinstance(value, (str, Path)):
                continue
            try:
                relative = Path(value).relative_to(project / 'data')
            except ValueError:
                # ⚠️ 第二百三十五刀：会话级配置沙箱（`tests/__init__.py`）会把
                # `prompt_library.BASELINE_FILE` / `LOCAL_FILE` 之类的常量挪到 /tmp 下 —— 那些值不在
                # `project/data` 前缀里，按原规则会被**跳过**，于是本沙箱反而"管不到"它们
                # （实测 `test_config_sandbox.py::test_nested_policy_paths_share_one_sandbox`
                # 就是这么红的）。这里把会话沙箱下的常量**接管**进来：更具体的沙箱优先。
                from tests import session_sandbox_roots

                relative = None
                for sroot in session_sandbox_roots():
                    try:
                        relative = Path(value).relative_to(sroot)
                    except ValueError:
                        continue
                    break
                if relative is None:
                    continue
            target = root / 'data' / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            replacement = str(target) if isinstance(value, str) else target
            p = patch.object(module, key, replacement)
            p.start(); test.addCleanup(p.stop)
    app = sys.modules.get("astra_backend.app")
    if app is not None:
        git_probe = patch.object(app, "git", side_effect=lambda args: (
            "0 0" if args[0] == "rev-list" else "test" if args[0] == "branch" else
            "" if args[0] in ("fetch", "status") else "abc1234"))
        git_probe.start(); test.addCleanup(git_probe.stop)
    # ⚠️ 只重定向常量还不够：`risk_reservation.get_manager()` 缓存了进程级实例，
    # 一旦某次未沙箱调用先建了实例，它会**永久指向生产库**（实测污染源）。
    # 清缓存才能让新常量真正生效。
    try:
        import astra_backend.risk_reservation as _rr
        _rr.reset_default_manager()
    except Exception:
        pass

    return root
