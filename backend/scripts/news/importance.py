"""快讯的**重要度分级**与**币种识别**（结构优化阶段 4·B3 第四十四刀）。

原样搬自 `scripts/news_sentiment_harvester.py` 的 L112–166（53 行），两块都是
**纯函数**（不读任何模块级路径常量）：

| 函数 | 作用 |
|---|---|
| `_classify_importance` | 标题+摘要 → `high` / `mid` / `low` |
| `_extract_coins` | 文本 → 涉及的币种列表（含中文别名） |

## 为什么这两块值得单独成模块

它们决定"一条快讯有多重要、牵扯哪些币"，是**判断逻辑**；而门面剩下的
`fetch_*` 是**取数**、`trigger_circuit_breaker` 是**落盘**。两者性质不同。

更实际的理由：这两个函数**不依赖任何可 patch 的模块常量**，抽走后
门面的接缝（`patch.object(nh, "NEWS_CACHE_FILE", ...)`）**完全不受影响** ——
这是本阶段"低锚点文件"里少见的**真能安全外提**的聚簇。

## ⚠️ 三条必须原样保留的行为

1. **`high` 优先于 `mid`**：先遍历高危词表，命中即返回。词表里
   `"暴跌"`/`"崩盘"` 属高危，而 `"暴涨"`/`"突破"` 只算中危 ——
   **方向不对称是有意的**（涨不恐慌，跌才恐慌）。
2. **中文别名用子串、ASCII 别名用词边界**：
   `re.search(rf"\\b{re.escape(a)}\\b", text) if a.isascii() else (a in text)`。
   中文没有词边界，用 `\\b` 会漏匹配；英文用子串又会把 `ETH` 匹配进
   `ETHEREUM` 之外的词。**勿"统一"成一种匹配方式。**
3. **`found[:4]` —— 最多返回 4 个币**：既有行为，控制晨报长度。**不是笔误。**
4. `text` 在 `_classify_importance` 里 **lower()**、在 `_extract_coins` 里
   **upper()** 且两侧补空格 —— 两者取不同方向，**勿"统一"**。
"""

from __future__ import annotations

import re

__all__ = ["_classify_importance", "_extract_coins", "is_crypto_or_macro_relevant"]

#: 高危关键词：系统性风险、崩盘、黑客、脱锚、破产清算、司法调查等
HIGH_KEYWORDS = [
    "脱锚", "depeg", "破产", "倒闭", "挤兑", "停止提现", "暂停提币",
    "51%攻击", "系统瘫痪", "暴跌", "崩盘", "黑客", "被盗", "黑天鹅",
    "起诉", "立案调查", "全面封杀", "严厉打击", "清算危机", "清退",
    "bankruptcy", "insolvent", "halt withdrawals", "freeze withdrawals",
    "exploit", "hacked", "plunge", "crash", "subpoena", "fraud", "scam"
]

#: 中等关注关键词：宏观决议、ETF、大额投融资、主网升级、重要合作、大额流入
MID_KEYWORDS = [
    "etf", "sec", "美联储", "降息", "加息", "鲍威尔", "cpi", "非农",
    "融资", "主网", "升级", "硬分叉", "战略合作", "巨鲸", "大额增持",
    "上市", "上线", "首发", "创历史新高", "暴涨", "突破",
    "fed", "rate cut", "inflation", "funding", "mainnet", "upgrade",
    "partnership", "whale", "inflow", "ath", "all-time high", "breakout"
]

#: 币种 → 别名（含中文）
COIN_ALIASES = {
    "BTC": ["BTC", "BITCOIN", "比特币"],
    "ETH": ["ETH", "ETHEREUM", "以太坊", "以太币"],
    "SOL": ["SOL", "SOLANA", "索拉纳"],
    "DOGE": ["DOGE", "DOGECOIN", "狗狗币"],
    "LINK": ["LINK", "CHAINLINK"],
    "AVAX": ["AVAX", "AVALANCHE", "雪崩"],
    "SUI": ["SUI"],
    "ADA": ["ADA", "CARDANO", "艾达币"],
    "XRP": ["XRP", "RIPPLE", "瑞波", "瑞波币"],
    "ARB": ["ARB", "ARBITRUM"],
    "UNI": ["UNI", "UNISWAP"],
}

#: `_extract_coins` 最多返回的币数（控制晨报长度，既有行为）
MAX_COINS = 4

#: 加密与核心宏观相关性词表（用于过滤传统通用快讯里的非金融杂音）
CRYPTO_MACRO_RELEVANT_KEYWORDS = [
    "btc", "eth", "sol", "doge", "xrp", "crypto", "blockchain", "bitcoin",
    "ethereum", "solana", "tether", "usdt", "usdc", "binance", "okx", "coinbase",
    "etf", "sec", "cpi", "fed", "美联储", "加密", "比特币", "以太坊", "数字货币",
    "虚拟货币", "区块链", "降息", "加息", "通胀", "鲍威尔", "非农", "央行", "流动性",
    "defi", "web3", "币安", "稳定币", "钱包", "质押", "公链", "交易所", "代币",
]


def is_crypto_or_macro_relevant(title: str, summary: str) -> bool:
    """判断通用快讯是否与加密资产、宏观流动性或监管风险强相关。"""
    text = f"{title} {summary}".lower()
    return any(kw in text for kw in CRYPTO_MACRO_RELEVANT_KEYWORDS)


def _classify_importance(title: str, summary: str) -> str:
    """根据快讯内容科学评定影响等级（high=重大/高危, mid=中等关注, low=普通快讯）。
    绝不盲目全标 high，避免狼来了式恐慌。"""
    text = f"{title} {summary}".lower()

    for kw in HIGH_KEYWORDS:
        if kw in text:
            return "high"

    for kw in MID_KEYWORDS:
        if kw in text:
            return "mid"

    return "low"


def _extract_coins(title: str, summary: str, target_coins: list) -> list:
    """从新闻文本中识别涉及的加密资产代码。"""
    text = f" {title} {summary} ".upper()
    found = []
    for c, aliases in COIN_ALIASES.items():
        if any(re.search(rf"\b{re.escape(a)}\b", text) if a.isascii() else (a in text) for a in aliases):
            found.append(c)
    for tc in (target_coins or []):
        if tc not in found:
            if re.search(rf"\b{re.escape(tc.upper())}\b", text):
                found.append(tc.upper())
    return found[:MAX_COINS]
