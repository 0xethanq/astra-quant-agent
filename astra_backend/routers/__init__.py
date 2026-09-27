"""Modular API Routers for ASTRA Backend."""
from .auth import router as auth_router
from .system import router as system_router
from .exchanges import router as exchanges_router
from .risk import router as risk_router
from .strategy import router as strategy_router
from .llm import router as llm_router
from .gateway import router as gateway_router
from .dashboard import router as dashboard_router
from .plaza import router as plaza_router

__all__ = [
    "auth_router",
    "system_router",
    "exchanges_router",
    "risk_router",
    "strategy_router",
    "llm_router",
    "gateway_router",
    "dashboard_router",
    "plaza_router",
]
