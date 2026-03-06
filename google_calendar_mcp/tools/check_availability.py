"""
Check availability tool for Google Calendar MCP Server.
"""

import logging
from datetime import datetime, timedelta
from typing import Optional

from dateutil.tz import gettz
from mcp.server.fastmcp import Context

from google_calendar_mcp.auth import get_calendar_service
from google_calendar_mcp.config import DEFAULT_CALENDAR_ID, get_google_calendar_credentials
from google_calendar_mcp.utils import (
    format_calendar_error,
    get_timezone_from_location,
    parse_natural_datetime,
)

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
    """
    Check calendar availability for a time range using natural language date/time.
    
    Credentials are automatically retrieved from HTTP headers.
    No need to pass credentials as a parameter.
    
    Args:
        date: Date in natural language (e.g., '07 Mar 2026', 'March 7, 2026', '2026-03-07')
        start_time: Start time in natural language (e.g., '8am', '9:00 AM', '14:00', '2:30 PM')
        end_time: End time in natural language (optional, defaults to 1 hour after start_time)
        location: Location name (optional). If provided and timezone is not specified, 
                  timezone will be automatically determined from location (e.g., "New York" -> "America/New_York")
        calendar_id: Calendar ID (default: 'primary')
        timezone: Timezone (e.g., 'America/New_York', 'UTC', 'Asia/Kolkata'). 
                  If not provided, will be auto-detected from location, or defaults to Asia/Kolkata (IST).
        impersonate_user: Optional email for service account domain-wide delegation.
    
    Returns:
        String indicating availability or listing busy periods.
    """
    try:
        headers = _extract_headers_from_context(ctx)
        credentials = get_google_calendar_credentials(headers)
        service = get_calendar_service(credentials, impersonate_user)
        
        # Determine timezone: use provided timezone, or detect from location, or default to IST
        if timezone:
            target_timezone = timezone
            logger.debug(f"Using provided timezone: {target_timezone}")
        elif location:
            # Try to detect timezone from location
            detected_timezone = get_timezone_from_location(location)
            if detected_timezone:
                target_timezone = detected_timezone
                logger.info(f"Auto-detected timezone from location '{location}': {target_timezone}")
            else:
                target_timezone = 'Asia/Kolkata'
                logger.warning(f"Could not detect timezone from location '{location}', using default: {target_timezone}")
        else:
            target_timezone = 'Asia/Kolkata'
            logger.debug(f"Using default timezone: {target_timezone} (IST)")
        
        # Parse natural language date and start_time
        start_datetime_str, start_dt = parse_natural_datetime(date, start_time, target_timezone)
        
        # Parse end_time or calculate it
        if end_time:
            end_datetime_str, end_dt = parse_natural_datetime(date, end_time, target_timezone)
        else:
            # Default to 1 hour after start
            end_dt = start_dt + timedelta(hours=1)
            end_datetime_str = end_dt.strftime('%Y-%m-%dT%H:%M:%S')
        
        # Validate that end time is after start time
        if end_dt <= start_dt:
            raise ValueError(
                f"End time must be after start time. "
                f"Start: {start_datetime_str} ({start_time}), "
                f"End: {end_datetime_str} ({end_time or '1 hour after start'})"
            )
        
        # Format for Google Calendar API (RFC3339 format with timezone)
        time_min = start_dt.isoformat()
        time_max = end_dt.isoformat()
        
        logger.info(f"AVAILABILITY CHECK: Checking from {start_datetime_str} to {end_datetime_str} ({target_timezone})")
        
        # Get events in the time range
        events_result = service.events().list(
            calendarId=calendar_id,
            timeMin=time_min,
            timeMax=time_max,
            singleEvents=True,
            orderBy='startTime'
        ).execute()
        
        events = events_result.get('items', [])
        
        # Format the search time range in readable format (same as get_events)
        start_formatted = start_dt.strftime('%d %b %Y, %I:%M %p')
        end_formatted = end_dt.strftime('%d %b %Y, %I:%M %p')
        
        if not events:
            return f"Available from {start_formatted} to {end_formatted} ({target_timezone})"
        
        result = [f"Busy periods from {start_formatted} to {end_formatted} ({target_timezone}):"]
        for event in events:
            event_start = event['start'].get('dateTime', event['start'].get('date'))
            event_end = event['end'].get('dateTime', event['end'].get('date'))
            summary = event.get('summary', 'No Title')
            
            # Format times using the same format as get_events (readable format)
            try:
                if 'T' in event_start:
                    # Parse datetime
                    if event_start.endswith('Z'):
                        start_dt_parsed = datetime.fromisoformat(event_start.replace('Z', '+00:00'))
                    else:
                        start_dt_parsed = datetime.fromisoformat(event_start)
                    
                    # Convert to target timezone
                    tz_obj = gettz(target_timezone)
                    if tz_obj and start_dt_parsed.tzinfo:
                        start_dt_local = start_dt_parsed.astimezone(tz_obj)
                    elif tz_obj:
                        start_dt_local = start_dt_parsed.replace(tzinfo=gettz('UTC')).astimezone(tz_obj)
                    else:
                        start_dt_local = start_dt_parsed
                    
                    # Format as readable date/time (same as get_events)
                    event_start_formatted = start_dt_local.strftime('%d %b %Y, %I:%M %p')
                else:
                    # All-day event
                    event_start_formatted = event_start
                    
                if 'T' in event_end:
                    # Parse datetime
                    if event_end.endswith('Z'):
                        end_dt_parsed = datetime.fromisoformat(event_end.replace('Z', '+00:00'))
                    else:
                        end_dt_parsed = datetime.fromisoformat(event_end)
                    
                    # Convert to target timezone
                    tz_obj = gettz(target_timezone)
                    if tz_obj and end_dt_parsed.tzinfo:
                        end_dt_local = end_dt_parsed.astimezone(tz_obj)
                    elif tz_obj:
                        end_dt_local = end_dt_parsed.replace(tzinfo=gettz('UTC')).astimezone(tz_obj)
                    else:
                        end_dt_local = end_dt_parsed
                    
                    # Format as readable date/time (same as get_events)
                    event_end_formatted = end_dt_local.strftime('%d %b %Y, %I:%M %p')
                else:
                    # All-day event
                    event_end_formatted = event_end
            except Exception as e:
                logger.debug(f"Error formatting event time: {e}")
                event_start_formatted = event_start
                event_end_formatted = event_end
            
            result.append(f"  • {summary}: {event_start_formatted} to {event_end_formatted}")
        
        return "\n".join(result)
        
    except Exception as e:
        logger.exception("Error checking availability")
        return f"Error checking availability: {format_calendar_error(e)}"
