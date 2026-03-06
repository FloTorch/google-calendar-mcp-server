"""
Get events tool for Google Calendar MCP Server.
"""

import logging
from datetime import datetime
from typing import Optional

from mcp.server.fastmcp import Context

from google_calendar_mcp.auth import get_calendar_service
from google_calendar_mcp.config import (
    DEFAULT_CALENDAR_ID,
    DEFAULT_MAX_RESULTS,
    get_google_calendar_credentials,
)
from google_calendar_mcp.utils import format_calendar_error, format_event_summary

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


def get_events(
    calendar_id: str = DEFAULT_CALENDAR_ID,
    max_results: int = DEFAULT_MAX_RESULTS,
    time_min: Optional[str] = None,
    time_max: Optional[str] = None,
    impersonate_user: Optional[str] = None,
    ctx: Context = None
) -> str:
    """
    Get calendar events.
    
    Credentials are automatically retrieved from HTTP headers.
    No need to pass credentials as a parameter.
    
    Args:
        calendar_id: Calendar ID (default: 'primary')
        max_results: Maximum number of events to return (default: 10)
        time_min: Start time in ISO format (default: now)
        time_max: End time in ISO format (optional, for filtering to specific day)
        impersonate_user: Optional email for service account domain-wide delegation.
    
    Returns:
        String listing calendar events with their titles and start times.
    """
    try:
        headers = _extract_headers_from_context(ctx)
        credentials = get_google_calendar_credentials(headers)
        service = get_calendar_service(credentials, impersonate_user)
        
        if not time_min:
            time_min = datetime.utcnow().isoformat() + 'Z'
        
        # Build query parameters
        query_params = {
            'calendarId': calendar_id,
            'timeMin': time_min,
            'maxResults': max_results,
            'singleEvents': True,
            'orderBy': 'startTime'
        }
        
        # Add timeMax if provided (for date filtering to specific day)
        if time_max:
            query_params['timeMax'] = time_max
        
        events_result = service.events().list(**query_params).execute()
        
        events = events_result.get('items', [])
        
        if not events:
            return "No upcoming events found."
        
        # Determine timezone for formatting (try to get from time_min if provided)
        format_timezone = 'Asia/Kolkata'  # default
        if time_min:
            try:
                # Try to extract timezone from time_min or use default
                # For now, use default - could be enhanced to detect from time_min
                pass
            except:
                pass
        
        result = [format_event_summary(event, format_timezone) for event in events]
        count = len(events)
        return f"Found {count} event(s):\n" + "\n".join(result)
        
    except Exception as e:
        logger.exception("Error getting events")
        return f"Error getting events: {format_calendar_error(e)}. Please check your credentials and try again."
