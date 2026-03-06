"""
List calendars tool for Google Calendar MCP Server.
"""

import logging
from typing import Optional

from mcp.server.fastmcp import Context

from google_calendar_mcp.auth import get_calendar_service
from google_calendar_mcp.config import get_google_calendar_credentials
from google_calendar_mcp.utils import format_calendar_error, format_calendar_summary

logger = logging.getLogger(__name__)


def _extract_headers_from_context(ctx: Optional[Context]) -> dict:
    """Extract HTTP headers from request context as lowercase dict."""
    if not ctx:
        return {}
    
    # Check if headers are stored directly in context (for custom routes)
    if hasattr(ctx, "headers") and ctx.headers:
        return {k.lower(): v for k, v in ctx.headers.items()}
    
    # Try to extract from request context (for MCP tool calls)
    try:
        request_context = ctx.request_context
        if hasattr(request_context, "request") and request_context.request:
            request = request_context.request
            return {name.lower(): request.headers[name] for name in request.headers.keys()}
    except Exception as e:
        logger.debug(f"Could not extract headers from request context: {e}")
    
    return {}


def list_calendars(
    impersonate_user: Optional[str] = None,
    ctx: Context = None
) -> str:
    """
    List all available calendars.
    
    Credentials are automatically retrieved from HTTP headers.
    No need to pass credentials as a parameter.
    
    Args:
        impersonate_user: Optional email for service account domain-wide delegation.
    
    Returns:
        String listing all available calendars with their IDs.
    """
    try:
        headers = _extract_headers_from_context(ctx)
        credentials = get_google_calendar_credentials(headers)
        service = get_calendar_service(credentials, impersonate_user)
        calendars = service.calendarList().list().execute()
        
        items = calendars.get('items', [])
        if not items:
            return "No calendars found."
        
        result = [format_calendar_summary(cal) for cal in items]
        return "\n".join(result)
        
    except Exception as e:
        logger.exception("Error listing calendars")
        return f"Error listing calendars: {format_calendar_error(e)}"
