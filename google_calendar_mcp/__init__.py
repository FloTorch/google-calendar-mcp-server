"""
Google Calendar MCP Server.

MCP tools for Google Calendar management via FastMCP.
"""

__version__ = "1.0.0"

from google_calendar_mcp.auth import get_calendar_service
from google_calendar_mcp.config import (
    SCOPES,
    get_google_calendar_credentials,
)
from google_calendar_mcp.utils import (
    format_calendar_error,
    format_calendar_summary,
    format_event_summary,
)

__all__ = [
    "__version__",
    "SCOPES",
    "get_calendar_service",
    "get_google_calendar_credentials",
    "format_calendar_error",
    "format_calendar_summary",
    "format_event_summary",
]
