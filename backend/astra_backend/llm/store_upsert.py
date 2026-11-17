"""`upsert_model` 的两条**写入路径**（B4 收尾，从 `llm/store.py` 搬出）。

| 函数 | 职责 |
|---|---|
| `write_model_into_top_level_list` | 顶层 `config["models"]` 的更新/追加：命中则**原地更新**，否则追加新条目 |
| `write_model_into_providers_local_list` | 把同一个模型登记进其**供应商本地的 `models` 数组**（同一套命中/追加语义） |

两者 **0 返回值**：结果按引用写进调用方传入的 `models` / `prov`（与 `load_llm_config`
的两段归一化同风格）。密钥有意**不**快照进模型条目 —— 唯一存放处是供应商，
读取时由 `init_llm_config` 合并注入（见 `store.py` 内注释），故这里也不带 `api_key`。
"""
def write_model_into_providers_local_list(*,
        caps,
        ctx_len,
        default_effort,
        desc,
        mid,
        name,
        prov,
        reasoning_type):
    # Also update provider's local models array
    if prov:
        prov_models = prov.setdefault("models", [])
        p_existing = next((m for m in prov_models if m.get("id") == mid), None)
        if p_existing:
            p_existing["name"] = name
            p_existing["capabilities"] = caps
            p_existing["reasoning_type"] = reasoning_type
            p_existing["reasoning_effort"] = default_effort
            p_existing["context_length"] = ctx_len
            p_existing["description"] = desc
        else:
            prov_models.append({
                "id": mid,
                "name": name,
                "capabilities": caps,
                "reasoning_type": reasoning_type,
                "reasoning_effort": default_effort,
                "context_length": ctx_len,
                "description": desc,
            })


def write_model_into_top_level_list(*,
        api_format,
        api_key,
        base_url,
        caps,
        ctx_len,
        default_effort,
        desc,
        existing,
        mid,
        models,
        name,
        provider_id,
        provider_name,
        reasoning_type):
    if existing:
        existing["name"] = name
        existing["provider_id"] = provider_id or existing.get("provider_id", "openai")
        existing["provider_name"] = provider_name or existing.get("provider_name", "自定义")
        existing["base_url"] = base_url
        if api_key:
            existing["api_key"] = api_key
        existing["api_format"] = api_format
        existing["reasoning_type"] = reasoning_type
        existing["reasoning_effort"] = default_effort
        existing["capabilities"] = caps
        existing["context_length"] = ctx_len
        existing["description"] = desc
    else:
        models.append({
            "id": mid,
            "name": name,
            "provider_id": provider_id or "openai",
            "provider_name": provider_name or "自定义",
            "base_url": base_url,
            "api_key": api_key,
            "api_format": api_format,
            "reasoning_type": reasoning_type,
            "reasoning_effort": default_effort,
            "capabilities": caps,
            "context_length": ctx_len,
            "description": desc,
        })

