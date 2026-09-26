"""Binance USDⓈ-M 私有请求的**签名串构建**（从 `exchanges/binance.py::signed_request` 搬出）。

规则（原样保留，勿"优化"）：

- 由本函数补齐毫秒 `timestamp` 与 `recvWindow=5000`；
- **空值与 `None` 一律剔除**（判据是 `v not in (None, "")`）—— 注意 `0` 与 `False`
  **不在此列**（`0 not in (None, "")` 为真）⇒ 数量为 0 的参数不会被悄悄丢掉。
  这是最容易"顺手改成 `if v`"而改坏的一处；
- 签名 = `HMAC-SHA256(secret, query_string)` 的十六进制小写；
- 最终串形如 `a=1&timestamp=<ms>&recvWindow=5000&signature=<hex>`。

`time` / `urlencode` / `hmac` / `hashlib` 由本模块**自己 import**（分析器第 11 条：标准库名
不当参数注入）。已核实现无测试对 `binance.time` / `binance.hmac` 打桩，故不构成接缝迁移；
HTTP 传送（`Request`/`urlopen`）仍留在门面，`urlopen` 的既有 `patch.object` 接缝不受影响。
"""
import hashlib
import hmac
import time
from urllib.parse import urlencode
from typing import Any, Dict, Optional


def build_signed_query(*,
        params,
        secret,
        timestamp_ms=None):
    """构建签名串。

    ⚠️ 2026-09-16 P1（时钟余量）：`timestamp_ms` 是**服务器校时后**的毫秒时间戳
    （`None` = 用本机时钟），由 `BinanceAdapter._server_aligned_ms()` 传入
    （实测本机比交易所慢 ~2.1s、而 recvWindow=5000ms，只剩 ~2.9s 传输/排队余量，
    已实测撞到 `[-1021] Timestamp for this request is outside of the recvWindow`）。
    把校时做成**显式入参**而非改本机时钟：容器内无 CAP_SYS_TIME（`date -s` 被拒），
    且宿主机无 NTP；显式入参也让该行为可被测。
    """
    query_dict = dict(params or {})
    query_dict["timestamp"] = int(timestamp_ms if timestamp_ms is not None
                                  else time.time() * 1000)
    query_dict["recvWindow"] = 5000
    clean_query = {k: v for k, v in query_dict.items() if v not in (None, "")}
    query_string = urlencode(clean_query)
    signature = hmac.new(secret.encode("utf-8"), query_string.encode("utf-8"), hashlib.sha256).hexdigest()
    full_query = f"{query_string}&signature={signature}"
    return full_query
