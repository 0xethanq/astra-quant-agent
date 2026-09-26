"""备份上传目标：S3 / OSS / WebDAV / 百度网盘（结构优化阶段 4·B3 第五十二刀）。

## 为什么单独成模块

`scripts/backup_runtime.py`（628 行）里有三块职责清晰但混住的内容：

| 簇 | 函数 | 行数 |
|---|---|---|
| **上传目标** | `calculate_sha256` + 4 个 `upload_*` + 3 个私有辅助 | 212 行（34%） |
| 归档与加解密 | `create_archive` / `encrypt_archive` / `decrypt_archive` / `verify_archive` / `_derive_key` | 130 行 |
| 作业编排 | `run_backup_job` / `deliver_target` / `sqlite_hot_backups` / 保留与清理 | 183 行 |

本模块是**上传目标**簇：它是唯一**不读任何模块级路径常量**的一块
（实测：`upload_*` 与三个辅助里 `ROOT` / `LOCAL_DIR` / `MANIFEST_DIR` /
`SQLITE_DIR` / `SCOPE_PATHS` 零出现），故可独立成模块且不影响门面的路径接缝。

## ⚠️ 依赖一律**调用时注入**，不在 import 期绑定

门面 `scripts/backup_runtime.py` 有两个**被测试 patch 的名字**：

1. `patch.object(br, "_urlencoded_json", …)` 与
   `patch.object(br, "_multipart_upload", …)`
   （`tests/audit/test_audit_batch5_d_tails.py` 的百度 OAuth 用例）；
2. `patch.object(backup_runtime, "calculate_sha256", return_value="hash")`
   （`tests/core/test_open_source_control.py` 的 `run_backup_job` 用例）。

若这些函数在 import 期从本模块取名字，补丁就**静默失效** ——
属于本仓已实证的"测试写进生产"事故类型。故：

- 本模块内 `upload_s3` 需要算 sha256 时，用**形参** `calculate_sha256`；
- 四个 `upload_*` 需要读凭证时，用**形参** `_credentials`；
- `upload_baidu_oauth` 另需 `_urlencoded_json` / `_multipart_upload` 两个形参。

门面保留同名薄壳，在**调用时**解析自己的全局并传入。

## ⚠️ 依赖方向

本模块只依赖标准库 + **函数内延迟导入**的
`astra_backend.backup_secrets` / `astra_backend.net_security` / `oss2` / `bypy`
（与搬移前完全一致 —— 这些延迟导入是原样搬过来的，未改成模块级导入）。
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


def calculate_sha256(path: Path) -> str:
    if not path.exists() or not path.is_file():
        raise RuntimeError(f"文件不存在，无法计算 SHA256: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

def _credentials(target: dict[str, Any]) -> dict[str, str]:
    from astra_backend.backup_secrets import load_credentials
    return load_credentials(str(target.get("credential_ref") or f"backup:{target['id']}"))

def _urlencoded_json(url: str, data: dict[str, Any] | None = None, timeout: int = 60) -> dict[str, Any]:
    from astra_backend.net_security import safe_urlopen
    body = urllib.parse.urlencode(data).encode() if data is not None else None
    request = urllib.request.Request(url, data=body, headers={"User-Agent": "ASTRA-Backup/6.2.0"}, method="POST" if body is not None else "GET")
    with safe_urlopen(request, timeout=timeout) as response:
        raw = response.read().decode("utf-8")
    payload = json.loads(raw or "{}")
    if payload.get("errno") not in (None, 0) or payload.get("error"):
        raise RuntimeError(str(payload.get("errmsg") or payload.get("error_description") or payload))
    return payload

def _multipart_upload(url: str, field_name: str, filename: str, content: bytes, timeout: int = 180) -> dict[str, Any]:
    from astra_backend.net_security import safe_urlopen
    boundary = f"----ASTRA{hashlib.sha256(os.urandom(16)).hexdigest()[:24]}"
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{field_name}\"; filename=\"{filename}\"\r\nContent-Type: application/octet-stream\r\n\r\n").encode() + content + f"\r\n--{boundary}--\r\n".encode()
    request = urllib.request.Request(url, data=body, headers={"Content-Type": f"multipart/form-data; boundary={boundary}", "User-Agent": "ASTRA-Backup/6.2.0"}, method="POST")
    with safe_urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8") or "{}")
    if payload.get("errno") not in (None, 0):
        raise RuntimeError(str(payload.get("errmsg") or payload))
    return payload

def upload_baidu_oauth(source: Path, target: dict[str, Any], *,
                       _credentials: Callable[[dict[str, Any]], dict[str, str]],
                       _urlencoded_json: Callable[..., dict[str, Any]],
                       _multipart_upload: Callable[..., Any]) -> dict[str, Any]:
    from astra_backend.backup_secrets import save_credentials
    creds = _credentials(target)
    app_key = creds.get("app_key", "")
    app_secret = creds.get("app_secret", "")
    refresh_token = creds.get("refresh_token", "")
    if not app_key or not app_secret or not refresh_token:
        raise RuntimeError("百度官方 OAuth 需要 App Key、App Secret 与 Refresh Token")
    # 审计D(2026-09-13)·凭证不进 query string：旧实现把 client_secret / refresh_token
    # 拼进 URL 走 GET——OAuth2 token 端点参数一旦入 query 就会被访问日志、代理、
    # Referer、浏览器历史逐字留存（RFC 6749 §2.3.1 明确要求 client credentials 走
    # POST body）。百度 token 端点对 POST form 与 GET query 等价受理，纯改道零风险。
    token_url = "https://openapi.baidu.com/oauth/2.0/token"
    token = _urlencoded_json(token_url, {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": app_key,
        "client_secret": app_secret,
    })
    access_token = str(token.get("access_token") or "")
    if not access_token:
        raise RuntimeError("百度 OAuth 未返回 Access Token")
    if token.get("refresh_token") and token["refresh_token"] != refresh_token:
        save_credentials(str(target.get("credential_ref")), {"refresh_token": token["refresh_token"]})
    chunk_size = 4 * 1024 * 1024
    block_list: list[str] = []
    with source.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            block_list.append(hashlib.md5(chunk).hexdigest())
    remote_dir = str(target.get("remote_path") or "ASTRA_Backups").strip("/")
    remote_path = f"/apps/AstraQuantumTrader/{remote_dir}/{source.name}" if remote_dir else f"/apps/AstraQuantumTrader/{source.name}"
    precreate_url = "https://pan.baidu.com/rest/2.0/xpan/file?method=precreate&access_token=" + urllib.parse.quote(access_token, safe="")
    common = {"path": remote_path, "size": source.stat().st_size, "isdir": 0, "autoinit": 1, "rtype": 3, "block_list": json.dumps(block_list)}
    precreated = _urlencoded_json(precreate_url, common)
    upload_id = str(precreated.get("uploadid") or "")
    if not upload_id:
        raise RuntimeError("百度网盘预创建未返回 uploadid")
    with source.open("rb") as handle:
        for part_seq in range(len(block_list)):
            chunk = handle.read(chunk_size)
            upload_url = "https://d.pcs.baidu.com/rest/2.0/pcs/superfile2?" + urllib.parse.urlencode({"method": "upload", "type": "tmpfile", "access_token": access_token, "path": remote_path, "uploadid": upload_id, "partseq": part_seq})
            uploaded = _multipart_upload(upload_url, "file", source.name, chunk)
            if uploaded.get("md5") and uploaded["md5"] != block_list[part_seq]:
                raise RuntimeError(f"百度分片 {part_seq} MD5 校验失败")
    create_url = "https://pan.baidu.com/rest/2.0/xpan/file?method=create&access_token=" + urllib.parse.quote(access_token, safe="")
    created = _urlencoded_json(create_url, {**common, "uploadid": upload_id})
    return {"success": True, "attempts": 1, "destination": remote_path, "fs_id": str(created.get("fs_id") or "")}

def upload_s3(source: Path, target: dict[str, Any], *,
             calculate_sha256: Callable[[Path], str],
             _credentials: Callable[[dict[str, Any]], dict[str, str]]) -> dict[str, Any]:
    """S3-compatible SigV4 upload without a mandatory boto3 dependency."""
    import hmac
    creds = _credentials(target)
    access = creds.get("access_key_id", "")
    secret = creds.get("secret_access_key", "")
    if not access or not secret:
        raise RuntimeError("S3 Access Key / Secret Key 未配置")
    endpoint = str(target.get("endpoint", "")).rstrip("/")
    bucket = str(target.get("bucket", ""))
    if not endpoint or not bucket:
        raise RuntimeError("S3 Endpoint 或 Bucket 未配置")
    region = str(target.get("region") or "us-east-1")
    key = "/".join(x for x in [str(target.get("remote_path") or "").strip("/"), source.name] if x)
    parsed = urllib.parse.urlparse(endpoint)
    host = parsed.netloc
    path = f"/{bucket}/{urllib.parse.quote(key, safe='/')}" if target.get("force_path_style") else f"/{urllib.parse.quote(key, safe='/')}"
    if not target.get("force_path_style"):
        host = f"{bucket}.{host}"
    now = datetime.now(timezone.utc)
    amzdate = now.strftime("%Y%m%dT%H%M%SZ")
    datestamp = now.strftime("%Y%m%d")
    payload_hash = calculate_sha256(source)
    headers = {"host": host, "x-amz-content-sha256": payload_hash, "x-amz-date": amzdate, "content-length": str(source.stat().st_size)}
    if creds.get("session_token"):
        headers["x-amz-security-token"] = creds["session_token"]
    signed_headers = ";".join(sorted(headers))
    canonical_headers = "".join(f"{k}:{headers[k]}\n" for k in sorted(headers))
    canonical = f"PUT\n{path}\n\n{canonical_headers}\n{signed_headers}\n{payload_hash}"
    scope = f"{datestamp}/{region}/s3/aws4_request"
    string_to_sign = f"AWS4-HMAC-SHA256\n{amzdate}\n{scope}\n{hashlib.sha256(canonical.encode()).hexdigest()}"
    sign = lambda key, msg: hmac.new(key, msg.encode(), hashlib.sha256).digest()
    signing = sign(sign(sign(sign(("AWS4" + secret).encode(), datestamp), region), "s3"), "aws4_request")
    headers["authorization"] = f"AWS4-HMAC-SHA256 Credential={access}/{scope}, SignedHeaders={signed_headers}, Signature={hmac.new(signing, string_to_sign.encode(), hashlib.sha256).hexdigest()}"
    import http.client
    connection = (http.client.HTTPSConnection if parsed.scheme == "https" else http.client.HTTPConnection)(host, timeout=300)
    connection.putrequest("PUT", path, skip_host=True)
    for k, v in headers.items():
        connection.putheader(k, v)
    connection.endheaders()
    with source.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            connection.send(chunk)
    response = connection.getresponse()
    response.read()
    connection.close()
    if response.status not in (200, 201):
        raise RuntimeError(f"S3 HTTP {response.status}")
    return {"success": True, "attempts": 1, "destination": f"s3://{bucket}/{key}"}

def upload_oss(source: Path, target: dict[str, Any], *,
               _credentials: Callable[[dict[str, Any]], dict[str, str]]) -> dict[str, Any]:
    try:
        import oss2
    except ImportError:
        raise RuntimeError("系统未安装 oss2 模块，请先安装 oss2 (pip install oss2)")
    creds = _credentials(target)
    access = creds.get("access_key_id", "")
    secret = creds.get("secret_access_key", "")
    if not access or not secret:
        raise RuntimeError("OSS AccessKey ID / Secret 未配置")
    endpoint = str(target.get("endpoint", "")).strip()
    bucket_name = str(target.get("bucket", "")).strip()
    if not endpoint or not bucket_name:
        raise RuntimeError("OSS Endpoint 或 Bucket 未配置")
    key = "/".join(x for x in [str(target.get("remote_path") or "").strip("/"), source.name] if x)
    bucket = oss2.Bucket(oss2.Auth(access, secret), endpoint, bucket_name)
    bucket.put_object_from_file(key, str(source))
    return {"success": True, "attempts": 1, "destination": f"oss://{bucket_name}/{key}"}

def upload_webdav(source: Path, target: dict[str, Any], *,
                  _credentials: Callable[[dict[str, Any]], dict[str, str]]) -> dict[str, Any]:
    from astra_backend.net_security import safe_urlopen
    creds = _credentials(target)
    endpoint = str(target["endpoint"]).rstrip("/")
    remote = str(target.get("remote_path") or "").strip("/")
    auth = ""
    username = creds.get("username", "")
    password = creds.get("password", "")
    if username:
        auth = "Basic " + base64.b64encode(f"{username}:{password}".encode()).decode()
    current = endpoint
    for part in [x for x in remote.split("/") if x]:
        current += "/" + urllib.parse.quote(part, safe="")
        req = urllib.request.Request(current, headers={"Authorization": auth} if auth else {}, method="MKCOL")
        try:
            safe_urlopen(req, timeout=20).close()
        except urllib.error.HTTPError as exc:
            if exc.code not in (301, 302, 405):
                raise
    url = current + "/" + urllib.parse.quote(source.name, safe="")
    parsed = urllib.parse.urlparse(url)
    import http.client
    connection = (http.client.HTTPSConnection if parsed.scheme == "https" else http.client.HTTPConnection)(parsed.netloc, timeout=300)
    path = parsed.path + (f"?{parsed.query}" if parsed.query else "")
    connection.putrequest("PUT", path)
    connection.putheader("Content-Type", "application/octet-stream")
    connection.putheader("Content-Length", str(source.stat().st_size))
    if auth:
        connection.putheader("Authorization", auth)
    connection.endheaders()
    with source.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            connection.send(chunk)
    response = connection.getresponse()
    response.read()
    connection.close()
    if response.status not in (200, 201, 204):
        raise RuntimeError(f"WebDAV HTTP {response.status}")
    return {"success": True, "attempts": 1, "destination": url}

def upload_baidu(source: Path, remote_path: str, retries: int) -> dict[str, Any]:
    try:
        import bypy
    except ImportError:
        return {"success": False, "attempts": 1, "destination": remote_path, "error": "系统未安装 bypy 模块"}
    remote = "/".join(part for part in Path(remote_path).parts if part not in {"/", "."})
    destination = f"{remote}/{source.name}" if remote else source.name
    last = ""
    for attempt in range(1, retries + 1):
        try:
            code = bypy.ByPy().upload(str(source), destination)
            if code == 0:
                return {"success": True, "attempts": attempt, "destination": f"/apps/bypy/{destination}"}
            last = f"ByPy 返回 {code}"
        except Exception as exc:
            last = f"{type(exc).__name__}: {exc}"
        if attempt < retries:
            time.sleep(min(attempt * 5, 30))
    return {"success": False, "attempts": retries, "destination": destination, "error": last}
