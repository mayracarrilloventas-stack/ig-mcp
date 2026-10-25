#!/usr/bin/env python3
"""
HTTP entry point for the Instagram MCP Server.

Serves the same tools, resources and prompts as the stdio server over the
MCP Streamable HTTP transport, so it can be added as a remote connector
(e.g. in claude.ai). The endpoint lives at /<MCP_SECRET_PATH>/mcp so that
only someone who knows the secret URL can use the Instagram account.
"""

import contextlib
import logging
import os
import secrets
import sys

import structlog
import uvicorn
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from starlette.applications import Starlette
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.routing import Mount, Route

from . import instagram_mcp_server
from .config import get_settings
from .instagram_client import InstagramClient

logger = structlog.get_logger(__name__)


def create_app() -> Starlette:
    """Build the Starlette app that serves MCP over HTTP."""
    secret_path = os.environ.get("MCP_SECRET_PATH", "").strip("/")
    if len(secret_path) < 24:
        print(
            "MCP_SECRET_PATH must be set to a random string of at least 24 "
            f"characters. Example: {secrets.token_urlsafe(32)}",
            file=sys.stderr,
        )
        sys.exit(1)

    mcp_server = instagram_mcp_server.InstagramMCPServer()
    session_manager = StreamableHTTPSessionManager(
        app=mcp_server.server, stateless=True
    )

    mcp_path = f"/{secret_path}/mcp"

    async def handle_mcp(scope, receive, send):
        if scope["type"] == "http" and scope["path"].rstrip("/") == mcp_path:
            await session_manager.handle_request(scope, receive, send)
            return
        response = JSONResponse({"error": "not found"}, status_code=404)
        await response(scope, receive, send)

    async def health(_request):
        return PlainTextResponse("ok")

    @contextlib.asynccontextmanager
    async def lifespan(_app):
        instagram_mcp_server.instagram_client = InstagramClient()
        if not await instagram_mcp_server.instagram_client.validate_access_token():
            logger.error("Invalid Instagram access token")
            sys.exit(1)
        logger.info("Instagram access token validated successfully")
        async with session_manager.run():
            yield

    return Starlette(
        routes=[
            Route("/health", health),
            Mount("/", app=handle_mcp),
        ],
        lifespan=lifespan,
    )


def main():
    """Main entry point."""
    settings = get_settings()
    logging.basicConfig(level=getattr(logging, settings.log_level))
    uvicorn.run(
        create_app(),
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "8000")),
        proxy_headers=True,
        forwarded_allow_ips="*",
    )


if __name__ == "__main__":
    main()
