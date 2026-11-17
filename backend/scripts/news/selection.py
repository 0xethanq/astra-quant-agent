"""快讯智能分类、权重分流与提示词语义标签化（纯判断与纯格式化逻辑）。

解决痛点：
原先仅按时间倒序粗暴截取前 6 条快讯，由于宏观高频快讯（汽车降价、黄金微调、地方民生等）
发稿密集，导致币圈行业重大突发（ETH 升级、标的币种异动、SEC 政策）被严重挤出。

本模块提供结构化加权分流算法：
1. 币圈强相关（持仓标的 > 重点币种 > 原生行业/监管）倾斜保底，通常占据 3~4 条；
2. 关键宏观（美联储/CPI/利率/地缘风险）保留 2 条作为流动性与系统风险大背景；
3. 杂音剔除与动态配额补齐：在加密资讯不足时由宏观平滑填充，反之亦然；
4. 输出带清晰语义标签（[币圈·ETH ⚡] / [宏观·重磅 🌐]），降低大模型理解负担。
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Set, Tuple

# 原生加密媒体平台白名单（命中直接判币圈）
CRYPTO_PLATFORMS: Set[str] = {
    "cointelegraph", "coindesk", "theblock", "okx", "binance", "decrypt",
    "blockworks", "odaily", "foresight", "panews", "jinse", "chaincatcher",
}

# 币圈特异性关键词表（用于精准识别未打标签的纯文本快讯）
CRYPTO_SPECIFIC_KEYWORDS: List[str] = [
    "btc", "eth", "sol", "doge", "xrp", "sui", "ada", "avax", "link", "dot", "arb",
    "op", "pepe", "shib", "ltc", "crypto", "blockchain", "bitcoin", "ethereum",
    "solana", "tether", "usdt", "usdc", "binance", "okx", "coinbase", "bybit",
    "kraken", "bitget", "etf", "sec", "cftc", "defi", "web3", "vitalik", "saylor",
    "token", "nft", "staking", "stablecoin", "layer2", "l2", "altcoin", "hashrate",
    "airdrop", "halving", "mainnet", "mempool", "validator", "gas fee",
    "加密", "比特币", "以太坊", "狗狗币", "瑞波", "数字货币", "虚拟货币", "区块链",
    "代币", "币安", "稳定币", "质押", "公链", "交易所", "链上", "矿工", "脱锚",
    "爆仓", "多空比", "黑客", "冷钱包", "硬分叉", "主网", "铭文", "符文"
]

# 核心系统级宏观与流动性关键词表
MACRO_CRITICAL_KEYWORDS: List[str] = [
    "美联储", "降息", "加息", "cpi", "非农", "利率", "通胀", "鲍威尔", "fed", "fomc",
    "rate cut", "rate hike", "inflation", "nonfarm", "payroll", "treasury", "美债",
    "收益率", "央行", "流动性", "关税", "地缘", "战争", "制裁", "核", "危机"
]


def is_crypto_news(item: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """判断快讯是否属于加密货币领域，并提取关联币种。"""
    title = str(item.get("title") or "")
    summary = str(item.get("summary") or "")
    text = f"{title} {summary}".lower()

    # 1. 已有币种标签
    raw_coins = item.get("coins") or []
    coins = [str(c).upper() for c in raw_coins if str(c).strip() and str(c).upper() != "NONE"]
    if coins:
        return True, coins

    # 2. 原生媒体平台
    platforms = [str(p).lower() for p in (item.get("platforms") or [])]
    if any(any(cp in p for cp in CRYPTO_PLATFORMS) for p in platforms):
        return True, []

    # 3. 币圈关键词匹配
    if any(re.search(rf"\b{re.escape(kw)}\b", text) if kw.isascii() else (kw in text) for kw in CRYPTO_SPECIFIC_KEYWORDS):
        return True, []

    return False, []


def is_macro_news(item: Dict[str, Any]) -> Tuple[bool, bool]:
    """判断快讯是否属于重要宏观/地缘流动性，返回 (is_macro, is_high_critical)。"""
    title = str(item.get("title") or "")
    summary = str(item.get("summary") or "")
    text = f"{title} {summary}".lower()
    importance = str(item.get("importance") or "low").lower()

    is_high = importance == "high"
    has_macro_kw = any(re.search(rf"\b{re.escape(kw)}\b", text) if kw.isascii() else (kw in text) for kw in MACRO_CRITICAL_KEYWORDS)

    if has_macro_kw or is_high:
        return True, is_high

    return False, False


def select_weighted_news(
    latest_news: List[Dict[str, Any]],
    target_coins: Optional[Set[str] | List[str]] = None,
    total_limit: int = 6,
    crypto_quota: int = 4,
    macro_quota: int = 2,
) -> List[Dict[str, Any]]:
    """从原始快讯池中加权筛选最具决策价值的资讯列表。

    策略规则：
    1. 优先提取当前在手/观察标的（target_coins）直接相关的币圈新闻；
    2. 保底分配 crypto_quota 条加密资讯；
    3. 保留 macro_quota 条高权重宏观资讯；
    4. 动态配额回退：当币圈资讯偏少时由宏观平滑填补，反之亦然，总数上限 total_limit；
    5. 稳定顺序：保留原流中相对时序（_orig_idx），确保自然时间流淌。
    """
    if not latest_news:
        return []

    targets = {str(c).upper() for c in (target_coins or [])}

    crypto_items: List[Tuple[int, int, int, Dict[str, Any], List[str], int]] = []
    macro_items: List[Tuple[int, int, int, Dict[str, Any], int]] = []
    other_items: List[Tuple[int, int, Dict[str, Any], int]] = []

    for idx, item in enumerate(latest_news):
        is_crypto, coins = is_crypto_news(item)
        imp = str(item.get("importance") or "low").lower()
        imp_score = 3 if imp == "high" else (2 if imp == "mid" else 1)

        if is_crypto:
            matched_targets = [c for c in coins if c in targets]
            # 优先级：持仓/关注标的直接命中 (3) > 其他特定币种 (2) > 行业通用 (1)
            prio = 3 if matched_targets else (2 if coins else 1)
            crypto_items.append((prio, imp_score, -idx, item, matched_targets or coins, idx))
        else:
            is_macro, is_high = is_macro_news(item)
            if is_macro:
                prio = 2 if is_high else 1
                macro_items.append((prio, imp_score, -idx, item, idx))
            else:
                other_items.append((imp_score, -idx, item, idx))

    # 各分池排序：高优先级 > 高重要度 > 原流靠前（-idx 倒序即原流正序）
    crypto_items.sort(key=lambda x: (x[0], x[1], x[2]), reverse=True)
    macro_items.sort(key=lambda x: (x[0], x[1], x[2]), reverse=True)
    other_items.sort(key=lambda x: (x[0], x[1]), reverse=True)

    # 1. 抽取币圈核心资讯（适度做同币种去重防刷屏：单个币种最多保留 2 条）
    selected_crypto: List[Dict[str, Any]] = []
    coin_counts: Dict[str, int] = {}
    for _, _, _, item, item_coins, orig_idx in crypto_items:
        primary_coin = item_coins[0] if item_coins else "INDUSTRY"
        if coin_counts.get(primary_coin, 0) >= 2 and len(selected_crypto) < crypto_quota:
            continue
        coin_counts[primary_coin] = coin_counts.get(primary_coin, 0) + 1
        item_copy = dict(item)
        item_copy["_derived_category"] = "crypto"
        item_copy["_matched_coins"] = item_coins
        item_copy["_orig_idx"] = orig_idx
        selected_crypto.append(item_copy)
        if len(selected_crypto) >= crypto_quota:
            break

    # 2. 抽取宏观重要资讯
    selected_macro: List[Dict[str, Any]] = []
    for _, _, _, item, orig_idx in macro_items:
        item_copy = dict(item)
        item_copy["_derived_category"] = "macro"
        item_copy["_orig_idx"] = orig_idx
        selected_macro.append(item_copy)
        if len(selected_macro) >= macro_quota:
            break

    # 3. 动态补足配额（若某一类不足，优先从另一类补齐，最后从 other 补）
    result: List[Dict[str, Any]] = selected_crypto + selected_macro

    if len(result) < total_limit:
        # 先尝试用剩余的币圈资讯补齐
        used_indices = {x.get("_orig_idx") for x in result}
        for _, _, _, item, item_coins, orig_idx in crypto_items:
            if orig_idx not in used_indices:
                item_copy = dict(item)
                item_copy["_derived_category"] = "crypto"
                item_copy["_matched_coins"] = item_coins
                item_copy["_orig_idx"] = orig_idx
                result.append(item_copy)
                used_indices.add(orig_idx)
                if len(result) >= total_limit:
                    break

    if len(result) < total_limit:
        # 再尝试用剩余的宏观资讯补齐
        used_indices = {x.get("_orig_idx") for x in result}
        for _, _, _, item, orig_idx in macro_items:
            if orig_idx not in used_indices:
                item_copy = dict(item)
                item_copy["_derived_category"] = "macro"
                item_copy["_orig_idx"] = orig_idx
                result.append(item_copy)
                used_indices.add(orig_idx)
                if len(result) >= total_limit:
                    break

    if len(result) < total_limit:
        # 最后用常规资讯保底
        used_indices = {x.get("_orig_idx") for x in result}
        for _, _, item, orig_idx in other_items:
            if orig_idx not in used_indices:
                item_copy = dict(item)
                item_copy["_derived_category"] = "general"
                item_copy["_orig_idx"] = orig_idx
                result.append(item_copy)
                used_indices.add(orig_idx)
                if len(result) >= total_limit:
                    break

    # 保留原流中的自然时序
    result.sort(key=lambda x: x.get("_orig_idx", 0))
    return result[:total_limit]


def format_news_for_prompt(
    selected_items: List[Dict[str, Any]],
    target_coins: Optional[Set[str] | List[str]] = None,
) -> List[str]:
    """将加权选出的快讯格式化为带有语义标签的提示词行。

    输出示例：
    - [币圈·ETH ⚡] [22:29] Vitalik Buterin maps Ethereum’s shift... (summary...)
    - [币圈·行业] [21:15] Binance deal gives Circle a boost... (summary...)
    - [宏观·重磅 🌐] [23:00] 一周展望：非农与PCE考验美联储利率路径... (summary...)
    """
    lines: List[str] = []
    targets = {str(c).upper() for c in (target_coins or [])}

    for item in selected_items:
        time_raw = str(item.get("time") or "")
        # 如果是 "2026-09-27 22:29:13"，提取时分 "22:29" 提升提示词密度，其余原样保留
        time_display = time_raw.split(" ")[1][:5] if " " in time_raw else (time_raw[:16] if time_raw else "--")

        title = str(item.get("title") or "").strip()
        summary = str(item.get("summary") or "").strip()
        # 摘要统一截断至 80 字，符合提示词标准
        summary_snip = f" ({summary[:80]}...)" if summary else ""

        category = item.get("_derived_category", "general")
        matched_coins = item.get("_matched_coins") or item.get("coins") or []
        imp = str(item.get("importance") or "low").lower()

        if category == "crypto":
            if matched_coins:
                primary = str(matched_coins[0]).upper()
                is_target = primary in targets
                badge = f"币圈·{primary} ⚡" if is_target else f"币圈·{primary}"
            else:
                badge = "币圈·行业"
        elif category == "macro":
            badge = "宏观·重磅 🌐" if imp == "high" else "宏观·流动性"
        else:
            badge = "市场要闻"

        lines.append(f"- [{badge}] [{time_display}] {title}{summary_snip}")

    return lines
