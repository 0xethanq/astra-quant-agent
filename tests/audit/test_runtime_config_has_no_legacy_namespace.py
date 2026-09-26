r"""运行态配置里不得再出现旧命名空间（`r20`）—— 已跟踪文件之外的那一半。

## 为什么需要这道门（它来自一次真实漏迁）

本仓已有 `tests/audit/test_brand_strings_are_consistent.py` 守**被跟踪文件**。
但运行态配置大多在 `.gitignore` 里（`data/*.json`），于是**没有任何门禁看得见它们** ——
而那正是改名最容易留尾巴的地方：

`data/backup_methods.json` 的 `encryption.key_env` 写着 `R20_BACKUP_ENCRYPTION_KEY`，
而代码默认值已随改名变成 `ASTRA_BACKUP_ENCRYPTION_KEY`。加密当时是关的，
所以它**当天不报错**；等用户哪天打开备份加密，任务就会去找一个不存在的键并直接失败。
**"潜伏到某个开关被打开才炸"** 是这类漏迁的共同形态，也是它值得单独一道门的原因。

## 判据

1. 扫描 `data/*.json` 里**未被只读保护**的那些（受保护的文件测试读它们会告警／
   严格模式下抛错，故交由 `scripts/migrate_r20_to_astra.py --check` 在运维路径上守），
   断言其中不出现形如 `R20_SOMETHING` 的**环境变量名**。
2. 有意保留的旧名必须逐条登记（`DELIBERATE_KEEPS`）**并说明理由**，
   同时反向断言它们**仍然存在** —— 否则登记表会慢慢变成与现实无关的清单。
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

from tests import _PROTECTED_CONFIG_FILES

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"

#: 形如环境变量名的旧命名空间记号（全大写 + 下划线，故 `R20_Backups` 这种
#: 混合大小写的**目录名**不会被误判）。
ENV_TOKEN_RE = re.compile(r"\bR20_[A-Z0-9_]{2,}\b")

#: 有意保留的旧名 → 为什么不能改。
#: 每一条都**必须真的还存在于**被扫描的文件里（见 `test_keeps_are_not_stale`）。
DELIBERATE_KEEPS: "dict[str, str]" = {
    "R20_Backups":
        "百度网盘与本地的**备份落盘目录名**。改它 = 新备份写去新目录、"
        "而历史归档留在旧目录 ⇒ 备份历史被静默劈成两半。"
        "它是外部存储上的一个位置，不是本项目的命名空间。",
}


def _scanned_files() -> "list[Path]":
    protected = {p.resolve() for p in _PROTECTED_CONFIG_FILES}
    return [p for p in sorted(DATA.glob("*.json")) if p.resolve() not in protected]


class RuntimeConfigCarriesNoLegacyNamespaceTest(unittest.TestCase):
    def test_scan_is_not_vacuous(self):
        names = {p.name for p in _scanned_files()}
        self.assertGreaterEqual(len(names), 5,
                                f"只扫到 {len(names)} 个运行态配置 ⇒ 扫描范围失效")
        # ★ 反向锚点：**破坏过的那份文件**必须在扫描范围内，
        #   否则这道门会在最需要它的地方恰好瞎掉。
        self.assertIn("backup_methods.json", names,
                      "扫描范围漏了 backup_methods.json —— 正是它漏迁过")

    def test_no_legacy_env_var_names_in_runtime_config(self):
        offenders = []
        for path in _scanned_files():
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            for m in ENV_TOKEN_RE.finditer(text):
                token = m.group(0)
                if token in DELIBERATE_KEEPS:
                    continue
                offenders.append(f"{path.name}: {token}")
        self.assertEqual(
            offenders, [],
            "运行态配置里出现了旧命名空间的环境变量名：\n  " + "\n  ".join(offenders)
            + "\n（代码已只认 `ASTRA_*`，这种写法会在对应功能被启用时直接失败；"
            "若确属必须保留的外部位置名，请连同理由加进 DELIBERATE_KEEPS。）")

    def test_keeps_are_not_stale(self):
        """反向断言：登记为"有意保留"的旧名必须真的还在，否则登记表就是在说空话。"""
        blob = ""
        for path in _scanned_files():
            try:
                blob += path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
        for token, reason in DELIBERATE_KEEPS.items():
            with self.subTest(token=token):
                self.assertIn(token, blob,
                              f"{token} 已不在任何运行态配置里，请从 DELIBERATE_KEEPS 删除")
                self.assertGreater(len(reason), 20,
                                   f"{token} 的保留理由太短 —— 必须说清为什么不能改")


class LegacyBackupArchivesStayLinkedTest(unittest.TestCase):
    """旧前缀的归档文件**不能改名** —— 备份清单按文件名引用它们。

    本机 `backups/local/` 下有三份 `r20_backup_*.tar.gz`。改名会让
    `backups/manifests/*.json` 里记录的 `archive` 字段指向不存在的文件，
    历史备份的"清单 → 归档"链接就断了。故保留，并由本类把这条理由钉住。
    """

    def test_manifests_reference_archives_by_filename(self):
        manifests = sorted((ROOT / "backups" / "manifests").glob("*.json"))
        if not manifests:
            self.skipTest("本机没有备份清单（全新安装或已清理）")
        import json
        sample = json.loads(manifests[-1].read_text(encoding="utf-8"))
        blob = json.dumps(sample, ensure_ascii=False)
        self.assertIn(".tar.gz", blob,
                      "备份清单不再记录归档文件名 ⇒ 旧前缀归档才可以安全改名，"
                      "请重新评估本类（并同步更新 docs）")

    def test_no_new_legacy_named_archive_will_be_produced(self):
        """新归档必须用新前缀，否则 prune（按 `astra_backup_*` 归类）永远回收不到它们。"""
        src = (ROOT / "scripts" / "backup_runtime.py").read_text(encoding="utf-8")
        self.assertIn('f"astra_backup_{safe_id}_{timestamp}.tar.gz"', src,
                      "归档命名模板不是新前缀 ⇒ 归档会不被 prune 管理")
        self.assertNotIn('f"r20_backup_', src, "归档命名模板又回到旧前缀了")


if __name__ == "__main__":
    unittest.main()
