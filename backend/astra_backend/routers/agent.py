"""AI 策略运维指挥台（Agent）HTTP 与 SSE 流式路由。"""
from __future__ import annotations

import json
import re
from typing import Any, AsyncIterator

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import StreamingResponse

from astra_backend.agent.config import load_agent_config, save_agent_config
from astra_backend.agent.engine import run_agent_chat
from astra_backend.agent.proposals import apply_proposal, reject_proposal, rollback_proposal
from astra_backend.agent.store import AgentStore
from astra_backend.agent.tools_read import build_inspector_payload, build_proactive_insights, build_state_summary
from astra_backend.audit import record as audit_record
from astra_backend.config import refresh_settings
from astra_backend.dependencies import require_admin_header, require_superadmin
from astra_backend.schemas import (
    AgentChatRequest,
    AgentConfigUpdateRequest,
    AgentProposalApplyRequest,
    AgentProposalRejectRequest,
    AgentSessionCreateRequest,
    AgentSessionUpdateRequest,
)

router = APIRouter(tags=["agent"])
_STORE = AgentStore()
_SESSION_ID_RE = re.compile(r"^sess_[a-zA-Z0-9_-]{4,48}$")
_PROPOSAL_ID_RE = re.compile(r"^prop_[a-zA-Z0-9_-]{4,48}$")


def _validate_session_id(session_id: str) -> None:
    if not _SESSION_ID_RE.fullmatch(session_id or ""):
        raise HTTPException(status_code=400, detail=f"无效会话标识：{session_id}")


def _validate_proposal_id(proposal_id: str) -> None:
    if not _PROPOSAL_ID_RE.fullmatch(proposal_id or ""):
        raise HTTPException(status_code=400, detail=f"无效提案标识：{proposal_id}")


@router.get("/api/v1/admin/agent/config")
def get_agent_config(
    x_astra_session: str | None = Header(default=None, alias="X-Astra-Session"),
    x_astra_admin_token: str | None = Header(default=None),
) -> dict[str, Any]:
    refresh_settings()
    require_admin_header(x_astra_admin_token, x_astra_session)
    return load_agent_config()


@router.put("/api/v1/admin/agent/config")
def update_agent_config(
    payload: AgentConfigUpdateRequest,
    x_astra_session: str | None = Header(default=None, alias="X-Astra-Session"),
) -> dict[str, Any]:
    refresh_settings()
    actor = require_superadmin(x_astra_session)
    try:
        updated = save_agent_config(payload.model_dump(exclude_unset=True))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    audit_record(
        "agent.config.update",
        "success",
        {"actor": actor.get("username", "admin"), "model_id": updated.get("model_id"), "reasoning_effort": updated.get("reasoning_effort")},
    )
    return updated


@router.get("/api/v1/admin/agent/state-summary")
def get_agent_state_summary(
    x_astra_session: str | None = Header(default=None, alias="X-Astra-Session"),
    x_astra_admin_token: str | None = Header(default=None),
) -> dict[str, Any]:
    refresh_settings()
    require_admin_header(x_astra_admin_token, x_astra_session)
    return build_state_summary()


@router.get("/api/v1/admin/agent/insights")
def get_agent_insights(
    x_astra_session: str | None = Header(default=None, alias="X-Astra-Session"),
    x_astra_admin_token: str | None = Header(default=None),
) -> dict[str, Any]:
    refresh_settings()
    require_admin_header(x_astra_admin_token, x_astra_session)
    return build_proactive_insights()


@router.get("/api/v1/admin/agent/inspector")
def get_agent_inspector(
    x_astra_session: str | None = Header(default=None, alias="X-Astra-Session"),
    x_astra_admin_token: str | None = Header(default=None),
) -> dict[str, Any]:
    refresh_settings()
    require_admin_header(x_astra_admin_token, x_astra_session)
    return build_inspector_payload()


@router.get("/api/v1/admin/agent/sessions")
def list_agent_sessions(
    limit: int = 50,
    x_astra_session: str | None = Header(default=None, alias="X-Astra-Session"),
    x_astra_admin_token: str | None = Header(default=None),
) -> dict[str, Any]:
    refresh_settings()
    require_admin_header(x_astra_admin_token, x_astra_session)
    return {"sessions": _STORE.list_sessions(limit=limit)}


@router.post("/api/v1/admin/agent/sessions")
def create_agent_session(
    payload: AgentSessionCreateRequest,
    x_astra_session: str | None = Header(default=None, alias="X-Astra-Session"),
    x_astra_admin_token: str | None = Header(default=None),
) -> dict[str, Any]:
    refresh_settings()
    actor = require_admin_header(x_astra_admin_token, x_astra_session)
    session = _STORE.create_session(
        actor=str(actor.get("username") or "admin"),
        title=payload.title or "新会话",
        model_id=payload.model_id or "auto",
    )
    return {"session": session}


@router.get("/api/v1/admin/agent/sessions/{session_id}")
def get_agent_session_detail(
    session_id: str,
    x_astra_session: str | None = Header(default=None, alias="X-Astra-Session"),
    x_astra_admin_token: str | None = Header(default=None),
) -> dict[str, Any]:
    refresh_settings()
    require_admin_header(x_astra_admin_token, x_astra_session)
    _validate_session_id(session_id)
    session = _STORE.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    return {
        "session": session,
        "messages": _STORE.list_messages(session_id),
        "proposals": _STORE.list_proposals(session_id),
    }


@router.patch("/api/v1/admin/agent/sessions/{session_id}")
def update_agent_session_meta(
    session_id: str,
    payload: AgentSessionUpdateRequest,
    x_astra_session: str | None = Header(default=None, alias="X-Astra-Session"),
    x_astra_admin_token: str | None = Header(default=None),
) -> dict[str, Any]:
    refresh_settings()
    require_admin_header(x_astra_admin_token, x_astra_session)
    _validate_session_id(session_id)
    updated = _STORE.rename_session(session_id, title=payload.title, model_id=payload.model_id)
    if not updated:
        raise HTTPException(status_code=404, detail="会话不存在")
    return {"session": updated}


@router.delete("/api/v1/admin/agent/sessions/{session_id}")
def delete_agent_session(
    session_id: str,
    x_astra_session: str | None = Header(default=None, alias="X-Astra-Session"),
    x_astra_admin_token: str | None = Header(default=None),
) -> dict[str, Any]:
    refresh_settings()
    require_admin_header(x_astra_admin_token, x_astra_session)
    _validate_session_id(session_id)
    if not _STORE.delete_session(session_id):
        raise HTTPException(status_code=404, detail="会话不存在")
    return {"deleted": True, "session_id": session_id}


@router.post("/api/v1/admin/agent/sessions/{session_id}/chat")
async def stream_agent_chat(
    session_id: str,
    payload: AgentChatRequest,
    x_astra_session: str | None = Header(default=None, alias="X-Astra-Session"),
    x_astra_admin_token: str | None = Header(default=None),
) -> StreamingResponse:
    refresh_settings()
    actor = require_admin_header(x_astra_admin_token, x_astra_session)
    _validate_session_id(session_id)
    session = _STORE.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")

    is_superadmin = str(actor.get("role") or "") in ("superadmin", "legacy")
    username = str(actor.get("username") or "admin")

    async def _sse_generator() -> AsyncIterator[str]:
        async for ev in run_agent_chat(
            store=_STORE,
            session_id=session_id,
            user_message=payload.message,
            actor=username,
            is_superadmin=is_superadmin,
            model_override=payload.model_id,
        ):
            yield f"data: {json.dumps(ev, ensure_ascii=False, default=str)}\n\n"

    return StreamingResponse(
        _sse_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/api/v1/admin/agent/proposals/{proposal_id}/apply")
def apply_agent_proposal(
    proposal_id: str,
    payload: AgentProposalApplyRequest,
    x_astra_session: str | None = Header(default=None, alias="X-Astra-Session"),
) -> dict[str, Any]:
    refresh_settings()
    actor = require_superadmin(x_astra_session)
    _validate_proposal_id(proposal_id)
    try:
        return apply_proposal(
            store=_STORE,
            proposal_id=proposal_id,
            actor=str(actor.get("username") or "admin"),
            selected_item_ids=payload.selected_item_ids,
            confirmations=payload.confirmations,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/v1/admin/agent/proposals/{proposal_id}/rollback")
def rollback_agent_proposal(
    proposal_id: str,
    x_astra_session: str | None = Header(default=None, alias="X-Astra-Session"),
) -> dict[str, Any]:
    refresh_settings()
    actor = require_superadmin(x_astra_session)
    _validate_proposal_id(proposal_id)
    try:
        return rollback_proposal(
            store=_STORE,
            proposal_id=proposal_id,
            actor=str(actor.get("username") or "admin"),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"提案回滚失败：{exc}") from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"提案应用失败：{exc}") from exc


@router.post("/api/v1/admin/agent/proposals/{proposal_id}/reject")
def reject_agent_proposal(
    proposal_id: str,
    payload: AgentProposalRejectRequest,
    x_astra_session: str | None = Header(default=None, alias="X-Astra-Session"),
) -> dict[str, Any]:
    refresh_settings()
    actor = require_superadmin(x_astra_session)
    _validate_proposal_id(proposal_id)
    try:
        return reject_proposal(
            store=_STORE,
            proposal_id=proposal_id,
            actor=str(actor.get("username") or "admin"),
            reason=payload.reason,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/v1/admin/agent/proposals/{proposal_id}/rollback")
def rollback_agent_proposal(
    proposal_id: str,
    x_astra_session: str | None = Header(default=None, alias="X-Astra-Session"),
) -> dict[str, Any]:
    refresh_settings()
    actor = require_superadmin(x_astra_session)
    _validate_proposal_id(proposal_id)
    try:
        return rollback_proposal(
            store=_STORE,
            proposal_id=proposal_id,
            actor=str(actor.get("username") or "admin"),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"提案回滚失败：{exc}") from exc
