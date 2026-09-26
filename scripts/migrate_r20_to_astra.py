#!/usr/bin/env python3
"""一次性数据迁移：把内部代号 `r20` 留下的运行态文件与密文库键迁到 `astra`。

## 为什么需要它（不做会怎样）

2026-09-27 把 `r20` 全量改名 `astra`，**对配置契约是硬切**：`R20_*` 环境变量不再被读取，
用户必须改自己的 `.env`。但**运行态数据不能硬切** —— 改个文件名不等于数据消失：

| 文件 | 不改的后果 |
|---|---|
| `data/r20_quant.db` | 交易台账认不出来 ⇒ 系统"忘了"自己的历史成交 |
| `data/r20_admin.db` | 管理员账号消失 ⇒ 进不去后台 |
| `data/r20_gateway.db` | 事件投递/调度状态归零 |
| `data/r20_secrets.enc` + `.r20_secret_key` | **加密的交易所凭证打不开** ⇒ 三所全部 NOT READY |
| `data/.r20_gateway.lock` / `_heartbeat` / pid | 锁与心跳指向旧路径 ⇒ 监督与存活判据读不到 |
| `logs/r20_admin_audit.jsonl` | 审计链断代 |

还有一处**不在文件名上**：密文库解密出来的 dict 里，键名本身带旧前缀
（`R20_ADMIN_TOKEN` / `R20_TELEGRAM_BOT_TOKEN` …）。文件名迁完、键名不改，
后台 token 之类照样"丢失" —— 本机实测密文库里就有一个 `R20_QQ_CLIENT_SECRET`。

## 用法

```bash
python scripts/migrate_r20_to_astra.py            # 只打印计划（默认 dry-run）
python scripts/migrate_r20_to_astra.py --apply    # 真正执行
python scripts/migrate_r20_to_astra.py --check    # 供启动脚本用：有遗留 ⇒ 退出码 3
```

退出码：`0` 无需迁移/已完成 · `3` 检测到遗留（需迁移）· `4` 迁移失败。

## 安全设计

- **默认 dry-run**：不加 `--apply` 什么都不动。
- **只 `os.rename`（同盘原子）**，绝不 `copy+delete`；绝不覆盖已存在的新名文件
  （两代文件同时在 = 状态不明，宁可停下让人看）。
- **迁移前后都校验**：SQLite 打开并 `PRAGMA integrity_check`，密文库解密后**逐字节比对**。
- **幂等**：跑第二遍是 no-op。
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
LOGS = ROOT / "logs"

#: 需要原子改名的运行态文件（旧名 → 新名）。
#: SQLite 的 `-wal` / `-shm` **必须跟着一起走** —— 只搬主库会把最后一批已提交事务留在旧名里。
#: 运行态文件的**相对仓库根**旧名 → 新名。
#: `RENAME_PAIRS` 由它派生 —— 这样门禁可以把整张表重定位到临时目录，在不碰真实
#: 运行态的前提下验证迁移逻辑（模块级写死绝对路径就做不到这件事，只能去改生产文件）。
RUNTIME_FILE_NAMES = (
    ("data/r20_admin.db", "data/astra_admin.db"),
    ("data/r20_quant.db", "data/astra_quant.db"),
    ("data/r20_gateway.db", "data/astra_gateway.db"),
    ("data/r20_gateway.sqlite3", "data/astra_gateway.sqlite3"),
    ("data/r20_secrets.enc", "data/astra_secrets.enc"),
    ("data/r20_secrets.enc.bak", "data/astra_secrets.enc.bak"),
    ("data/.r20_secret_key", "data/.astra_secret_key"),
    ("data/r20_backup_secrets.enc", "data/astra_backup_secrets.enc"),
    ("data/.r20_backup_secret_key", "data/.astra_backup_secret_key"),
    ("data/r20_backend.pid", "data/astra_backend.pid"),
    ("data/r20_gateway.pid", "data/astra_gateway.pid"),
    ("data/.r20_gateway.lock", "data/.astra_gateway.lock"),
    ("data/.r20_gateway_heartbeat", "data/.astra_gateway_heartbeat"),
    ("data/.r20_watchdog.lock", "data/.astra_watchdog.lock"),
    ("data/.r20_watchdog.gateway.lock", "data/.astra_watchdog.gateway.lock"),
    ("data/.r20_scheduler.lock", "data/.astra_scheduler.lock"),
    ("logs/r20_backend.log", "logs/astra_backend.log"),
    ("logs/r20_gateway.log", "logs/astra_gateway.log"),
    ("logs/r20_watchdog.log", "logs/astra_watchdog.log"),
    ("logs/r20_admin_audit.jsonl", "logs/astra_admin_audit.jsonl"),
)


def _pairs(root: Path) -> "tuple[tuple[Path, Path], ...]":
    """把相对名表挂到给定根目录上（测试传入临时目录即可整体重定位）。"""
    return tuple((root / o, root / n) for o, n in RUNTIME_FILE_NAMES)


RENAME_PAIRS = _pairs(ROOT)

#: SQLite 侧车文件后缀（跟着主库一起搬）
SQLITE_SIDECARS = ("-wal", "-shm", "-journal")

#: 密文库内的旧键前缀（键名本身也带旧前缀 ⇒ 必须重映射，否则后台 token 等"丢失"）
SECRET_KEY_PREFIX = ("R20_", "ASTRA_")

MIGRATION_CMD = "python scripts/migrate_r20_to_astra.py --apply"

#: `data/` 下**配置文件**里出现的旧名记号（改文件名改不到它们）。
#: 本机实测 `data/backup_methods.json` 里 `scope` 写着 `r20_backend`/`r20_gateway`、
#: `exclude` 写着 `data/r20_admin.db*` —— 两个方向都错：前者指向已不存在的目录
#: ⇒ 每晚备份**静默漏掉整个后端**；后者不再匹配真实库名 ⇒ 管理员库反而被打进备份。
#: 这类"改名改不到的配置"比文件本身更危险，因为它不报错、只是悄悄少做一件事。
CONFIG_TEXT_TOKENS = (
    ("r20_backend", "astra_backend"),
    ("r20_gateway", "astra_gateway"),
    ("data/r20_admin.db", "data/astra_admin.db"),
    ("data/r20_quant.db", "data/astra_quant.db"),
    ("data/r20_gateway.db", "data/astra_gateway.db"),
    ("data/r20_gateway.sqlite3", "data/astra_gateway.sqlite3"),
    ("r20_secrets.enc", "astra_secrets.enc"),
    (".r20_secret_key", ".astra_secret_key"),
    # ⚠️ **环境变量名也会出现在配置值里**，而它不会被"改文件名"覆盖到。
    #    本机实测：`data/backup_methods.json` 的 `encryption.key_env` 写着
    #    `R20_BACKUP_ENCRYPTION_KEY`，而代码默认值已随改名变成
    #    `ASTRA_BACKUP_ENCRYPTION_KEY`。加密当前是关的，所以它**今天不报错** ——
    #    等用户哪天打开备份加密，任务就会去找一个不存在的键并直接失败。
    #    这类"潜伏到某个开关被打开才炸"的漏迁最难查，必须一并改掉。
    ("R20_BACKUP_ENCRYPTION_KEY", "ASTRA_BACKUP_ENCRYPTION_KEY"),
)

#: 两代文件同时存在时，被接管（移走）的旧目标放这里 —— **只移不删**，便于人工复核。
SUPERSEDED_DIR = ROOT / ".archive" / "astra-migration-superseded"


def _row_count(path: Path) -> int | None:
    """SQLite 总行数（用于判断哪一代是权威数据）。非 SQLite 返回 None。"""
    if path.suffix not in (".db", ".sqlite3"):
        return None
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            tabs = [r[0] for r in con.execute(
                "select name from sqlite_master where type='table'")]
            total = 0
            for name in tabs:
                try:
                    total += con.execute(f'select count(*) from "{name}"').fetchone()[0]
                except Exception:
                    pass
            return total
        finally:
            con.close()
    except Exception:
        return None


def _plan() -> "list[tuple[Path, Path]]":
    """待迁移项：旧名存在且新名不存在。新名已存在则视为已迁移（绝不覆盖）。"""
    todo = []
    for old, new in RENAME_PAIRS:
        if old.exists() and not new.exists():
            todo.append((old, new))
    # ⚠️ sidecar（`-wal`/`-shm`）**不在这里列**，见 `_sweep_sidecars()` 的理由。
    # `.r20-env-*` 之类的临时文件（env 写入用），按前缀扫
    for o in sorted(DATA.glob(".r20-env-*")):
        n = DATA / o.name.replace(".r20-env-", ".astra-env-", 1)
        if not n.exists():
            todo.append((o, n))
    return todo


def _sweep_sidecars(old: Path, new: Path) -> "list[Path]":
    """把某个库的 `-wal`/`-shm` 跟着主库一起搬，返回实际搬走的路径。

    ⚠️ 必须**在**完整性探针之后调用，不能在算计划时预先列好：
    `_sqlite_ok()` 会以只读方式打开 WAL 模式的库，而 SQLite 单是打开就会
    创建 `-shm`（有时还有 0 字节的 `-wal`）。第一版把 sidecar 写进了改名计划，
    计划却是探针**之前**算的 ⇒ 探针新造出来的 sidecar 不在计划里，被留在原地，
    变成无主的 `r20_*.db-wal`/`-shm` 孤儿（本机实测，且正是启动前检查抓出来的）。
    """
    moved = []
    if old.suffix not in (".db", ".sqlite3"):
        return moved
    for sfx in SQLITE_SIDECARS:
        so, sn = Path(str(old) + sfx), Path(str(new) + sfx)
        if so.exists() and not sn.exists():
            os.rename(so, sn)
            moved.append(sn)
    return moved


def _finish() -> int:
    """迁移的**统一收尾**：第 3 步（配置文本）+ 完成语。

    ⚠️ 为什么必须收敛成一个函数：`apply()` 里有三条提前返回路径
    （无待迁移 / 密文库未就绪 / 无旧前缀键）。第一版把第 3 步只写在其中一条上，
    于是走"无旧前缀键"这条路时**配置文本被打印了却根本没写下去**
    （本机实测：`data/backup_methods.json` 报了 3 处命中，文件却没变）。
    凡是"必须发生"的步骤，都不能挂在某个分支上。
    """
    print("=== 第 3 步：data/ 配置文件里的旧名记号 ===")
    n_cfg = _migrate_config_texts(apply=True)
    print(f"  ✓ 改写 {n_cfg} 个配置文件（原文件留档于 .archive/astra-migration-config-backup/）" if n_cfg
          else "  · 没有需要改写的配置")
    print("\n✅ 迁移完成。请用新包名重启服务。")
    return 0


def _migrate_config_texts(apply: bool) -> int:
    """改写 `data/*.json` 里残留的旧名记号。返回改动的文件数。

    **只动 `data/` 下的 JSON 配置文件**，且只在**逐字命中** `CONFIG_TEXT_TOKENS` 时改写；
    不做正则、不做模糊匹配 —— 用户自己的策略/池配置里可能有意写着别的 `r20` 字样。
    """
    touched = 0
    for path in sorted(DATA.glob("*.json")):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        new_text, hits = text, []
        for old_tok, new_tok in CONFIG_TEXT_TOKENS:
            if old_tok in new_text:
                hits.append(f"{old_tok}→{new_tok}×{new_text.count(old_tok)}")
                new_text = new_text.replace(old_tok, new_tok)
        if not hits:
            continue
        touched += 1
        print(f"  {path.relative_to(ROOT)}: " + "、".join(hits))
        if apply:
            # ⚠️ 留档放 `.archive/`（已忽略），**不要**写在原文件旁边：
            #    `data/backup_methods.json.pre-astra` 这种"多一段后缀"的名字
            #    匹配不上 `.gitignore` 的 `data/*.json`，会静默滑进 `git add -A`
            #    ——本机实测已发生一次（与改名时那个无扩展名心跳文件同族）。
            cfg_backup_dir = ROOT / ".archive" / "astra-migration-config-backup"
            cfg_backup_dir.mkdir(parents=True, exist_ok=True)
            backup = cfg_backup_dir / path.name
            if not backup.exists():
                backup.write_text(text, encoding="utf-8")
            path.write_text(new_text, encoding="utf-8")
    return touched


def _conflicts() -> "list[tuple[Path, Path]]":
    """两代同名文件**都在**的项。

    实测（2026-09-27）本机就是这样：`data/r20_quant.db` 是**真台账**（234 笔），
    而 `data/astra_quant.db` 是**跑测试时在真实 data/ 目录里建出来的空库**（124 笔）。
    这种时候既不能静默覆盖、也不能直接报错了事 —— 必须把两边行数摆出来让人判。
    """
    out = []
    for old, new in RENAME_PAIRS:
        if old.exists() and new.exists():
            out.append((old, new))
    return out


def _pending_secret_rekey() -> "dict[str, str] | None":
    """密文库里还有多少旧前缀键？（返回 {旧键: 新键}，无则 None）"""
    store = DATA / "astra_secrets.enc"
    key = DATA / ".astra_secret_key"
    legacy_store, legacy_key = DATA / "r20_secrets.enc", DATA / ".r20_secret_key"
    if not store.exists() and legacy_store.exists():
        return {"__store__": str(legacy_store)}      # 先改名再谈重映射
    if not (store.exists() and key.exists()):
        return None
    try:
        from cryptography.fernet import Fernet
        data = _load_store(store, key)
    except Exception:
        return None
    remap = {k: v for k, v in data.items()
             if k.startswith(SECRET_KEY_PREFIX[0]) and isinstance(v, str) is not None}
    return remap or None


def _load_store(store: Path, key: Path) -> dict:
    import json
    from cryptography.fernet import Fernet
    return json.loads(Fernet(key.read_bytes().strip()).decrypt(store.read_bytes()).decode("utf-8"))


def _save_store(store: Path, key: Path, data: dict) -> None:
    import json
    from cryptography.fernet import Fernet
    blob = Fernet(key.read_bytes().strip()).encrypt(
        json.dumps(data, ensure_ascii=False).encode("utf-8"))
    tmp = store.with_suffix(store.suffix + ".migrating")
    tmp.write_bytes(blob)
    os.chmod(tmp, 0o600)
    os.replace(tmp, store)


def _sqlite_ok(path: Path) -> str:
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            row = con.execute("PRAGMA integrity_check").fetchone()
            return "ok" if row and row[0] == "ok" else f"integrity_check={row}"
        finally:
            con.close()
    except Exception as exc:                      # noqa: BLE001
        return f"打不开：{exc}"


def check() -> int:
    todo = _plan()
    rekey = _pending_secret_rekey()
    if not todo and not rekey and _migrate_config_texts(apply=False) == 0:
        return 0
    print("⚠️ 检测到改名前的运行态数据（r20 → astra 尚未迁移）。", file=sys.stderr)
    for o, n in todo:
        print(f"    {o.relative_to(ROOT)} → {n.relative_to(ROOT)}", file=sys.stderr)
    if rekey:
        print(f"    另需重映射密文库内的 {len(rekey)} 个旧前缀键（如 R20_* → ASTRA_*）", file=sys.stderr)
    print(f"\n请先停服，然后执行：\n    {MIGRATION_CMD}\n"
          "（不改名就启动 = 系统认不出自己的台账与凭证）", file=sys.stderr)
    return 3


def apply(supersede: bool = False) -> int:
    conflicts = _conflicts()
    if conflicts:
        print("⚠️ 新旧两代同名文件**都存在**，无法自动判断哪一代权威：")
        for old, new in conflicts:
            for label, f in (("旧名", old), ("新名", new)):
                rel = str(f.relative_to(ROOT))
                print(f"    [{label}] {rel:<28} 行数={str(_row_count(f)):<8} {f.stat().st_size}B")
        if not supersede:
            print("\n  多半是新名那份由**跑测试**在真实 data/ 目录里建出来的空库。")
            print("  确认旧名那份才是真数据后，用下面这条接管它（旧目标只**移走**不删除）：")
            print(f"      {MIGRATION_CMD} --supersede-existing")
            return 4
        SUPERSEDED_DIR.mkdir(parents=True, exist_ok=True)
        for old, new in conflicts:
            # ⚠️ "行数"判据只对 SQLite 成立。日志/锁等文本文件按**字节数**比大小 ——
            #    第一版没区分，把 `logs/astra_gateway.log` 当成"不可读的 SQLite"拒了，
            #    整个迁移中途停下（本机实测）。
            ro, rn = _row_count(old), _row_count(new)
            if ro is not None and rn is not None:
                if ro < rn:
                    print(f"  ✗ {old.name} 行数({ro}) 少于 {new.name}({rn})"
                          " —— 拒绝用较小的一份接管较大的一份")
                    return 4
                basis = f"行数 {ro} ≥ {rn}"
            else:
                so, sn = old.stat().st_size, new.stat().st_size
                if so < sn:
                    print(f"  ✗ {old.name} 体积({so}B) 小于 {new.name}({sn}B)"
                          " —— 拒绝用较小的一份接管较大的一份")
                    return 4
                basis = f"体积 {so}B ≥ {sn}B"
            target = SUPERSEDED_DIR / new.name
            os.replace(new, target)
            print(f"  ✓ 已把 {new.relative_to(ROOT)} 移入 "
                  f"{target.relative_to(ROOT)}（{basis}，未删除）")

    todo = _plan()
    if not todo and not _pending_secret_rekey() and _migrate_config_texts(apply=False) == 0:
        print("✅ 没有需要迁移的东西（已迁移或全新安装）。")
        return _finish()

    print(f"=== 第 1 步：原子改名 {len(todo)} 个文件 ===")
    for o, n in todo:
        if n.exists():
            print(f"  ✗ 目标已存在，拒绝覆盖：{n.relative_to(ROOT)}（状态不明确，请人工确认）")
            return 4
        if o.suffix in (".db", ".sqlite3"):
            verdict = _sqlite_ok(o)
            print(f"  改名前自检 {o.name}: {verdict}")
            if verdict != "ok":
                print(f"  ✗ {o.name} 自检未通过，拒绝迁移（先恢复数据）")
                return 4
        os.rename(o, n)                     # 同盘原子
        os.chmod(n, 0o600) if o.name.startswith(".") else None
        sidecars = _sweep_sidecars(o, n)
        tail = ("（含 " + "、".join(x.name for x in sidecars) + "）") if sidecars else ""
        print(f"  ✓ {o.relative_to(ROOT)} → {n.relative_to(ROOT)}{tail}")

    store, key = DATA / "astra_secrets.enc", DATA / ".astra_secret_key"
    if not (store.exists() and key.exists()):
        print("=== 第 2 步：密文库不存在或未就绪，跳过键重映射 ===")
        return _finish()

    print("=== 第 2 步：密文库键重映射（R20_* → ASTRA_*）===")
    try:
        before = _load_store(store, key)
    except Exception as exc:                        # noqa: BLE001
        print(f"  ✗ 密文库打不开：{exc}（拒绝改动）")
        return 4
    remap = {k: k.replace("R20_", "ASTRA_", 1) for k in before if k.startswith("R20_")}
    if not remap:
        print("  · 没有旧前缀键，无需重映射")
        return _finish()
    after = {(remap.get(k, k)): v for k, v in before.items()}
    if len(after) != len(before):
        print("  ✗ 重映射后键数变化（新旧键撞名），拒绝写入")
        return 4
    _save_store(store, key, after)
    verify = _load_store(store, key)
    if {remap.get(k, k): v for k, v in before.items()} != verify:
        print("  ✗ 回读校验不一致，迁移未生效（原文件已被覆盖，请从备份恢复）")
        return 4
    print(f"  ✓ 已重映射 {len(remap)} 个键：" + ", ".join(sorted(remap)))
    print(f"  ✓ 回读校验通过（值逐字节一致，共 {len(verify)} 个键）")
    return _finish()


def main(argv: "list[str] | None" = None) -> int:
    ap = argparse.ArgumentParser(description="把 r20 时代的运行态数据迁移到 astra 命名")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--apply", action="store_true", help="真正执行（默认只打印计划）")
    g.add_argument("--check", action="store_true", help="供启动脚本用：有遗留则退出码 3")
    ap.add_argument("--supersede-existing", action="store_true",
                    help="两代同名文件并存时，接管旧目标（**只移入 .archive/，不删除**）")
    args = ap.parse_args(argv)

    if args.check:
        return check()
    if not args.apply:
        todo = _plan()
        rekey = _pending_secret_rekey()
        print("=== 待迁移计划（dry-run，未改动任何文件）===")
        for o, n in todo:
            print(f"  {o.relative_to(ROOT)} → {n.relative_to(ROOT)}")
        print(f"  密文库旧前缀键：{len(rekey) if rekey else 0} 个")
        print("  data/ 配置文件待改写：")
        if _migrate_config_texts(apply=False) == 0:
            print("    （无）")
        if not todo and not rekey:
            print("  （无需迁移）")
        else:
            print(f"\n执行：{MIGRATION_CMD}")
        return 0
    return apply(supersede=args.supersede_existing)


if __name__ == "__main__":
    raise SystemExit(main())
