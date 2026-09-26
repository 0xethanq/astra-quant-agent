"""把生效模型同步到 `.env` 的**纯装配**（B4 收尾，从 `llm/store.py` 搬出）。

| 函数 | 内容 |
|---|---|
| `resolve_effective_endpoint` | 解析生效 `base_url` / `api_key` 的**优先级链**：模型自身 → 其供应商（`provider_id` 命中）→ 环境变量（`LLM_BASE_URL` / `OPENAI_BASE_URL`）→ OpenAI 默认；并统一 `rstrip("/")` |
| `build_env_values` | 组装要写进 `.env` 的值（含 `LLM_THINKING_TIMEOUT` 的 **5s–1800s 夹取**与整值格式归一），并在有 `api_key` 且允许时写密钥存储 |

## 为什么值得单独成函数

这两段是"配置生效"里**唯一有判定规则**的部分（优先级链、夹取、条件写密钥），
原本夹在 143 行的 `activate_provider_model` 中间，前后都是 IO。
搬出来后可对**每条优先级**单独设断言；IO（`update_env`/`refresh_settings`）留在门面。

`build_env_values` 里 `save_secrets` 的调用是**注入**的（不在 import 期绑定），
门面上 `patch.object(store, "save_secrets")` 类接缝照常生效。
"""
def resolve_effective_endpoint(*,
        config,
        os,
        target_model):
    base_url = target_model.get("base_url", "")
    api_key = target_model.get("api_key", "")
    m_pid = target_model.get("provider_id")
    if m_pid:
        prov = next((p for p in config.get("providers", []) if p.get("id") == m_pid), None)
        if prov:
            if not api_key:
                api_key = prov.get("api_key", "")
            if not base_url:
                base_url = prov.get("base_url", "")

    base_url = (base_url or os.getenv("LLM_BASE_URL") or os.getenv("OPENAI_BASE_URL") or "https://api.openai.com/v1").rstrip("/")
    return (base_url, api_key)


def build_env_values(*,
        api_key,
        base_url,
        effort,
        model_id,
        save_secrets,
        thinking_timeout):
    env_values = {
        "LLM_BASE_URL": base_url,
        "LLM_MODEL": model_id,
        "LLM_REASONING_EFFORT": effort,
    }
    if thinking_timeout is not None:
        timeout_val = max(5.0, min(float(thinking_timeout), 1800.0))
        env_values["LLM_THINKING_TIMEOUT"] = str(int(timeout_val) if timeout_val.is_integer() else timeout_val)
    if api_key:
        env_values["LLM_API_KEY"] = api_key
        if save_secrets:
            save_secrets({"LLM_API_KEY": api_key})
    return (env_values)

