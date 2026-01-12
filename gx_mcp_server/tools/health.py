"""Simple health check tool."""

from typing import TYPE_CHECKING

from starlette.requests import Request
from starlette.responses import Response

from gx_mcp_server.logging import logger

if TYPE_CHECKING:
    from fastmcp import FastMCP


def ping() -> dict:
    """Check if the gx-mcp-server is running and responsive.

    WHEN TO USE:
    - As a simple health check before starting a validation workflow
    - To verify the MCP connection is working
    - For monitoring and alerting systems
    - To troubleshoot connectivity issues

    WHAT IT CHECKS:
    - Server is running and accepting requests
    - Basic server functionality is operational

    Returns:
        Dictionary containing:
        - status: "ok" if server is healthy

    Examples:
        # Verify server is running
        >>> ping()
        {"status": "ok"}

        # Use in monitoring
        >>> result = ping()
        >>> if result["status"] == "ok":
        ...     print("Server is healthy")
    """
    logger.debug("Health check ping")
    return {"status": "ok"}


async def health(_: Request) -> Response:
    """HTTP health endpoint."""
    logger.debug("HTTP health check")
    return Response(status_code=200, content="OK")


def register(mcp_instance: "FastMCP") -> None:
    """Register health tools."""
    mcp_instance.tool()(ping)
