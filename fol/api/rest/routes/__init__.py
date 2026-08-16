"""REST API routes."""

from api.rest.routes.conversation import router as conversation_router
from api.rest.routes.memory import router as memory_router
from api.rest.routes.tools import router as tools_router
from api.rest.routes.plugins import router as plugins_router
from api.rest.routes.proactive import router as proactive_router
from api.rest.routes.settings import router as settings_router

__all__ = [
    "conversation_router",
    "memory_router",
    "tools_router",
    "plugins_router",
    "proactive_router",
    "settings_router",
]
