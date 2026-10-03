"""测试观望明细诊断渲染与理由文本清洗逻辑。"""
import unittest

from scripts.ai_factor_trader import _clean_diagnostic_reason, _format_entry_diagnostics


class EntryDiagnosticsFormattingTests(unittest.TestCase):
    def test_clean_diagnostic_reason_strips_redundant_suffixes(self):
        """验证清洗逻辑能准确去除尾部反复出现的'观望'与冗余标点。"""
        cases = [
            ("震荡市未及箱体极值且CVD顶背离观望", "震荡市未及箱体极值且CVD顶背离"),
            ("已有在途空单微利未达加仓门槛，观望", "已有在途空单微利未达加仓门槛"),
            ("已有在途多单微亏严禁逆势补仓。观望", "已有在途多单微亏严禁逆势补仓"),
            ("贴盘VWAP中枢且动能衰竭严禁贴盘追单故观望", "贴盘VWAP中枢且动能衰竭严禁贴盘追单"),
            ("偏离VWAP且CVD背离无结构确认保持观望", "偏离VWAP且CVD背离无结构确认"),
            ("多单已推保本锁利但CVD顶背离禁加仓", "多单已推保本锁利但CVD顶背离禁加仓"),
            ("", ""),
            (None, ""),
        ]
        for raw, expected in cases:
            self.assertEqual(_clean_diagnostic_reason(raw), expected)

    def test_format_entry_diagnostics_model_source(self):
        """验证大模型主动观望时的优雅排版格式。"""
        diag = [
            {"name": "ARB", "source": "model", "confidence": 75.0, "reason": "震荡市未及箱体极值且CVD顶背离观望"},
            {"name": "BTC", "source": "model", "confidence": 75.0, "reason": "已有在途空单微利未达加仓门槛观望"},
        ]
        res = _format_entry_diagnostics(diag)
        self.assertEqual(
            res,
            "ARB [模型 75%]: 震荡市未及箱体极值且CVD顶背离 | BTC [模型 75%]: 已有在途空单微利未达加仓门槛"
        )

    def test_format_entry_diagnostics_three_states_mixed(self):
        """验证模型自决、风控拦截与漏答兜底三态混合时的清晰区分。"""
        diag = [
            {"name": "ARB", "source": "model", "confidence": 75.0, "reason": "震荡市未及箱体极值且CVD顶背离观望"},
            {"name": "ETH", "source": "gate", "confidence": 72.0, "reason": "置信度 72% < 门禁 80%"},
            {"name": "SOL", "source": "omitted", "confidence": 0.0, "reason": ""},
        ]
        res = _format_entry_diagnostics(diag)
        self.assertEqual(
            res,
            "ARB [模型 75%]: 震荡市未及箱体极值且CVD顶背离 | ETH [风控拦截]: 置信度 72% < 门禁 80% | SOL [未作答]: 无新鲜决策，兜底观望"
        )

    def test_format_entry_diagnostics_empty(self):
        """空列表应返回空字符串。"""
        self.assertEqual(_format_entry_diagnostics([]), "")


if __name__ == "__main__":
    unittest.main()
