"""
Google Calendar MCP Server.

Exposes Google Calendar management tools via FastMCP:
list_calendars, get_events, create_event, check_availability, delete_event.
"""
import os
import logging
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple

from dateutil import parser as date_parser
from dateutil.tz import gettz

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request as StarletteRequest
from starlette.responses import JSONResponse

from google_calendar_mcp.auth import get_calendar_service
from google_calendar_mcp.config import (
    DEFAULT_CALENDAR_ID,
    DEFAULT_MAX_RESULTS,
    DEFAULT_REMINDERS_MINUTES,
    get_google_calendar_credentials,
)
from google_calendar_mcp.utils import (
    format_calendar_error,
    format_calendar_summary,
    format_event_summary,
    get_timezone_from_location,
    parse_natural_datetime,
)

logging.basicConfig(
    format="[%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)


def _extract_headers_from_context(ctx: Optional[Context]) -> Dict[str, str]:
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


# Create FastMCP server with gateway-specific settings
mcp = FastMCP(
    "Google Calendar MCP",
    instructions=(
        "Google Calendar MCP Server: Provides tools to view, create, update, and manage calendar events. "
        "Credentials are automatically retrieved from HTTP headers (X-Google-Calendar-Credentials, Authorization)."
    ),
    json_response=True,
    streamable_http_path="/google-calendar/mcp",
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    stateless_http=True,
)


# ---------------------------------------------------------------------------
# Custom Routes
# ---------------------------------------------------------------------------

@mcp.custom_route("/google-calendar/mcp", methods=["GET"])
async def discovery(_request: StarletteRequest) -> JSONResponse:
    """Discovery endpoint for transport detection."""
    return JSONResponse({
        "transport": "HTTP_STREAMABLE",
        "protocol": "streamable-http",
        "message": "Google Calendar MCP Server - Set transport to HTTP_STREAMABLE",
    })


@mcp.custom_route("/create_event", methods=["POST"])
async def create_event_simple(request: StarletteRequest) -> JSONResponse:
    """
    Simplified endpoint for creating events.
    
    Accepts a simplified JSON format with just the event arguments:
    {
      "summary": "Team Meeting",
      "date": "05 Mar 2026",
      "start_time": "8am",
      "end_time": "9am",
      "location": "New York",  // Optional: timezone auto-detected from location
      "attendees": "email@example.com"
    }
    
    No need for JSON-RPC wrapper - just send the arguments directly.
    """
    try:
        # Parse the simplified request body
        body = await request.json()
        
        # Extract headers from request and create a context-like object
        headers_dict = {name.lower(): value for name, value in request.headers.items()}
        
        # Create a simple context object that stores headers
        class SimpleContext:
            def __init__(self, headers):
                self.headers = headers
                self.request_context = None
        
        ctx = SimpleContext(headers_dict)
        
        # Call create_event tool directly with the arguments
        from google_calendar_mcp.tools.create_event import create_event as create_event_impl
        result = create_event_impl(ctx=ctx, **body)
        
        return JSONResponse({
            "success": True,
            "result": result
        })
        
    except Exception as e:
        logger.exception("Error in simplified endpoint")
        return JSONResponse(
            {
                "success": False,
                "error": str(e),
                "error_type": type(e).__name__
            },
            status_code=500
        )


@mcp.custom_route("/delete_event", methods=["POST"])
async def delete_event_simple(request: StarletteRequest) -> JSONResponse:
    """
    Simplified endpoint for deleting events.
    
    Accepts a simplified JSON format:
    
    Option 1 - Delete by Event ID (recommended):
    {
      "event_id": "abc123..."
    }
    
    Option 2 - Delete by date, time, and event name:
    {
      "date": "07 Mar 2026",
      "start_time": "8:30am",
      "summary": "Team Meeting"
    }
    
    Option 3 - Delete by date and time only:
    {
      "date": "07 Mar 2026",
      "start_time": "8:30am"
    }
    """
    try:
        body = await request.json()
        headers_dict = {name.lower(): value for name, value in request.headers.items()}
        
        class SimpleContext:
            def __init__(self, headers):
                self.headers = headers
                self.request_context = None
        
        ctx = SimpleContext(headers_dict)
        from google_calendar_mcp.tools.delete_event import delete_event as delete_event_impl
        result = delete_event_impl(ctx=ctx, **body)
        
        return JSONResponse({
            "success": True,
            "result": result
        })
        
    except Exception as e:
        logger.exception("Error in delete endpoint")
        return JSONResponse(
            {
                "success": False,
                "error": str(e),
                "error_type": type(e).__name__
            },
            status_code=500
        )


@mcp.custom_route("/check_availability", methods=["POST"])
async def check_availability_simple(request: StarletteRequest) -> JSONResponse:
    """
    Simplified endpoint for checking calendar availability.
    
    Accepts a simplified JSON format:
    {
      "date": "07 Mar 2026",
      "start_time": "8am",
      "end_time": "10am",  // optional, defaults to 1 hour after start_time
      "location": "New York"  // optional: timezone auto-detected from location
    }
    
    No need for JSON-RPC wrapper - just send the arguments directly.
    """
    try:
        body = await request.json()
        headers_dict = {name.lower(): value for name, value in request.headers.items()}
        
        class SimpleContext:
            def __init__(self, headers):
                self.headers = headers
                self.request_context = None
        
        ctx = SimpleContext(headers_dict)
        from google_calendar_mcp.tools.check_availability import check_availability as check_availability_impl
        result = check_availability_impl(ctx=ctx, **body)
        
        return JSONResponse({
            "success": True,
            "result": result
        })
        
    except Exception as e:
        logger.exception("Error in check_availability endpoint")
        return JSONResponse(
            {
                "success": False,
                "error": str(e),
                "error_type": type(e).__name__
            },
            status_code=500
        )


@mcp.custom_route("/list_calendars", methods=["POST"])
async def list_calendars_simple(request: StarletteRequest) -> JSONResponse:
    """
    Simplified endpoint for listing all available calendars.
    
    Accepts an empty JSON body or optional parameters:
    {
      "impersonate_user": "email@example.com"  // optional, for service accounts
    }
    
    No need for JSON-RPC wrapper - just send the arguments directly.
    """
    try:
        body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
        headers_dict = {name.lower(): value for name, value in request.headers.items()}
        
        class SimpleContext:
            def __init__(self, headers):
                self.headers = headers
                self.request_context = None
        
        ctx = SimpleContext(headers_dict)
        from google_calendar_mcp.tools.list_calendars import list_calendars as list_calendars_impl
        result = list_calendars_impl(ctx=ctx, **body)
        
        return JSONResponse({
            "success": True,
            "result": result
        })
        
    except Exception as e:
        logger.exception("Error in list_calendars endpoint")
        return JSONResponse(
            {
                "success": False,
                "error": str(e),
                "error_type": type(e).__name__
            },
            status_code=500
        )


@mcp.custom_route("/get_events", methods=["POST"])
async def get_events_simple(request: StarletteRequest) -> JSONResponse:
    """
    Simplified endpoint for getting calendar events.
    
    Accepts a simplified JSON format:
    {
      "calendar_id": "primary",  // optional, defaults to "primary"
      "max_results": 10,         // optional, defaults to 10
      "date": "07 Mar 2026",     // optional, natural language date (defaults to today)
      "location": "New York"     // optional: timezone auto-detected from location
    }
    
    No need for JSON-RPC wrapper - just send the arguments directly.
    """
    try:
        body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
        headers_dict = {name.lower(): value for name, value in request.headers.items()}
        
        class SimpleContext:
            def __init__(self, headers):
                self.headers = headers
                self.request_context = None
        
        ctx = SimpleContext(headers_dict)
        
        # If date is provided, convert to ISO format for time_min and time_max (entire day)
        if "date" in body:
            date_str = body.pop("date")
            location = body.pop("location", None)
            timezone = body.pop("timezone", None)
            
            # Determine timezone
            if timezone:
                target_timezone = timezone
            elif location:
                detected_timezone = get_timezone_from_location(location)
                target_timezone = detected_timezone or 'Asia/Kolkata'
            else:
                target_timezone = 'Asia/Kolkata'
            
            # Parse date and set time to start of day
            _, start_dt = parse_natural_datetime(date_str, "00:00", target_timezone)
            # Set time_max to end of the same day
            end_dt = start_dt.replace(hour=23, minute=59, second=59)
            body["time_min"] = start_dt.isoformat()
            body["time_max"] = end_dt.isoformat()
        
        from google_calendar_mcp.tools.get_events import get_events as get_events_impl
        result = get_events_impl(ctx=ctx, **body)
        
        return JSONResponse({
            "success": True,
            "result": result
        })
        
    except Exception as e:
        logger.exception("Error in get_events endpoint")
        return JSONResponse(
            {
                "success": False,
                "error": str(e),
                "error_type": type(e).__name__
            },
            status_code=500
        )


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@mcp.tool()
def list_calendars(
    impersonate_user: Optional[str] = None,
    ctx: Context = None
) -> str:
    """List all available calendars."""
    from google_calendar_mcp.tools.list_calendars import list_calendars as list_calendars_impl
    return list_calendars_impl(impersonate_user=impersonate_user, ctx=ctx)


@mcp.tool()
def get_events(
    calendar_id: str = DEFAULT_CALENDAR_ID,
    max_results: int = DEFAULT_MAX_RESULTS,
    time_min: Optional[str] = None,
    time_max: Optional[str] = None,
    impersonate_user: Optional[str] = None,
    ctx: Context = None
) -> str:
    """Get calendar events."""
    from google_calendar_mcp.tools.get_events import get_events as get_events_impl
    return get_events_impl(
        calendar_id=calendar_id,
        max_results=max_results,
        time_min=time_min,
        time_max=time_max,
        impersonate_user=impersonate_user,
        ctx=ctx
    )


@mcp.tool()
def create_event(
    summary: str,
    date: str,
    start_time: str,
    end_time: Optional[str] = None,
    description: Optional[str] = None,
    location: Optional[str] = None,
    attendees: Optional[str] = None,
    send_notifications: bool = True,
    add_google_meet: bool = True,
    reminders_minutes: Optional[int] = DEFAULT_REMINDERS_MINUTES,
    calendar_id: str = DEFAULT_CALENDAR_ID,
    timezone: Optional[str] = None,
    impersonate_user: Optional[str] = None,
    ctx: Context = None
) -> str:
    """Create a calendar event with natural language date/time input."""
    from google_calendar_mcp.tools.create_event import create_event as create_event_impl
    return create_event_impl(
        summary=summary,
        date=date,
        start_time=start_time,
        end_time=end_time,
        description=description,
        location=location,
        attendees=attendees,
        send_notifications=send_notifications,
        add_google_meet=add_google_meet,
        reminders_minutes=reminders_minutes,
        calendar_id=calendar_id,
        timezone=timezone,
        impersonate_user=impersonate_user,
        ctx=ctx
    )


@mcp.tool()
def check_availability(
    date: str,
    start_time: str,
    end_time: Optional[str] = None,
    location: Optional[str] = None,
    calendar_id: str = DEFAULT_CALENDAR_ID,
    timezone: Optional[str] = None,
    impersonate_user: Optional[str] = None,
    ctx: Context = None
) -> str:
    """Check calendar availability for a time range using natural language date/time."""
    from google_calendar_mcp.tools.check_availability import check_availability as check_availability_impl
    return check_availability_impl(
        date=date,
        start_time=start_time,
        end_time=end_time,
        location=location,
        calendar_id=calendar_id,
        timezone=timezone,
        impersonate_user=impersonate_user,
        ctx=ctx
    )


@mcp.tool()
def delete_event(
    event_id: Optional[str] = None,
    date: Optional[str] = None,
    start_time: Optional[str] = None,
    summary: Optional[str] = None,
    location: Optional[str] = None,
    calendar_id: str = DEFAULT_CALENDAR_ID,
    timezone: Optional[str] = None,
    impersonate_user: Optional[str] = None,
    ctx: Context = None
) -> str:
    """Delete a calendar event by event ID, or by date/time and event name."""
    from google_calendar_mcp.tools.delete_event import delete_event as delete_event_impl
    return delete_event_impl(
        event_id=event_id,
        date=date,
        start_time=start_time,
        summary=summary,
        location=location,
        calendar_id=calendar_id,
        timezone=timezone,
        impersonate_user=impersonate_user,
        ctx=ctx
    )

# ---------------------------------------------------------------------------
# Main Entry Point
# ---------------------------------------------------------------------------

async def main() -> None:
    """Main entry point for the Google Calendar MCP Server."""
    port = int(os.getenv("PORT", 7860))
    host = os.getenv("HOST", "0.0.0.0")
    
    mcp.settings.host = host
    mcp.settings.port = port
    mcp.settings.log_level = "INFO"
    
    logger.info(
        f"Google Calendar MCP Server starting on http://{host}:{port}\n"
        "Streamable HTTP and discovery at /google-calendar/mcp"
    )
    
    await mcp.run_streamable_http_async()
