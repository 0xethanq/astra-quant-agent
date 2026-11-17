"""交易所统一适配层（OKX 专用）。

设计原则（源自 plan_local/ASTRA_DEEP_ROADMAP_2026-09.md，对齐 freqtrade/nautilus 模式）：

1. **能力表驱动**：适配器子类 = 一张差异声明字典（ExchangeCapabilities），
   标的命名、数量语义、触发价默认、限频、附属 TP/SL、大陆 IP 政策全部显式声明。
2. **显式不支持，永不静默模拟**：未实装的私有切面（下单/账户/保护单）一律抛
   ``ExchangeCapabilityError`` fail-closed——绝不返回假数据骗过上层。
3. **对外统一币本位，进 venue 前换算**：上层决策契约只谈「保证金 USDT / 杠杆 /
   现价」，``quote_qty_to_native()`` 按场所规格折算，且**两条分支都向下取整**：
   币数语义截断到 step、张数语义 `floor` —— 换算出的名义**永不超出**目标。
4. **行情与执行分离**（nautilus 模式）：本阶段 OKX 执行走自有直签链路
   （`okx_rest` / `okx_trade_service`），适配器面提供只读行情与能力声明。
   本层为 OKX 专用适配器基类。

符号规范：全系统内部 canonical 资产名 = 裸币种（"BTC"）；venue 原生 instId 只在
适配器边界内存在（OKX "BTC-USDT-SWAP"）。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from decimal import ROUND_DOWN, Decimal
from typing import Any, Dict, Optional

import requests

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
}


class ExchangeCapabilityError(RuntimeError):
    """能力缺失显式拒绝（fail-closed）。上层不得捕获后静默降级。"""


@dataclass(frozen=True)
class ExchangeCapabilities:
    venue: str                       # "okx"（本层只剩 OKX）
    display_name: str
    symbol_template: str             # e.g. "{base}-USDT-SWAP"
    quote: str = "USDT"
    # ---- 数量语义 ----
    quantity_unit: str = "contracts"  # "contracts"(张) | "base_asset"(币本位数量)
    signed_size: bool = False         # 载荷是否用「正多负空」的带符号张数
    # ---- 条件单/OCO 语义（先声明后实现）----
    supports_attached_tp_sl: bool = False   # OKX attachAlgoOrds 附带 TP/SL
    # ⚠️ 实现必须**显式传入**触发价格类型，不依赖任何交易所默认值（官方默认值会变，
    # 旧调研里「默认就是 MARK_PRICE」的断言已作废）。本字段只是本系统的语义标注。
    trigger_price_default: str = "last"     # 本系统内部语义标注（last/mark/index）
    # ---- 真实语义字段（审批出处逐所声明，勿再挤在 supports_orders 一栏）----
    # 订单 ID 类型（防 JS int64 精度损失）：
    #   "string"               — 原生即字符串（OKX ordId/algoId）
    #   "int64_id_string"      — int64 且响应带 id_string，读取一律用 id_string 字符串
    #   "int64_precision_risk" — int64 无 id_string，跨 JSON Number 链路必须 str 归一
    order_id_type: str = "string"
    native_amend: bool = False        # 原生改单端点（本仓 OKX 未实装 ⇒ False）
    decimal_amount: bool = False      # 十进制张数 amount 字符串（本仓 OKX 用整数张 ⇒ False）
    # 持仓模式族（仅声明支持域，永不自动切换用户账户；未支持档=禁新开仓并显示原因）
    # okx: ("net","long_short")——判定必须按本所自己的**词汇**，不得跨所套用
    position_modes: tuple = ()
    # 其中**载荷已验证、允许新开仓**的模式子集（宽于它的模式=检测得到但禁开，
    # 因为本系统没有在真实账户上核验过那种模式的下单/保护腿载荷）：
    #   okx: long_short（显式 posSide、平仓按腿方向，已在真实双向账户核验）
    #         net（净持仓）未核验 ⇒ 不在子集内
    # 空 = 不体检（不认识模式的实现维持原行为，绝不因"没实现"就停掉一个所）
    entry_ready_position_modes: tuple = ()
    conditional_family: str = "none"  # attached | independent_resource | algo_service
    protection_semantics: str = ""    # 保护生效条件的人读语义（见各所声明与 §0 设计纠正）
    # ---- 公共行情 ----
    max_candle_limit: int = 300
    bar_case: str = "upper"                 # "upper" 保留内部写法 / "lower" 转小写
    has_top_trader_ratio: bool = False
    has_taker_ratio: bool = False
    # ---- 私有面能力（除 OKX 现状外均为 False）----
    supports_account: bool = False
    supports_orders: bool = False
    # ---- G9 统一开闸判定（US-009 后收口）：适配器执行的 env 旗标单源声明 ----
    #: 空 = 经本适配器的执行面未实装/未启用（恒关闸，结构性，非风险开关）；
    #: 非空 = live 档开闸旗标名（sandbox 档自动映射 `<前缀>DEMO_EXECUTION` 变体），
    #: 判定单一入口 registry.execution_open（能力表 AND 环境双轴旗标）。
    adapter_execution_flag: str = ""
    # ---- 网络与合规现实（文档化，供选所/可用性矩阵使用）----
    mainland_ip_restricted: bool = False
    rate_limit_note: str = ""


@dataclass(frozen=True)
class InstrumentSpec:
    """合约规格——原生字段归一后的统一形态。"""
    venue: str
    inst_id: str
    base: str
    tick_size: float          # 最小价格变动
    step_size: float          # 最小数量增量（base_asset 语义用；contracts 用 ct_val 整数）
    ct_val: float             # 每张合约对应的币本位面值（base_asset 所恒为 1.0）
    min_size: float           # 原生单位最小下单量（张 或 币）
    max_leverage: float = 0.0
    status: str = "trading"
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)


#: 计价币后缀（用于**无分隔符**写法：`BTCUSDT` → `BTC`）。顺序有意义：长的先试。
_QUOTE_SUFFIXES = ("USDT", "USDC", "FDUSD", "BUSD", "TUSD", "USD")


def canonical_base(symbol: str) -> str:
    """任意写法（BTC / btc / BTC-USDT-SWAP / BTCUSDT）→ 裸币种 "BTC"。"""
    text = str(symbol or "").strip().upper()
    if ":" in text:                                   # PREFIX:BTC-USDT-SWAP → BTC-USDT-SWAP
        text = text.rsplit(":", 1)[1]
    for sep in ("-", "_", "/"):                       # BTC-USDT-SWAP / BTC_USDT → BTC
        if sep in text:
            text = text.split(sep)[0]
            break
    for quote in _QUOTE_SUFFIXES:                     # BTCUSDT / 1000PEPEUSDT → BTC / 1000PEPE
        if text.endswith(quote) and len(text) > len(quote):
            text = text[: -len(quote)]
            break
    return text


class BaseExchangeAdapter:
    """交易所适配器基类。子类必须声明 capabilities 并设置 base_url。

    端点档位：类属性 live_url/test_url 声明；实例化时若环境变量
    ``ASTRA_{VENUE}_TESTNET``=1 且该所声明了 test_url，则 base_url 指向沙盒。
    """

    capabilities: ExchangeCapabilities
    base_url: str = ""
    live_url: str = ""
    test_url: str = ""        # 旧单沙盒域声明，仅作未配 profile 场所的兼容兜底
    environment: str = "live"  # US-001：资金/沙盒档位（live|demo|testnet|sandbox）

    def __init__(self, session: Optional[requests.Session] = None,
                 environment: Optional[str] = None) -> None:
        """端点解析（US-001 起）：(venue, environment) → env_profiles 单一入口。

        environment=None → 按旧 ``ASTRA_{VENUE}_TESTNET`` 布尔兼容映射
        （未声明档的场所维持旧 live/test_url 行为；OKX 无旧沙盒档 ⇒ 恒 live）。
        """
        from . import env_profiles
        venue_key = str(getattr(self.capabilities, "venue", "") or "").lower()
        env = (str(environment or "").strip().lower()
               or env_profiles.legacy_environment_for(venue_key))
        if env_profiles.has_env(venue_key, env):
            self.base_url = env_profiles.resolve_base_url(venue_key, env)
        elif env != "live" and self.test_url:
            self.base_url = self.test_url          # 未配 profile 场所的旧兜底
        elif self.live_url:
            self.base_url = self.live_url
        self.environment = env
        self._session = session
        self._specs_cache: Dict[str, InstrumentSpec] = {}

    # ------------------------------------------------------------------
    # 会话与公共 HTTP（读-only、fail-soft：失败返回 None，不抛不炸上层）
    # ------------------------------------------------------------------
    def get_session(self) -> requests.Session:
        if self._session is None:
            s = requests.Session()
            s.headers.update(DEFAULT_HEADERS)
            self._session = s
        return self._session

    def _public_get(self, path: str, params: Optional[Dict[str, Any]] = None,
                    timeout: float = 4.0) -> Any:
        url = f"{self.base_url}{path}"
        try:
            resp = self.get_session().get(url, params=params, timeout=timeout)
            if resp.status_code != 200:
                return None
            return resp.json()
        except Exception:
            return None

    # ------------------------------------------------------------------
    # 切面 1：标的命名双向转译
    # ------------------------------------------------------------------
    def native_symbol(self, symbol: str) -> str:
        """canonical 资产名 → venue 原生 instId。"""
        return self.capabilities.symbol_template.format(base=canonical_base(symbol))

    def canonical(self, inst_id: str) -> str:
        """venue 原生 instId → canonical 资产名。"""
        return canonical_base(inst_id)

    def to_bar(self, bar: str) -> str:
        """统一周期（内部 OKX 风格 15m/1H/4H）→ venue 字面量。"""
        b = str(bar or "15m").strip()
        if self.capabilities.bar_case == "lower":
            return b.lower()
        return b

    # ------------------------------------------------------------------
    # 切面 2：公共行情（子类实现；统一返回归一形态或 None）
    # ------------------------------------------------------------------
    def fetch_ticker(self, symbol: str) -> Optional[Dict[str, Any]]:
        raise NotImplementedError

    def fetch_candles(self, symbol: str, bar: str = "15m",
                      limit: int = 100) -> Optional[list]:
        raise NotImplementedError

    def fetch_funding_rate(self, symbol: str) -> Optional[float]:
        raise NotImplementedError

    def fetch_orderbook(self, symbol: str, depth: int = 20) -> Optional[Dict[str, Any]]:
        raise NotImplementedError

    def fetch_top_trader_ratio(self, symbol: str) -> Optional[float]:
        """大户持仓多空比。能力缺失 → 显式 None + 上层按数据健康度处理，不伪造。"""
        if not self.capabilities.has_top_trader_ratio:
            return None
        raise NotImplementedError

    # ------------------------------------------------------------------
    # 切面 3：合约规格
    # ------------------------------------------------------------------
    def fetch_instrument_spec(self, symbol: str, refresh: bool = False) -> Optional[InstrumentSpec]:
        inst = self.native_symbol(symbol)
        if not refresh and inst in self._specs_cache:
            return self._specs_cache[inst]
        spec = self._load_spec(inst)
        if spec:
            self._specs_cache[inst] = spec
        return spec

    def _load_spec(self, inst_id: str) -> Optional[InstrumentSpec]:
        raise NotImplementedError

    # ------------------------------------------------------------------
    # 切面 4：数量语义换算层（对外币本位 → 原生单位：**币数与张数一律向下取整**）
    # ------------------------------------------------------------------
    def quote_qty_to_native(self, notional_usdt: float, price: float,
                            spec: InstrumentSpec) -> float:
        """名义价值 USDT + 现价 + 规格 → 该场所原生下单量（正数）。

        - base_asset 语义：币数，向下截断到 step_size；
        - contracts 语义（OKX）：整数张，`floor` 后校验最小张数。

        ⚠️ **两条分支一律向下取整**，故换算出的名义**永不超出**目标（第一百五十三刀）：

        - 币数分支：`ROUND_DOWN` 截断到 step；
        - 张数分支：`floor`（曾为四舍五入 —— 那会最坏向上多买半张：每张 300U、目标 450U 时
          1.5 张 ⇒ 2 张 = 600U，**+33%**，直接顶破按笔保证金上限；用户拍板改为 floor）。

        代价方向相反且可接受：向下取整可能让单子更常低于最小张数而被拒（少下单，不超买）。
        换算失败/低于最小名义价值 → 0.0（调用方据此拒单，fail-closed）。

        注：本函数是「按名义额估整数张」的便利换算，不是数量类型禁令 ——
        支持十进制 `amount` 的实现（`capabilities.decimal_amount=True` 且环境合约
        规格许可）可在下单入口显式传 Decimal/十进制字符串 amount 绕过本整数换算，
        不得把「所有合约必须 int 张数」当硬编码事实（本仓 OKX 用整数张，故该位为 False）。
        """
        if notional_usdt <= 0 or price <= 0:
            return 0.0
        cap = self.capabilities
        if cap.quantity_unit == "base_asset":
            qty = Decimal(str(notional_usdt / price))
            step = Decimal(str(spec.step_size or 1e-9))
            qty = (qty / step).to_integral_value(rounding=ROUND_DOWN) * step
            native = float(qty)
            if native < spec.min_size or native * price < 1e-9:
                return 0.0
            return native
        # contracts：每张名义价值 = price * ct_val
        per_contract = price * (spec.ct_val or 1.0)
        if per_contract <= 0:
            return 0.0
        # 向下取整（用户拍板，第一百五十三刀）：张数分支原先四舍五入，最坏**向上多买半张**
        # （每张 300U、目标 450U 时 1.5 张 ⇒ 2 张 = 600U，+33%，直接顶破按笔保证金上限）。
        # 现改为 floor ⇒ 换算名义**永不超出**目标；与**实盘路径**已有的
        # `astra_backend.execution.sizing.quantize_size`（同为 floor）方向一致。
        # `+ 1e-9` 是浮点噪声护栏（如 600/300 可能算成 1.9999999）：沿用实盘量化器的同一纪律。
        contracts = int(math.floor(notional_usdt / per_contract + 1e-9))
        if contracts < int(spec.min_size or 1) or contracts < 1:
            return 0.0
        return float(contracts)

    # ------------------------------------------------------------------
    # 切面 5/6：私有执行与账户 —— 本阶段全部显式拒绝
    # ------------------------------------------------------------------
    def _unsupported(self, facet: str) -> ExchangeCapabilityError:
        return ExchangeCapabilityError(
            f"{self.capabilities.display_name}: {facet} 未实装"
            f"（私有切面未实装；本层只提供只读行情与能力声明，显式拒绝而非伪造）"
        )

    def account_snapshot(self) -> Dict[str, Any]:
        raise self._unsupported("账户快照")

    def positions(self) -> list:
        raise self._unsupported("持仓查询")

    def place_order(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        raise self._unsupported("下单")

    def attach_protective_orders(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        raise self._unsupported("云端保护单（TP/SL）")

    def cancel_protective_orders(self, *args: Any, **kwargs: Any) -> Any:
        raise self._unsupported("撤销云端保护单")

    def cancel_order(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        raise self._unsupported("撤单")
