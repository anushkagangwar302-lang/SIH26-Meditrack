"""API v1 routers. Clinical routers must use require_intake_session."""

from app.api.v1.auth_routes import (
    assert_consents,
    get_current_principal,
    require_intake_session,
    require_staff,
    router as auth_router,
)

__all__ = [
    "assert_consents",
    "auth_router",
    "get_current_principal",
    "require_intake_session",
    "require_staff",
]
