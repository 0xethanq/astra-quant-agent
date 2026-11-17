from __future__ import annotations
import base64
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import astra_backend.notifications as notifications
import astra_backend.okx_trade_service as okx
import scripts.okx_rest as okx_rest
import scripts.prompt_library as prompts
from astra_gateway.events import GatewayEvent
from astra_gateway.store import GatewayStore
from scripts.okx_runtime import OKXEnvironment


class OKXV5Tests(unittest.TestCase):
    # V5 私有 HTTP 传输已并入 scripts.okx_rest 统一通道（okx_trade_service._request
    # 是委托门面）；旧测试 patch astra_backend.okx_trade_service.urllib.request 的
    # 目标模块属性已不存在。迁移到统一通道真实 HTTP 边界：patch.object(
    # scripts.okx_rest, "urlopen")，断言签名头/v5 路径/sCode fail-closed 原意图不变。
    def _response(self, body):
        class Response:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *_): return False
            def read(self): return body
        return Response()

    def test_demo_request_is_signed_and_uses_v5_header(self):
        import hashlib
        import hmac
        from urllib.parse import urlsplit
        env=OKXEnvironment("demo","AK","SK","PP")
        captured={}
        def open_(request,timeout=0):
            captured["request"]=request; return self._response(b'{"code":"0","data":[]}')
        with patch.object(okx_rest,"urlopen",side_effect=open_):
            self.assertEqual(okx._request("GET","/api/v5/account/positions",{"instType":"SWAP"},env),[])
        req=captured["request"]
        headers={k.lower():v for k,v in req.header_items()}
        split=urlsplit(req.full_url)
        request_path=split.path+(("?"+split.query) if split.query else "")
        self.assertEqual(split.netloc,"www.okx.com")
        self.assertEqual(request_path,"/api/v5/account/positions?instType=SWAP")
        self.assertEqual(headers["x-simulated-trading"],"1")
        self.assertEqual(headers["ok-access-key"],"AK")
        self.assertEqual(headers["ok-access-passphrase"],"PP")
        message=headers["ok-access-timestamp"]+"GET"+request_path
        expected=base64.b64encode(hmac.new(env.secret_key.encode(),message.encode(),hashlib.sha256).digest()).decode()
        self.assertEqual(headers["ok-access-sign"],expected)

    def test_business_scode_fails_closed(self):
        env=OKXEnvironment("live","AK","SK","PP")
        with patch.object(okx_rest,"urlopen",return_value=self._response(b'{"code":"0","data":[{"sCode":"51008","sMsg":"margin"}]}')):
            with self.assertRaises(RuntimeError) as ctx:
                okx._request("POST","/api/v5/trade/close-position",{"instId":"BTC-USDT-SWAP"},env)
        self.assertIn("51008",str(ctx.exception))


class ChannelBusinessCodeTests(unittest.TestCase):
    def test_wecom_http_200_error_is_failure(self):
        env={"ASTRA_WECHAT_WEBHOOK":"https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=x"}
        with patch.object(notifications,"validate_outbound_url",return_value=env["ASTRA_WECHAT_WEBHOOK"]), patch.object(notifications,"_post_json",return_value=(True,"HTTP 200",{"errcode":93000,"errmsg":"denied"})):
            self.assertFalse(notifications.send_channel("wechat","x",env)[0])

    def test_telegram_http_200_error_is_failure(self):
        env={"ASTRA_TELEGRAM_BOT_TOKEN":"T","ASTRA_TELEGRAM_CHAT_ID":"1"}
        # 第七十八刀：`_post_json` 已假，但 telegram 分支发送前还调
        # `validate_outbound_url`（SSRF 防线，内部 getaddrinfo 真解析
        # api.telegram.org）—— 本用例验证的是**业务响应码判定**，
        # 不该为它发真 DNS（离线守护下必被拦；wecom 用例同款 patch）。
        with patch.object(notifications,"validate_outbound_url",
                          side_effect=lambda u, **k: u), \
             patch.object(notifications,"_post_json",return_value=(True,"HTTP 200",{"ok":False,"description":"denied"})):
            self.assertFalse(notifications.send_channel("telegram","x",env)[0])

    def test_qq_http_200_error_is_failure(self):
        env={"ASTRA_QQ_APP_ID":"A","ASTRA_QQ_CLIENT_SECRET":"S","ASTRA_QQ_OPENID":"O"}
        responses=[(True,"HTTP 200",{"access_token":"T"}),(True,"HTTP 200",{"code":11248,"message":"denied"})]
        with patch.object(notifications,"_post_json",side_effect=responses): self.assertFalse(notifications.send_channel("qq","x",env)[0])

    def test_diagnose_never_sends(self):
        env={"ASTRA_TELEGRAM_BOT_TOKEN":"T","ASTRA_TELEGRAM_CHAT_ID":"1"}
        with patch.object(notifications,"_post_json") as post:
            self.assertEqual(notifications.diagnose_channel("telegram",env)["status"],"ready"); post.assert_not_called()


class PromptModuleTests(unittest.TestCase):
    def test_layout_reorders_and_overrides_editable_base(self):
        """排序照旧生效；"改写基座"的**新契约**（2026-09-30）是"降级为覆盖层后生效"。

        ## 契约为什么变了

        `source=="base"` 的产品承诺是**跟随代码发版**（前端 `source.baseTip`：
        "与代码基座逐字相同：代码升级后会自动同步到本方案"）。旧契约让
        `apply_module_layout` 直接采用布局里那段被改过的 base 正文，等于**冻结**了它：
        代码升级再也到不了这个方案，且工坊显示存档、实发用存档，两边都偏离基座却无人知道。

        新契约把职责切两半（`normalize_base_modules` ⨯ `demote_edited_base_modules`）：
        `source=="base"` 一律等于现网基座；用户改动由**保存路径**降级为 `legacy`
        覆盖层后原样生效。故本用例分两段断言，两段都必须绿：
        （1）未降级的改写 base ⇒ 被治愈成现网基座（跟随发版）；
        （2）经保存路径降级的同一改写 ⇒ 真的出现在实发文本里（改动不丢）。
        """
        base="【A】\none\n\n【B】\ntwo"
        view=prompts.pipeline_view(base,{"pipelines":{}},"trading_system")
        self.assertEqual([x["title"] for x in view],["A","B"])
        view[0]["content"]="【A】\nchanged"
        profile={"pipelines":{"trading_system":[view[1],view[0]]}}

        # （1）裸改写：排序生效，正文被治愈为现网基座
        healed=prompts.apply_module_layout(base,profile,"trading_system","x")
        self.assertLess(healed.index("【B】"),healed.index("【A】"))
        self.assertNotIn("changed",healed)
        self.assertIn("【A】\none",healed)

        # （2）走保存路径降级后：排序生效且改动真的到达实发
        demoted=prompts.demote_edited_base_modules([view[1],view[0]], base, "trading_system")
        self.assertEqual([m["source"] for m in demoted], ["base","legacy"])
        compiled=prompts.apply_module_layout(base,{"pipelines":{"trading_system":demoted}},"trading_system","x")
        self.assertIn("changed",compiled)
        self.assertIn("【A】\none",compiled)  # 基座分节仍在（实发 = 基座 + 覆盖层）

    def test_unknown_live_base_section_is_preserved(self):
        old={"pipelines":{"trading_user":[{"id":"a","title":"旧模块","content":"old","enabled":True,"source":"base"}]}}
        compiled=prompts.apply_module_layout("【新实时行情】\nlive",old,"trading_user","x")
        self.assertIn("live",compiled)

    def test_trading_user_layout_preserves_runtime_values_inside_locked_slots(self):
        base=("======================= 【当前决策时间戳与市场时效】 =======================\n"
              "【推演基准时间】: 2026-09-02 14:15:06\n"
              "【当前账户可用资金】: 3858.73 USDT\n\n"
              "======================= 【账户当前持仓与风险敞口全景】 =======================\n"
              "【账户持仓概况】: 当前系统总持仓 1/6\n"
              "【当前活动在途持仓明细】:\n- SOL 多仓 4张\n\n"
              "======================= 【六币种原生行情、技术指标与筹码矩阵】 =======================\n"
              "【BTC (BTC-USDT-SWAP)】| 数据质量: valid\n- 现价: 77575\n\n"
              "【推演与决策任务】:\n完整严格 JSON Schema")
        layout=[
            {"id":"t","title":"当前决策时间戳与市场时效","content":"实时插槽：北京时间、账户可用资金。","enabled":True,"locked":True,"source":"base"},
            {"id":"p","title":"账户当前持仓与风险敞口全景","content":"实时插槽：持仓。","enabled":True,"locked":True,"source":"base"},
            {"id":"m","title":"六币种原生行情、技术指标与筹码矩阵","content":"实时插槽：行情。","enabled":True,"locked":True,"source":"base"},
            {"id":"d","title":"推演与决策任务","content":"【推演与决策任务】:\n完整严格 JSON Schema","enabled":True,"locked":False,"source":"base"},
        ]
        compiled=prompts.apply_module_layout(base,{"pipelines":{"trading_user":layout}},"trading_user","x")
        self.assertIn("2026-09-02 14:15:06",compiled)
        self.assertIn("3858.73 USDT",compiled)
        self.assertIn("当前系统总持仓 1/6",compiled)
        self.assertIn("BTC (BTC-USDT-SWAP)",compiled)
        self.assertLess(compiled.index("2026-09-02 14:15:06"),compiled.index("当前系统总持仓 1/6"))
        self.assertLess(compiled.index("当前系统总持仓 1/6"),compiled.index("BTC (BTC-USDT-SWAP)"))
        self.assertLess(compiled.index("BTC (BTC-USDT-SWAP)"),compiled.index("完整严格 JSON Schema"))

    def test_safety_trading_rules_are_live_locked_not_stale_profile_text(self):
        base="【三重滤网裁决协议】\n新规则：ADX 18~22 小仓参与\n\n【开仓与价格几何】\n目标 R:R ≥ 2.2"
        layout=[
            {"id":"a","title":"三重滤网裁决协议","content":"旧规则：ADX < 20 必须 WAIT","enabled":True,"locked":False,"source":"base"},
            {"id":"b","title":"开仓与价格几何","content":"旧规则：目标 R:R ≥ 2.5","enabled":True,"locked":False,"source":"base"},
        ]
        compiled=prompts.apply_module_layout(base,{"pipelines":{"trading_system":layout}},"trading_system","x")
        self.assertIn("ADX 18~22 小仓参与",compiled)
        self.assertIn("目标 R:R ≥ 2.2",compiled)
        self.assertNotIn("ADX < 20 必须 WAIT",compiled)

    def test_allpattern_preset_keeps_p0_and_patience_is_not_permanent_flatness(self):
        """出厂样板必须覆盖"全形态"，同时**不许削弱 P0**（2026-09-30 换预设后重写）。

        旧用例钉的是「全维度波段强化版」的措辞（"不得把稳健解释为长期空仓"等），
        那条预设已被淘汰。新判据守住同一件事：① P0 硬约束仍由执行层强制；
        ② 耐心（允许 WAIT）不得被写成"长期空仓"；③ 招式必须覆盖多形态而非只认一种。

        ★ 2026-09-30 提示词来源迁移后重钉：`prompts.PRESETS` 已是**结构-only stub**
        （pipelines 为空，只承担"出厂方案 id"的身份职责），正文只存
        `data/prompt_library.json`。旧判据读 `PRESETS["allpattern_swing"]["trading_system"]`
        只会读到空串 —— 那不是"样板没覆盖 P0"，而是读错了事实源。故改为读基线方案
        （`get_profile`；隔离渲染沙箱已把真基线复制进沙箱，普通运行走会话级沙箱副本）。
        旧锚点"允许空仓/不是保守"在新正文里的同义表述是「空仓 = 待命状态」与
        「减速不等于反转」「这是纪律，不是保守」，一并按同一意图钉住。
        """
        profile = prompts.get_profile("allpattern_swing")
        ts = prompts.compile_modules(profile["pipelines"]["trading_system"])
        tu = prompts.compile_modules(profile["pipelines"]["trading_user"])
        self.assertGreater(len(ts), 500, "基线 trading_system 为空 —— 又读到了结构-only stub")
        self.assertGreater(len(tu), 500, "基线 trading_user 为空 —— 又读到了结构-only stub")
        self.assertIn("P0 不可覆盖硬约束", ts)
        self.assertIn("执行层强制", ts)
        for shape in ("顺势回踩", "顺势反弹", "假突破", "均值回归"):
            self.assertIn(shape, ts, f"样板未覆盖「{shape}」⇒ 又变成只认一种招式")
        self.assertIn("三件套", ts, "每单必须自证：形态命名·触发条件·失效位")
        self.assertNotIn("长期空仓", ts, "耐心不等于长期空仓")
        # 旧锚点「允许空仓 / 不是保守」的同一意图（耐心允许 WAIT，但不是永久平坦）
        self.assertIn("减速不等于反转", ts)
        self.assertIn("待命状态", ts)
        self.assertIn("这是纪律，不是保守", ts)
        self.assertIn("宁缺毋滥", tu)
        self.assertIn("不允许因怕亏而放掉已达标的机会", tu)

    def test_trading_decision_contract_cannot_be_replaced_by_editor_summary(self):
        base="【推演与决策任务】:\n必须输出严格 JSON，包含 position_management 与 decisions"
        layout=[{"id":"d","title":"推演与决策任务","content":"可编辑规则模块摘要","enabled":True,"locked":False,"source":"base"}]
        compiled=prompts.apply_module_layout(base,{"pipelines":{"trading_user":layout}},"trading_user","x")
        self.assertIn("必须输出严格 JSON",compiled)
        self.assertNotIn("可编辑规则模块摘要",compiled)


class GatewayFDTests(unittest.TestCase):
    def test_connections_are_closed(self):
        import gc
        with tempfile.TemporaryDirectory() as tmp:
            store=GatewayStore(Path(tmp)/"gateway.db")
            gc.collect()
            before=len(os.listdir("/proc/self/fd"))
            for i in range(150): store.set_state("x",str(i)); store.get_state("x"); store.stats()
            gc.collect()
            after=len(os.listdir("/proc/self/fd"))
            self.assertLessEqual(after-before,10)


if __name__ == "__main__": unittest.main()
