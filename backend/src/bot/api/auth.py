"""Minimal bearer-token gate (plan 09 §2).

When `BOT_API_TOKEN` is set, every request must carry `Authorization: Bearer <token>`.
Two carve-outs:

* `GET /api/health` — the liveness probe (Docker healthcheck, load balancers) must work
  without a secret.
* `OPTIONS` preflight — CORS preflights never carry the Authorization header; rejecting
  them would break the browser before it ever sends the real request.

Deliberately NOT here: users, roles, sessions, JWT. This is a single shared secret for a
single-operator dashboard on a LAN. No token set -> middleware is not installed at all
(dev mode), so this class only runs when a token exists.
"""

from __future__ import annotations

import hmac

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

_PUBLIC_PATHS = frozenset({"/api/health"})


class BearerTokenMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: object, token: str) -> None:
        super().__init__(app)  # type: ignore[arg-type]
        self._token = token

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        if request.method == "OPTIONS" or request.url.path in _PUBLIC_PATHS:
            return await call_next(request)

        header = request.headers.get("Authorization", "")
        scheme, _, presented = header.partition(" ")
        # hmac.compare_digest keeps the check constant-time (no early-exit timing leak).
        if scheme.lower() != "bearer" or not hmac.compare_digest(presented, self._token):
            return JSONResponse(
                {"detail": "missing or invalid API token"}, status_code=401
            )
        return await call_next(request)
