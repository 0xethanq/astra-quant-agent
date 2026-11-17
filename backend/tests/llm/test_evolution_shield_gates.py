"""自进化防污染认知中枢（`scripts/evolution_shield.py`）的闸门收口 —— 第 321 刀。

本模块是**自我进化的安全闸**：宪法红线、记忆完整性、版本冲突、停用存档、
注入披露。551 行 / 30 个公开名，而既有 `tests/llm/test_evolution_shield.py` 只有
**3 例**。本刀补齐 38 行缺口 —— 几乎全是"**坏输入必须被拦住**"的路径，
也就是这个模块存在的意义本身。

## 沙箱纪律

`STRUCTURED_MEMORY_FILE` 与 `AI_MEMORY_MD_FILE` 在 `setUp` 指向临时目录 ——
本模块真会 `flock` + 原子替换 + 写 markdown 镜像，绝不能在真实 `data/` 上跑。
"""
from __future__ import annotations

import datetime
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent.parent
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import scripts.evolution_shield as es  # noqa: E402


def _fresh_stamp():
    """默认必须是**刚刚**创建 —— 默认 TTL 是 7 天，写死一个过去日期会让所有条目
    在 `render_lessons` / `injection_report` 里被判过期（本刀在此自伤过一次）。"""
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _lesson(text="这是一个足够长的可复用交易情境心法", **over):
    item = {"id": "lesson_" + (over.pop("id_suffix", None) or "a" * 8),
            "category": "TACTICAL", "rule_text": text, "enabled": True,
            "health_score": 90.0, "created_at": _fresh_stamp(),
            "ttl_days": 7, "sample_size": 3,
            "shield_status": "PASSED"}
    item.update(over)
    return item


class _Sandbox(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.memory = self.root / "structured_trading_memory.json"
        self.mirror = self.root / "AI_TRADING_MEMORY.md"
        for name, value in (("STRUCTURED_MEMORY_FILE", self.memory),
                            ("AI_MEMORY_MD_FILE", self.mirror)):
            p = patch.object(es, name, value)
            p.start()
            self.addCleanup(p.stop)

    def _write_memory(self, lessons, *, envelope=True):
        if envelope:
            payload = {"schema_version": 1, "revision": "rev-1", "lessons": lessons}
        else:
            payload = lessons
        self.memory.write_text(json.dumps(payload), encoding="utf-8")

    def _version(self):
        return es.read_memory_snapshot()["version"]

    def _commit(self, lessons):
        es._commit(lessons)
        return self._version()


# ───────────────────── 宪法红线（audit_proposed_lesson） ─────────────────────
class ConstitutionLinterTests(unittest.TestCase):
    def test_too_short_text_is_refused(self):
        ok, reason = es.audit_proposed_lesson("太短")
        self.assertFalse(ok)
        self.assertIn("过短", reason)

    def test_blank_text_is_refused(self):
        self.assertFalse(es.audit_proposed_lesson("")[0])

    def test_a_clean_lesson_passes(self):
        ok, reason = es.audit_proposed_lesson(
            "在 4H 趋势明确向上且 1H 回踩不破前低时，分批建立多头仓位", sample_size=3)
        self.assertTrue(ok)
        self.assertEqual(reason, "PASSED")

    def test_chinese_prose_retired_factor_vocabulary_is_refused(self):
        """★ 2026-10 补门禁漏洞：中文散文形态也必须拦。

        实测漏洞（真实存量心法 `lesson_80fab4e2bc5b438`）：

            若 1H RSI > 72 严重超买且 1H **动能加速度 a** 明显转负，
            **条件延续概率**偏高时优先离场观望

        整句引用的都是**已退役的动力学/概率链**，但上一版 `RETIRED_FACTOR_TOKENS`
        **只有英文标识符** ⇒ `_retired_factor_hits` 返回 `[]`、`audit_proposed_lesson`
        判 `PASSED`。而模型改用中文散文表述是**常态**（提示词全中文），
        故"只认英文标识符"等于门禁在生产路径上基本不生效。
        """
        cases = [
            "若 1H RSI > 72 严重超买且 1H 动能加速度 a 明显转负，条件延续概率偏高时优先离场观望",
            "当动力学快照的 速度场 处于高位且 加加速度 转负时，禁止顺势追多。",
            "偏差面积积分 超阈值说明动能力竭，必须等待回踩确认再布局。",
            "曲率 与 能量积分 同步上行属单边共振，严禁左侧摸顶。",
            "概率状态占比 达 75% 以上时不得顺势追多，先看结构回踩。",
            "fast_var_95_pct 突破阈值且 is_fat_tail 为真时必须减仓观望，防范肥尾踩踏。",
        ]
        for text in cases:
            ok, reason = es.audit_proposed_lesson(text, sample_size=5)
            self.assertFalse(ok, f"中文散文形态的退役因子心法竟然通过：{text}")
            self.assertIn("FACTOR_CONTRACT_DRIFT", reason)

    def test_chinese_words_that_are_still_valid_are_not_blocked(self):
        """★ 反向判据：只拦**指向具体退役因子**的复合词，不误伤语义仍成立的通用词。

        "加速度"/"动能衰竭"/"超买"/"延续"这些词在 7 梯队范式下**依然成立**
        （`macd_accel_pct` / `macd_momentum_state` 都是现行字段）。误伤它们比漏洞更糟：
        会把本来可用的心法一并拒收，让自进化"学不到东西"。
        """
        for text in (
            "1H MACD 柱与加速度同向放大才叫趋势延续，价格新高而柱体缩量属动能背离，禁止贴盘追单。",
            "动量衰竭后价格二次冲高不过前高，视为动能背离，只做右侧确认单。",
            "15M RSI 严重超买但 1H MACD 柱仍在放大时，不构成离场理由，按结构持有。",
            "趋势延续需要 1H 与 4H 同向，单周期放大不构成加仓依据。",
        ):
            ok, reason = es.audit_proposed_lesson(text, sample_size=5)
            self.assertTrue(ok, f"现行因子心法被误拦：{text} → {reason}")
            self.assertEqual(es._retired_factor_hits(text), [],
                             f"不应命中任何退役因子词元：{text}")

    def test_retired_calculus_factor_vocabulary_is_refused(self):
        """2026-10 因子契约门禁：引用已退役因子的心法一律拒收。

        背景（真实事故）：因子范式从「数理微积分动力学」整块迁到 7 梯队后，
        `velocity`／`power_regime`／`continuation_prob_pct`／`RANGE_LOW_VELOCITY` 等
        已不在任何标的的数据包里；而提示词《数据缺失纪律》规定 `--` **不得**作为证据。
        于是这类心法既无法评估、又恒以最保守方式生效 —— 实测把系统压成"只会 WAIT"。
        """
        cases = [
            "当动力学环境处于 RANGE_LOW_VELOCITY 时，绝对禁止执行顺势追多，防范单边共振踩踏。",
            "若动力学快照中 velocity > 0.8 且 power_regime 为 KINETIC_ACCELERATING，禁止左侧摸顶开空。",
            "continuation_prob_pct 偏高（>75%）时不得顺势追多，必须等待回踩支撑确认。",
            "能量积分 energy_integral 超阈值时必须观望，等待结构回踩确认后再布局。",
            "反弹高空必须限定在 KINETIC_EXHAUSTION / STEADY_FLUX 之后右侧进场。",
        ]
        for text in cases:
            ok, reason = es.audit_proposed_lesson(text, sample_size=3)
            self.assertFalse(ok, f"退役因子心法竟然通过：{text}")
            self.assertIn("FACTOR_CONTRACT_DRIFT", reason)

    def test_current_seven_tier_factors_still_pass(self):
        """门禁只拦**退役**词汇，现行 7 梯队因子写的心法必须照常通过。"""
        for text in (
            "1H MACD 柱与加速度同向放大才叫趋势延续，价格新高而柱体缩量属动能背离，禁止贴盘追单。",
            "价格偏离 24H VWAP 超 1.5σ 且落在价值区外沿时，只做均值回归的右侧确认单。",
            "15M RSI 超卖且 1H MACD 柱收缩拐点时，可在箱体极值附近小仓右侧试单。",
        ):
            ok, reason = es.audit_proposed_lesson(text, sample_size=3)
            self.assertTrue(ok, f"现行因子心法被误拦：{text} → {reason}")

    def test_the_loose_generic_token_needs_a_word_boundary(self):
        """`velocity` 是通用词：只在独立出现时才算退役因子引用。"""
        ok, reason = es.audit_proposed_lesson(
            "在 4H 趋势明确向上且 1H 回踩不破前低时，分批建立多头仓位", sample_size=3)
        self.assertTrue(ok, reason)
        self.assertFalse(es._retired_factor_hits("macd_hist_velocity_pct") or
                         "velocity" in es._retired_factor_hits("xvelocityy"))

    def test_a_single_sample_is_refused_as_an_outlier(self):
        ok, reason = es.audit_proposed_lesson(
            "在 4H 趋势明确向上且 1H 回踩不破前低时建仓", sample_size=1)
        self.assertFalse(ok)
        self.assertIn("样本量不足", reason)

    def test_blank_sentences_are_skipped(self):
        # ★ 第 145 行 —— 连续分隔符产生的空句要被 `continue` 掉，不许当成待审文本
        ok, _ = es.audit_proposed_lesson(
            "在 4H 趋势明确向上时建仓。。；;\n\n在 1H 回踩不破前低时加仓", sample_size=3)
        self.assertTrue(ok)

    def test_a_poison_pattern_is_blocked(self):
        ok, reason = es.audit_proposed_lesson(
            "可以适当放宽风控以抓住大行情机会，建议这样做", sample_size=3)
        self.assertFalse(ok)
        self.assertIn("触发宪法红线拦截", reason)

    def test_a_listed_poison_pattern_wins_over_the_cooccurrence_fallback(self):
        # 先走第 147 行那张词表 ⇒ 报的是具体的 RISK_EXPANSION_VIOLATION
        ok, reason = es.audit_proposed_lesson(
            "在行情剧烈波动时应当提高杠杆倍数以放大收益", sample_size=3)
        self.assertFalse(ok)
        self.assertIn("RISK_EXPANSION_VIOLATION", reason)

    def test_risk_parameter_tampering_cooccurrence_is_blocked(self):
        # ★ 第 158 行 —— **词表未枚举**的改写变体，靠"变更动词 × 风险名词"共现兜底。
        #   措辞必须避开 POISON_PATTERNS 里的任何一条，否则先被上面那条拦下。
        ok, reason = es.audit_proposed_lesson(
            "在市场噪音增大时可以适当降低持仓上限以适配波动",
            sample_size=3)
        self.assertFalse(ok)
        self.assertIn("RISK_PARAMETER_TAMPERING", reason)

    def test_cooccurrence_needs_both_halves(self):
        # 只有动词、没有风险名词 ⇒ 放行（否则会大面积误杀）
        ok, _ = es.audit_proposed_lesson(
            "在行情剧烈波动时应当提高耐心等待更好的入场点", sample_size=3)
        self.assertTrue(ok)

    def test_a_prohibition_clause_is_stripped_before_the_cooccurrence_check(self):
        # "不得调整单笔敞口的上限" 是在**禁止**风险扩张 ⇒ 合法，豁免共现兜底
        ok, reason = es.audit_proposed_lesson(
            "不得降低持仓上限，保持既定风险纪律即可", sample_size=3)
        self.assertTrue(ok, reason)

    def test_the_residual_clause_is_still_audited(self):
        # 前半禁止、后半是真违规 ⇒ 剥离只在**被剥离的**子句上生效
        ok, reason = es.audit_proposed_lesson(
            "不得降低持仓上限，但可以在噪音增大时降低持仓上限",
            sample_size=3)
        self.assertFalse(ok)
        self.assertIn("RISK_PARAMETER_TAMPERING", reason)

    def test_prohibition_stripping_keeps_only_the_clean_clauses(self):
        self.assertEqual(es._strip_prohibition_clauses("严禁追高，可以回踩买入"), "可以回踩买入")
        self.assertEqual(es._strip_prohibition_clauses("严禁追高"), "")
        self.assertEqual(es._strip_prohibition_clauses(""), "")

    def test_the_red_line_check_is_per_sentence_not_whole_text(self):
        # 跨句不误伤：违规词在另一句不影响本句判定
        ok, _ = es.audit_proposed_lesson(
            "在上涨趋势里保持耐心持有。回踩不破前低时可以继续加码跟随。", sample_size=3)
        self.assertTrue(ok)


# ───────────────────── 记忆完整性（_validate） ─────────────────────
class ValidateTests(unittest.TestCase):
    def test_a_non_list_is_refused(self):
        # ★ 第 181 行
        for bad in ({}, "x", None, 42):
            with self.subTest(bad=bad):
                with self.assertRaises(es.MemoryCorruptError) as ctx:
                    es._validate(bad)
                self.assertIn("Expected a lesson list", str(ctx.exception))

    def test_a_valid_list_passes_through(self):
        rows = [_lesson()]
        self.assertIs(es._validate(rows), rows)

    def test_an_invalid_numeric_field_is_refused(self):
        # ★ 第 191 行
        for field, value in (("health_score", "high"), ("ttl_days", -1),
                             ("sample_size", float("inf")), ("ttl_days", True)):
            with self.subTest(field=field, value=value):
                with self.assertRaises(es.MemoryCorruptError) as ctx:
                    es._validate([_lesson(**{field: value})])
                self.assertIn("Invalid numeric field", str(ctx.exception))

    def test_an_invalid_text_field_is_refused(self):
        # ★ 第 194 行
        for field in ("category", "created_at", "shield_status"):
            with self.subTest(field=field):
                with self.assertRaises(es.MemoryCorruptError) as ctx:
                    es._validate([_lesson(**{field: 123})])
                self.assertIn("Invalid text field", str(ctx.exception))

    def test_missing_optional_fields_are_fine(self):
        self.assertEqual(len(es._validate([{"id": "a", "rule_text": "x", "enabled": True}])), 1)

    def test_missing_required_fields_are_refused(self):
        for broken in ({"rule_text": "x", "enabled": True},
                       {"id": "a", "enabled": True},
                       {"id": "a", "rule_text": "x"},
                       {"id": "a", "rule_text": "  ", "enabled": True}):
            with self.subTest(broken=sorted(broken)):
                with self.assertRaises(es.MemoryCorruptError):
                    es._validate([broken])

    def test_enabled_must_be_a_real_bool(self):
        with self.assertRaises(es.MemoryCorruptError):
            es._validate([_lesson(enabled=1)])

    def test_duplicate_ids_are_refused(self):
        with self.assertRaises(es.MemoryCorruptError):
            es._validate([_lesson(id_suffix="b" * 8), _lesson(id_suffix="b" * 8)])


# ───────────────────── 半衰期 / TTL（is_lesson_expired） ─────────────────────
class LessonExpiryTests(unittest.TestCase):
    NOW = datetime.datetime(2026, 9, 22, tzinfo=datetime.timezone.utc)

    def test_no_lesson_is_exempt_from_the_half_life(self):
        """★ 2026-10：原「基准心法永不过期」豁免已随基准机制拆除。

        所有心法一律按 `ttl_days` 计半衰期 —— 不再有"宪法级例外"。
        """
        self.assertTrue(es.is_lesson_expired(
            _lesson(created_at="2000-01-01T00:00:00+00:00"), self.NOW))

    def test_a_missing_created_at_never_expires(self):
        # ★ 第 231 行 —— 没有时间戳就**不判过期**（绝不猜）
        item = _lesson()
        item.pop("created_at")
        self.assertFalse(es.is_lesson_expired(item, self.NOW))

    def test_a_blank_created_at_never_expires(self):
        self.assertFalse(es.is_lesson_expired(_lesson(created_at=""), self.NOW))

    def test_a_fresh_lesson_is_alive(self):
        self.assertFalse(es.is_lesson_expired(
            _lesson(created_at="2026-09-20T00:00:00+00:00", ttl_days=7), self.NOW))

    def test_an_old_lesson_has_expired(self):
        self.assertTrue(es.is_lesson_expired(
            _lesson(created_at="2026-01-01T00:00:00+00:00", ttl_days=7), self.NOW))

    def test_a_zulu_timestamp_is_accepted(self):
        # ★ 第 234 行 —— `Z` 后缀要翻成 `+00:00`（`fromisoformat` 在 3.11 前不认 Z）
        item = _lesson(created_at="2026-09-20T00:00:00Z", ttl_days=7)
        self.assertFalse(es.is_lesson_expired(item, self.NOW))

    def test_a_zulu_timestamp_exposes_a_blank_created_at_as_blank(self):
        # `created_at_str` 是局部变量，`Z` 改写不许污染原件
        item = _lesson(created_at="2026-09-20T00:00:00Z")
        es.is_lesson_expired(item, self.NOW)
        self.assertEqual(item["created_at"], "2026-09-20T00:00:00Z")

    def test_a_naive_timestamp_is_treated_as_utc(self):
        self.assertFalse(es.is_lesson_expired(
            _lesson(created_at="2026-09-20T00:00:00", ttl_days=7), self.NOW))

    def test_an_unparsable_timestamp_never_expires(self):
        # ★ 第 241 行 —— 解析失败一律**不判过期**（保守：宁可不退役也不误杀）
        for bad in ("not-a-date", "2026-13-45T99:99:99", "12345"):
            with self.subTest(bad=bad):
                self.assertFalse(es.is_lesson_expired(_lesson(created_at=bad), self.NOW))

    def test_ttl_defaults_to_seven_days(self):
        item = _lesson(created_at="2026-09-10T00:00:00+00:00")
        item.pop("ttl_days")
        self.assertTrue(es.is_lesson_expired(item, self.NOW))


# ───────────────────── 渲染与注入披露 ─────────────────────
class RenderLessonsTests(unittest.TestCase):
    def test_disabled_lessons_are_not_rendered(self):
        text = es.render_lessons([_lesson(text="应当保持耐心", enabled=False)])
        self.assertEqual(text, "")

    def test_expired_lessons_are_suppressed(self):
        # ★ 第 252 行 —— 自然半衰期到期后不再注入主脑
        text = es.render_lessons([_lesson(text="应当保持耐心等待机会",
                                          created_at="2000-01-01T00:00:00+00:00")])
        self.assertEqual(text, "")

    def test_enabled_lessons_are_rendered_as_bullets(self):
        text = es.render_lessons([_lesson(text="应当保持耐心等待机会")])
        self.assertEqual(text, "- 应当保持耐心等待机会")

    def test_injection_is_capped_at_the_documented_limit(self):
        rows = [_lesson(text=f"心法条目编号{i}需要足够长才能通过校验",
                        id_suffix=f"{i:08d}",
                        created_at=_fresh_stamp())
                for i in range(12)]
        self.assertEqual(len(es.render_lessons(rows).splitlines()),
                         es.MAX_INJECTED_LESSONS)

    def test_the_healthiest_lesson_ranks_first(self):
        """★ 2026-10：排序键不再是"基准优先"（基准已不存在），而是**健康分优先**。

        这条直接决定注入配额（8 条）给谁 —— 旧键下一条又老又差的条目会永久占位。
        """
        # 两条都必须**在 TTL 内**（否则会被半衰期挡掉，与排序无关）；
        # 高分那条刻意更旧，用来证明"健康分压过新旧"。
        import datetime as _dt
        now = _dt.datetime.now(_dt.timezone.utc)
        fresh = (now - _dt.timedelta(days=1)).isoformat()
        older = (now - _dt.timedelta(days=5)).isoformat()
        rows = [_lesson(text="低分心法条目需要足够长才能通过校验", id_suffix="1" * 8,
                        health_score=30.0, created_at=fresh),
                _lesson(text="高分心法条目需要足够长才能通过校验", id_suffix="2" * 8,
                        health_score=95.0, created_at=older)]
        self.assertTrue(es.render_lessons(rows).startswith("- 高分心法条目"),
                        "健康分高的必须先注入，哪怕它更旧")

    def test_injection_report_exposes_the_gap(self):
        rows = [_lesson(text=f"心法条目编号{i}需要足够长才能通过校验",
                        id_suffix=f"{i:08d}") for i in range(12)]
        report = es.injection_report(rows)
        self.assertEqual(report["active"], 12)
        self.assertEqual(report["injected"], es.MAX_INJECTED_LESSONS)
        self.assertEqual(report["limit"], es.MAX_INJECTED_LESSONS)
        self.assertEqual(len(report["not_injected"]), 4, "未注入清单要如实披露")


# ───────────────────── 快照读取 ─────────────────────
class ReadMemorySnapshotTests(_Sandbox, unittest.TestCase):
    def test_a_missing_file_reports_missing_not_empty(self):
        snap = es.read_memory_snapshot()
        self.assertFalse(snap["exists"])
        self.assertEqual(snap["version"], "missing")
        self.assertEqual(snap["lessons"], [])

    def test_a_legacy_bare_list_stays_readable(self):
        self._write_memory([_lesson()], envelope=False)
        snap = es.read_memory_snapshot()
        self.assertTrue(snap["exists"])
        self.assertEqual(len(snap["lessons"]), 1)

    def test_a_current_envelope_is_read(self):
        self._write_memory([_lesson()])
        self.assertEqual(len(es.read_memory_snapshot()["lessons"]), 1)

    def test_the_version_is_the_file_digest(self):
        import hashlib
        self._write_memory([_lesson()])
        self.assertEqual(es.read_memory_snapshot()["version"],
                         hashlib.sha256(self.memory.read_bytes()).hexdigest())

    def test_a_wrong_schema_version_is_refused(self):
        self.memory.write_text(json.dumps(
            {"schema_version": 2, "revision": "r", "lessons": []}), encoding="utf-8")
        with self.assertRaises(es.MemoryCorruptError):
            es.read_memory_snapshot()

    def test_a_missing_revision_is_refused(self):
        self.memory.write_text(json.dumps(
            {"schema_version": 1, "lessons": []}), encoding="utf-8")
        with self.assertRaises(es.MemoryCorruptError):
            es.read_memory_snapshot()

    def test_a_non_string_revision_is_refused(self):
        self.memory.write_text(json.dumps(
            {"schema_version": 1, "revision": 7, "lessons": []}), encoding="utf-8")
        with self.assertRaises(es.MemoryCorruptError):
            es.read_memory_snapshot()

    def test_corrupt_json_is_refused_with_the_retention_message(self):
        self.memory.write_text("{ broken", encoding="utf-8")
        with self.assertRaises(es.MemoryCorruptError) as ctx:
            es.read_memory_snapshot()
        self.assertIn("retained unchanged", str(ctx.exception))

    def test_an_invalid_lesson_inside_a_good_envelope_is_refused(self):
        self.memory.write_text(json.dumps(
            {"schema_version": 1, "revision": "r", "lessons": [{"id": "a"}]}),
            encoding="utf-8")
        with self.assertRaises(es.MemoryCorruptError):
            es.read_memory_snapshot()

    def test_load_structured_memory_returns_just_the_lessons(self):
        self._write_memory([_lesson()])
        self.assertEqual(len(es.load_structured_memory()), 1)


# ───────────────────── 兼容读取（read_trading_context） ─────────────────────
class TradingContextTests(_Sandbox, unittest.TestCase):
    def test_the_structured_authority_wins(self):
        self._write_memory([_lesson(text="来自权威存储的心法条目")])
        snap, text, texts = es.read_trading_context()
        self.assertTrue(snap["exists"])
        self.assertIn("来自权威存储的心法条目", text)
        self.assertEqual(texts, ["来自权威存储的心法条目"])

    def test_only_enabled_lessons_become_prompt_text(self):
        self._write_memory([_lesson(text="启用的心法条目", id_suffix="1" * 8),
                            _lesson(text="停用的心法条目", id_suffix="2" * 8,
                                    enabled=False)])
        _, _, texts = es.read_trading_context()
        self.assertEqual(texts, ["启用的心法条目"])

    def test_legacy_markdown_is_used_only_without_the_authority(self):
        md = self.root / "legacy.md"
        md.write_text("旧的手写心法", encoding="utf-8")
        snap, text, texts = es.read_trading_context(legacy_md=str(md))
        self.assertFalse(snap["exists"])
        self.assertEqual(text, "旧的手写心法")
        self.assertEqual(texts, [])

    def test_legacy_json_lessons_are_rendered_as_bullets(self):
        md = self.root / "legacy.md"      # 不存在
        legacy = self.root / "legacy.json"
        legacy.write_text(json.dumps({"core_lessons": ["旧条目一", "旧条目二"]}),
                          encoding="utf-8")
        _, text, texts = es.read_trading_context(legacy_md=str(md), legacy_json=str(legacy))
        self.assertEqual(texts, ["旧条目一", "旧条目二"])
        self.assertEqual(text, "- 旧条目一\n- 旧条目二")

    def test_an_invalid_legacy_lesson_list_is_refused(self):
        # ★ 第 297 行
        legacy = self.root / "legacy.json"
        legacy.write_text(json.dumps({"core_lessons": "not-a-list"}), encoding="utf-8")
        with self.assertRaises(es.MemoryCorruptError) as ctx:
            es.read_trading_context(legacy_md=str(self.root / "none.md"),
                                    legacy_json=str(legacy))
        self.assertIn("Invalid legacy lessons", str(ctx.exception))

    def test_a_legacy_list_with_non_strings_is_refused(self):
        legacy = self.root / "legacy.json"
        legacy.write_text(json.dumps({"core_lessons": ["ok", 42]}), encoding="utf-8")
        with self.assertRaises(es.MemoryCorruptError):
            es.read_trading_context(legacy_md=str(self.root / "none.md"),
                                    legacy_json=str(legacy))

    def test_render_trading_memory_is_blank_when_there_is_nothing(self):
        self.assertEqual(es.render_trading_memory(legacy_md=str(self.root / "none.md")), "")

    def test_render_trading_memory_wraps_the_body(self):
        self._write_memory([_lesson(text="自进化心法条目")])
        out = es.render_trading_memory()
        self.assertIn("【AstraQuant 启发式实战认知与长期记忆】", out)
        self.assertIn("自进化心法条目", out)


# ───────────────────── markdown 镜像（sync_markdown_mirror） ─────────────────────
class MarkdownMirrorTests(_Sandbox, unittest.TestCase):
    def test_no_authority_means_no_mirror(self):
        self.assertFalse(es.sync_markdown_mirror())
        self.assertFalse(self.mirror.exists())

    def test_an_empty_library_still_refreshes_the_mirror(self):
        """★ 2026-10 缺陷修复：空库**必须**照写镜像，不能跳过。

        旧实现空库直接 `return False` ⇒ 镜像保持上一次内容。用户清空心法库后，
        看板仍显示**已删除的心法**与"共 N 条心法"的表头 —— "删掉"在界面上没发生。
        """
        self._write_memory([_lesson(enabled=False)])
        self.assertTrue(es.sync_markdown_mirror(), "空库也必须刷新镜像")
        doc = self.mirror.read_text(encoding="utf-8")
        self.assertIn("共 1 条心法（生效 0 条）", doc, "表头必须区分总条数与生效条数")
        self.assertIn("当前无生效心法", doc)
        self.assertNotIn("这是一个足够长的可复用交易情境心法", doc,
                         "已删除的条目不得残留在镜像里")

    def test_the_mirror_carries_the_provenance_header(self):
        self._write_memory([_lesson(text="镜像里的心法条目")])
        self.assertTrue(es.sync_markdown_mirror())
        doc = self.mirror.read_text(encoding="utf-8")
        self.assertIn("权威来源: structured_trading_memory.json", doc)
        self.assertIn("镜像里的心法条目", doc)
        self.assertIn("共 1 条心法", doc)

    def test_an_unparsable_newest_timestamp_falls_back_to_a_truncated_string(self):
        # ★ 第 332 行 —— `fromisoformat` 失败时用前 19 个字符（不崩）
        self._write_memory([_lesson(text="时间戳古怪的心法条目",
                                    created_at="not-a-date-at-all-but-long-enough")])
        self.assertTrue(es.sync_markdown_mirror())
        self.assertIn("not-a-date-at-all-", self.mirror.read_text(encoding="utf-8"))

    def test_no_timestamps_at_all_renders_a_dash(self):
        # ★ 第 334 行
        item = _lesson(text="没有时间戳的心法条目")
        item.pop("created_at")
        self._write_memory([item])
        self.assertTrue(es.sync_markdown_mirror())
        self.assertIn("更新基准: --", self.mirror.read_text(encoding="utf-8"))

    def test_no_temporary_file_is_left_behind(self):
        self._write_memory([_lesson(text="清理临时文件的心法条目")])
        es.sync_markdown_mirror()
        self.assertEqual([p.name for p in self.root.glob("*.tmp*")], [])

    def test_the_mirror_is_rewritten_not_appended(self):
        self._write_memory([_lesson(text="第一版心法条目内容")])
        es.sync_markdown_mirror()
        self._write_memory([_lesson(text="第二版心法条目内容")])
        es.sync_markdown_mirror()
        doc = self.mirror.read_text(encoding="utf-8")
        self.assertIn("第二版心法条目内容", doc)
        self.assertNotIn("第一版心法条目内容", doc)


# ───────────────────── 版本闸与候选审阅 ─────────────────────
class VersionGateTests(_Sandbox, unittest.TestCase):
    def test_a_missing_version_is_refused(self):
        self._write_memory([_lesson()])
        with self.assertRaises(es.MemoryVersionRequiredError):
            es._check_version(es.read_memory_snapshot(), None)

    def test_an_empty_version_is_refused(self):
        with self.assertRaises(es.MemoryVersionRequiredError):
            es._check_version({"version": "x"}, "")

    def test_a_stale_version_is_refused_without_overwriting(self):
        self._write_memory([_lesson()])
        with self.assertRaises(es.MemoryConflictError) as ctx:
            es._check_version(es.read_memory_snapshot(), "stale")
        self.assertIn("未覆盖当前数据", str(ctx.exception))

    def test_a_matching_version_passes(self):
        self._write_memory([_lesson()])
        self.assertIsNone(es._check_version(es.read_memory_snapshot(), self._version()),
                          "版本一致时 `_check_version` 返回 None（放行）")


class ReviewCandidatesTests(_Sandbox, unittest.TestCase):
    def test_a_non_list_is_refused(self):
        # ★ 第 398 行
        for bad in ("text", {"a": 1}, None, 42):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError) as ctx:
                    es._review_candidates(bad, [], 3, True)
                self.assertIn("Expected text list", str(ctx.exception))

    def test_a_list_with_non_strings_is_refused(self):
        with self.assertRaises(ValueError):
            es._review_candidates(["ok", 42], [], 3, True)

    def test_duplicate_texts_inside_one_batch_are_collapsed(self):
        # ★ 第 405 行
        result = es._review_candidates(
            ["应当保持耐心等待更好的入场时机", "应当保持耐心等待更好的入场时机"],
            [], 3, True)
        self.assertEqual(len(result), 1)

    def test_unchanged_texts_keep_their_identity_and_metadata(self):
        old = [_lesson(text="应当保持耐心等待更好的入场时机", health_score=42.0,
                       id_suffix="9" * 8)]
        result = es._review_candidates(["应当保持耐心等待更好的入场时机"], old, 3, True)
        self.assertEqual(result[0]["id"], old[0]["id"])
        self.assertEqual(result[0]["health_score"], 42.0)

    def test_non_strict_mode_drops_a_rejected_candidate(self):
        # ★ 第 415 行
        result = es._review_candidates(["可以适当放宽风控以抓住机会"], [], 3, False)
        self.assertEqual(result, [])

    def test_strict_mode_raises_on_a_rejected_candidate(self):
        with self.assertRaises(ValueError):
            es._review_candidates(["可以适当放宽风控以抓住机会"], [], 3, True)

    def test_disabled_tombstones_survive_a_review(self):
        old = [_lesson(text="已被停用的心法条目内容", enabled=False, id_suffix="8" * 8)]
        result = es._review_candidates(["应当保持耐心等待更好的入场时机"], old, 3, True)
        self.assertEqual(len(result), 2)
        self.assertTrue(any(not i["enabled"] for i in result))

    def test_revise_leaves_an_unmentioned_learned_lesson_as_a_tombstone(self):
        # 审计 P1-8c：REVISE/INVALIDATE 下未被复述的已学心法不许蒸发
        old = [_lesson(text="旧的已学心法条目内容", id_suffix="7" * 8)]
        result = es._review_candidates(["应当保持耐心等待更好的入场时机"], old, 3, True,
                                       "REVISE")
        tomb = next(i for i in result if i["rule_text"] == "旧的已学心法条目内容")
        self.assertFalse(tomb["enabled"])
        self.assertIn("retired_at", tomb)
        self.assertIn("未复述", tomb["retired_reason"])

    def test_a_mentioned_lesson_is_not_tombstoned(self):
        # ★ 第 427 行 —— 复述过的条目走"保留原样"路径，不该再被退役
        old = [_lesson(text="旧的已学心法条目内容", id_suffix="7" * 8)]
        result = es._review_candidates(["旧的已学心法条目内容"], old, 3, True, "REVISE")
        self.assertEqual(len(result), 1)
        self.assertTrue(result[0]["enabled"])

    def test_an_unmentioned_lesson_never_vanishes_it_becomes_a_tombstone(self):
        """★ 2026-10 起本函数**自足**了：漏述的条目落成停用存档，而不是消失。

        历史：旧实现在这里对 `is_baseline` 直接 `continue`（既不进结果也不退役），
        安全性**依赖调用方补回**。基准机制拆除后补回没了，故基线保护改为
        "一律落停用存档" —— 这比旧的两层防御更强：**任何**漏述的启用条目都不会蒸发。
        """
        old = [_lesson(text="既有心法条目内容需要足够长", id_suffix="6" * 8)]
        result = es._review_candidates(["应当保持耐心等待更好的入场时机"], old, 3, True,
                                       "INVALIDATE")
        by_text = {i["rule_text"]: i for i in result}
        self.assertIn("既有心法条目内容需要足够长", by_text, "被漏述的条目必须仍在结果里")
        self.assertFalse(by_text["既有心法条目内容需要足够长"]["enabled"], "但必须已停用")
        self.assertIn("retired_reason", by_text["既有心法条目内容需要足够长"])

    def test_the_outer_layer_adds_nothing_on_invalidate(self):
        """★ 外层不再"补回"任何东西：INVALIDATE 的清单**只由模型给出**。"""
        from scripts.self_improvement_engine import merge_lesson_texts
        old = [_lesson(text="既有心法条目内容需要足够长", id_suffix="6" * 8)]
        final = merge_lesson_texts(
            "INVALIDATE", ["应当保持耐心等待更好的入场时机"], old)
        self.assertEqual(final, ["应当保持耐心等待更好的入场时机"],
                         "不得补回任何未复述条目")

    def test_the_old_list_is_not_merged_in_automatically(self):
        # ⚠️ 危险语义（本刀仅记录，**未改**）：`_review_candidates(texts, old, …)`
        #    的结果**完全由 `texts` 决定** —— `old` 只在三种情况下被保留：
        #    ① 文本在 `texts` 里原样出现（保留身份）；② 已停用的存档；
        #    ③ REVISE/INVALIDATE 下的退役留痕。
        #    ⇒ 一个**启用的非基准**心法若不在 `texts` 里，就会被**静默删除**。
        #    两个真实调用方都各自补齐了这一点（ADD 分支拼上 existing_texts、
        #    admin_mutate 做 `candidates += active`），所以生产无碍 ——
        #    但这意味着**本函数不是自足的**：新增调用方忘了补齐就会丢心法。
        old = [_lesson(text="既有的启用心法条目内容", id_suffix="5" * 8)]
        result = es._review_candidates(["应当保持耐心等待更好的入场时机"], old, 3, True,
                                       "ADD")
        self.assertEqual([i["rule_text"] for i in result],
                         ["应当保持耐心等待更好的入场时机"],
                         "只看 texts ⇒ 既有心法不在结果里")
        self.assertFalse(any(i["rule_text"] == "既有的启用心法条目内容" for i in result))

    def test_passing_the_full_list_preserves_existing_entries(self):
        # 对照：按真实契约传全量清单就不会丢
        old = [_lesson(text="既有的启用心法条目内容", id_suffix="5" * 8)]
        result = es._review_candidates(["既有的启用心法条目内容",
                                        "应当保持耐心等待更好的入场时机"], old, 3, True,
                                       "ADD")
        self.assertEqual(len(result), 2)

    def test_admin_mutate_compensates_by_appending_active_texts(self):
        # 上层补偿确实存在：`admin_mutate` 的 add 分支会 `candidates += active`
        src = Path(es.__file__).read_text(encoding="utf-8")
        self.assertIn("candidates += active", src)

    def test_add_status_does_not_tombstone(self):
        old = [_lesson(text="旧的已学心法条目内容", id_suffix="7" * 8)]
        result = es._review_candidates(["应当保持耐心等待更好的入场时机"], old, 3, True,
                                       "ADD")
        self.assertEqual([i["rule_text"] for i in result].count("旧的已学心法条目内容"), 0)


# ───────────────────── 发布（publish_review） ─────────────────────
class PublishReviewTests(_Sandbox, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self._write_memory([_lesson(text="既有心法条目内容需要足够长")])
        self.version = self._version()

    def _publish(self, texts, status="ADD", **over):
        kw = {"expected_version": self.version, "sample_size": 3, "change_status": status}
        kw.update(over)
        return es.publish_review(texts, **kw)

    def test_no_change_is_a_noop(self):
        # ★ 第 438 行
        self.assertFalse(self._publish(["应当保持耐心等待更好的入场时机"],
                                       status="NO_CHANGE"))

    def test_an_unknown_status_is_refused(self):
        # ★ 第 440 行
        with self.assertRaises(ValueError) as ctx:
            self._publish([], status="DELETE_EVERYTHING")
        self.assertIn("Invalid change status", str(ctx.exception))

    def test_a_valid_add_is_published(self):
        # ⚠️ 必须**连同现有条目一起**传 —— 见 `ReviewCandidatesTests` 那条危险说明：
        #    本函数不合并 `old`，只传新文本会把现有心法静默删光。
        #    真实调用方 `merge_memory_with_constitution`（ADD 分支）与
        #    `admin_mutate`（`candidates += active`）都会补齐。
        self.assertTrue(self._publish(["既有心法条目内容需要足够长",
                                       "应当保持耐心等待更好的入场时机"]))
        self.assertEqual(len(es.load_structured_memory()), 2)

    def test_a_rejected_candidate_raises_in_strict_mode(self):
        # `publish_review` 用 strict=True ⇒ 有被拒的新条目时**抛**，不是静默返回 False
        with self.assertRaises(ValueError):
            self._publish(["在市场噪音增大时可以适当降低持仓上限以适配波动"])
        self.assertEqual(len(es.load_structured_memory()), 1, "拒绝时不许动现有条目")

    def test_an_empty_proposal_whose_result_contains_none_of_the_texts_is_a_noop(self):
        # ★ 第 449 行 —— `texts` 为空时 `{t.strip() for t in texts}` 是空集，
        #   只要候选里出现任何"未在 texts 中"的条目就会走到这个早退，
        #   而且**必须不写盘**（否则一次空提案会把停用存档顺手提交）
        self._write_memory([_lesson(text="既有心法条目内容需要足够长", id_suffix="1" * 8),
                            _lesson(text="已停用的心法条目内容需要足够长",
                                    id_suffix="2" * 8, enabled=False)])
        version = self._version()
        self.assertFalse(es.publish_review([], expected_version=version,
                                           sample_size=3, change_status="ADD"))
        self.assertEqual(self._version(), version, "早退不许轮换版本（即不许写盘）")

    def test_a_stale_version_blocks_the_publish(self):
        with self.assertRaises(es.MemoryConflictError):
            self._publish(["应当保持耐心等待更好的入场时机"], expected_version="stale")

    def test_an_identical_proposal_is_a_noop(self):
        self.assertFalse(self._publish(["既有心法条目内容需要足够长"]))

    def test_the_version_rotates_after_a_publish(self):
        before = self._version()
        self._publish(["应当保持耐心等待更好的入场时机"])
        self.assertNotEqual(self._version(), before)


# ───────────────────── save_structured_memory ─────────────────────
class SaveStructuredMemoryTests(_Sandbox, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self._write_memory([_lesson(text="既有心法条目内容需要足够长")])
        self.version = self._version()

    def test_an_unchanged_round_trip_succeeds(self):
        es.save_structured_memory(es.load_structured_memory(),
                                  expected_version=self.version)
        self.assertEqual(len(es.load_structured_memory()), 1)

    def test_a_valid_new_lesson_is_saved(self):
        rows = es.load_structured_memory() + [_lesson(text="应当保持耐心等待更好的入场时机",
                                                      id_suffix="5" * 8)]
        es.save_structured_memory(rows, expected_version=self.version)
        self.assertEqual(len(es.load_structured_memory()), 2)

    def test_a_stale_version_is_refused(self):
        with self.assertRaises(es.MemoryConflictError):
            es.save_structured_memory(es.load_structured_memory(),
                                      expected_version="stale")

    def test_resurrecting_a_disabled_text_is_refused(self):
        # ★ 第 462/463 行 —— 停用过的文本必须显式 toggle，不许借"重新发布"复活
        self._write_memory([_lesson(text="已被停用的心法条目内容", enabled=False)])
        version = self._version()
        rows = es.load_structured_memory()
        rows[0]["enabled"] = True
        with self.assertRaises(ValueError) as ctx:
            es.save_structured_memory(rows, expected_version=version)
        self.assertIn("explicit toggle", str(ctx.exception))

    def test_a_new_lesson_still_faces_the_constitution(self):
        # ★ 第 465/467 行 —— 兼容发布器不许成为绕过审查的后门
        rows = es.load_structured_memory() + [_lesson(text="可以适当放宽风控以抓住机会",
                                                      id_suffix="4" * 8)]
        with self.assertRaises(ValueError):
            es.save_structured_memory(rows, expected_version=self.version)

    def test_a_corrupt_memory_is_not_overwritten(self):
        self.memory.write_text("{ broken", encoding="utf-8")
        with self.assertRaises(es.MemoryCorruptError):
            es.save_structured_memory([_lesson()], expected_version="whatever")


# ───────────────────── toggle / rollback ─────────────────────
class ToggleLessonTests(_Sandbox, unittest.TestCase):
    def test_a_missing_id_returns_none(self):
        # ★ 第 481 行
        self._write_memory([_lesson()])
        self.assertIsNone(es.toggle_lesson("lesson_nope",
                                           expected_version=self._version()))

    def test_toggling_flips_the_flag(self):
        item = _lesson(id_suffix="3" * 8)
        self._write_memory([item])
        out = es.toggle_lesson(item["id"], expected_version=self._version())
        self.assertFalse(out["enabled"])
        out = es.toggle_lesson(item["id"], expected_version=self._version())
        self.assertTrue(out["enabled"])

    def test_a_missing_version_is_refused(self):
        self._write_memory([_lesson()])
        with self.assertRaises(es.MemoryVersionRequiredError):
            es.toggle_lesson("lesson_x")


class ResetAllLessonsTests(_Sandbox, unittest.TestCase):
    """2026-10：`rollback_to_baseline` → `reset_all_lessons`（清空到空白）。

    系统不再预设心法，故"重置"的目标集合从 4 条基准变成**空集**。
    安全性语义（CAS / 拒腐）原样保留。
    """

    def test_reset_empties_the_library(self):
        self._write_memory([_lesson(text="自进化长出来的心法条目内容")])
        out = es.reset_all_lessons(expected_version=self._version())
        self.assertEqual(out, [], "清空到空白（系统不再预设任何心法）")
        self.assertEqual(es.load_structured_memory(), [])
        self.assertFalse(hasattr(es, "BASELINE_LESSONS"),
                         "预设常量本身也必须已删除（不是留个空列表当摆设）")

    def test_reset_requires_a_version(self):
        self._write_memory([_lesson()])
        with self.assertRaises(es.MemoryVersionRequiredError):
            es.reset_all_lessons()

    def test_reset_rejects_a_stale_version(self):
        self._write_memory([_lesson()])
        with self.assertRaises(es.MemoryConflictError):
            es.reset_all_lessons(expected_version="stale")
        self.assertEqual(len(es.load_structured_memory()), 1, "版本不符不得清空")

    def test_reset_never_overwrites_corruption(self):
        self.memory.write_text("{ broken", encoding="utf-8")
        with self.assertRaises(es.MemoryCorruptError):
            es.reset_all_lessons(expected_version="x")


# ───────────────────── admin 视图与变更 ─────────────────────
class AdminViewTests(_Sandbox, unittest.TestCase):
    def test_the_structured_view_lists_enabled_texts(self):
        self._write_memory([_lesson(text="启用的心法条目内容", id_suffix="1" * 8),
                            _lesson(text="停用的心法条目内容", id_suffix="2" * 8,
                                    enabled=False)])
        view = es.admin_memory_view()
        self.assertEqual(view["items"], ["启用的心法条目内容"])
        self.assertFalse(view["legacy_read_only"])

    def test_the_legacy_view_is_marked_read_only(self):
        md = self.root / "legacy.md"
        md.write_text("旧心法\n- 旧条目一\n- 旧条目二\n", encoding="utf-8")
        with patch.object(es, "AI_MEMORY_MD_FILE", md):
            view = es.admin_memory_view()
        self.assertTrue(view["legacy_read_only"])
        self.assertEqual(view["items"], ["旧条目一", "旧条目二"])


class AdminMutateTests(_Sandbox, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.a = _lesson(text="第一条心法条目内容需要足够长", id_suffix="1" * 8)
        self.b = _lesson(text="第二条心法条目内容需要足够长", id_suffix="2" * 8)
        self._write_memory([self.a, self.b])

    def _mutate(self, operation, **over):
        kw = {"expected_version": self._version()}
        kw.update(over)
        return es.admin_mutate(operation, **kw)

    def test_delete_by_lesson_id(self):
        result = self._mutate("delete", lesson_id=self.a["id"])
        self.assertEqual(result["removed"], self.a["rule_text"])
        self.assertEqual(result["items"], [self.b["rule_text"]])

    def test_delete_by_unknown_id_is_refused(self):
        # ★ 第 516 行
        with self.assertRaises(IndexError) as ctx:
            self._mutate("delete", lesson_id="lesson_nope")
        self.assertIn("Memory id not found", str(ctx.exception))

    def test_delete_by_index(self):
        # ★ 第 520–523 行
        result = self._mutate("delete", index=0)
        self.assertEqual(result["removed"], self.a["rule_text"])
        self.assertEqual(result["items"], [self.b["rule_text"]])

    def test_delete_by_out_of_range_index_is_refused(self):
        for bad in (5, -1, None):
            with self.subTest(bad=bad):
                with self.assertRaises(IndexError) as ctx:
                    self._mutate("delete", index=bad)
                self.assertIn("Memory index not found", str(ctx.exception))

    def test_an_unknown_operation_is_refused(self):
        # ★ 第 530 行
        with self.assertRaises(ValueError) as ctx:
            self._mutate("nuke")
        self.assertIn("Unknown memory operation", str(ctx.exception))

    def test_add_appends_a_new_lesson(self):
        result = self._mutate("add", texts=["第三条心法条目内容需要足够长"])
        self.assertEqual(len(result["items"]), 3)
        self.assertNotIn("removed", result)

    def test_replace_keeps_only_the_given_texts(self):
        result = self._mutate("replace", texts=[self.b["rule_text"]])
        self.assertEqual(result["items"], [self.b["rule_text"]])

    def test_a_rejected_add_leaves_memory_unchanged(self):
        with self.assertRaises(ValueError):
            self._mutate("add", texts=["可以适当放宽风控以抓住机会"])
        self.assertEqual(len(es.load_structured_memory()), 2)

    def test_a_legacy_memory_is_read_only_for_admin_mutation(self):
        self.memory.unlink()
        es._commit([_lesson()])          # 建一个合法权威
        self.memory.write_text(json.dumps([_lesson()]), encoding="utf-8")
        # 裸露的 list 也是"存在"的权威 ⇒ 这条改为验证缺失时的分支
        self.memory.unlink()
        with self.assertRaises(es.MemoryConflictError) as ctx:
            es.admin_mutate("add", texts=["新心法条目内容需要足够长"],
                            expected_version="missing")
        self.assertIn("read-only", str(ctx.exception))

    def test_a_stale_version_is_refused(self):
        with self.assertRaises(es.MemoryConflictError):
            es.admin_mutate("delete", lesson_id=self.a["id"], expected_version="stale")

    def test_a_rejected_only_add_does_not_rotate_the_version(self):
        before = self._version()
        with self.assertRaises(ValueError):
            self._mutate("add", texts=["可以适当放宽风控以抓住机会"])
        self.assertEqual(self._version(), before)


# ───────────────────── add_safe_lesson ─────────────────────
class AddSafeLessonTests(_Sandbox, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self._write_memory([])

    def test_a_rejected_lesson_is_not_written(self):
        # ★ 第 542 行
        ok, reason, item = es.add_safe_lesson("可以适当放宽风控以抓住机会")
        self.assertFalse(ok)
        self.assertIsNone(item)
        self.assertEqual(es.load_structured_memory(), [])

    def test_a_short_lesson_is_not_written(self):
        ok, reason, item = es.add_safe_lesson("太短")
        self.assertFalse(ok)
        self.assertIn("过短", reason)

    def test_a_valid_lesson_is_recorded(self):
        ok, reason, item = es.add_safe_lesson("在 4H 趋势向上时回踩不破前低可加仓")
        self.assertTrue(ok)
        self.assertIsNotNone(item)
        self.assertEqual(len(es.load_structured_memory()), 1)

    def test_an_existing_lesson_is_returned_without_duplication(self):
        # ★ 第 547 行
        text = "在 4H 趋势向上时回踩不破前低可加仓"
        first = es.add_safe_lesson(text)[2]
        ok, reason, again = es.add_safe_lesson(text)
        self.assertTrue(ok)
        self.assertIn("已存在", reason)
        self.assertEqual(again["id"], first["id"])
        self.assertEqual(len(es.load_structured_memory()), 1)

    def test_the_sample_size_defaults_to_three(self):
        _, _, item = es.add_safe_lesson("在 4H 趋势向上时回踩不破前低可加仓")
        self.assertEqual(item["sample_size"], 3)

    def test_the_category_is_recorded(self):
        _, _, item = es.add_safe_lesson("在 4H 趋势向上时回踩不破前低可加仓",
                                        category="MACRO")
        self.assertEqual(item["category"], "MACRO")


if __name__ == "__main__":
    unittest.main()

# ───────────────────── 「以后不再预设心法」的持久守卫 ─────────────────────
class NoPresetDoctrineTests(unittest.TestCase):
    """★ 用户 2026-10 的硬要求：**系统不再预设任何心法**。

    这组守卫的意义在于**防止回归** —— 预设最容易以"就加一条兜底心法"的形式悄悄回来，
    而它一旦回来，注入配额（8 条）就被长期占位，自进化学到的东西永远挤不进去。
    故判据放在**模块源码**层面：任何形式的预设计量表都会立刻翻红。
    """

    SOURCE = (Path(__file__).resolve().parents[2] / "scripts" / "evolution_shield.py").read_text(encoding="utf-8")

    def test_the_preset_constant_is_gone(self):
        self.assertFalse(hasattr(es, "BASELINE_LESSONS"))
        for name in ("BASELINE_LESSONS", "GOLDEN_LESSONS", "PRESET_LESSONS", "DEFAULT_LESSONS"):
            with self.subTest(name=name):
                self.assertNotIn(name, self.SOURCE,
                                 f"模块里不得再出现预设清单 {name}")

    def test_the_source_contains_no_hardcoded_lesson_literals(self):
        """预设计量表必然是"含 rule_text 的字面量列表"；源码里不许有这种形状。"""
        import ast as _ast
        tree = _ast.parse(self.SOURCE)
        offenders = []
        for node in _ast.walk(tree):
            if isinstance(node, (_ast.List, _ast.Tuple, _ast.Set)) and len(node.elts) > 0:
                dicts = [e for e in node.elts if isinstance(e, _ast.Dict)]
                if len(dicts) == len(node.elts) and len(dicts) > 1:
                    keys = {k.value for d in dicts for k in d.keys
                            if isinstance(k, _ast.Constant)}
                    if "rule_text" in keys:
                        offenders.append(getattr(node, "lineno", "?"))
        self.assertEqual(offenders, [],
                         f"发现疑似预设心法清单（行号 {offenders}）—— 系统不再预设心法")

    def test_a_fresh_library_is_empty(self):
        """全新环境（文件不存在）读出来必须是空库，不得凭空生出心法。"""
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "nope.json"
            with patch.object(es, "STRUCTURED_MEMORY_FILE", missing):
                self.assertEqual(es.load_structured_memory(), [])
                self.assertEqual(es.render_lessons([]), "")

    def test_no_seed_path_creates_lessons_on_its_own(self):
        """★ 没有任何路径会"自行播种"心法：空环境下调用方必须显式要求初始化。

        判据：对**不存在的**库调用清空/读取，都不得凭空创建文件，更不得造出条目。
        """
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "mem.json"
            with patch.object(es, "STRUCTURED_MEMORY_FILE", target):
                self.assertEqual(es.load_structured_memory(), [], "读取不得凭空造库")
                self.assertFalse(target.exists(), "读取不得写出文件")
                with self.assertRaises(es.MemoryVersionRequiredError):
                    es.reset_all_lessons(expected_version="")
                self.assertFalse(target.exists(), "缺少版本时不得写盘（更不得写预设）")
