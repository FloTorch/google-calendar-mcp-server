"""
Delete event tool for Google Calendar MCP Server.
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
    """
    Delete a calendar event by event ID, or by date/time and event name.
    
    You can delete an event by:
    1. Providing event_id directly (recommended - most precise)
    2. Providing date + start_time + summary (event name) - natural language
    3. Providing date + start_time (if only one event at that time)
    
    Credentials are automatically retrieved from HTTP headers.
    No need to pass credentials as a parameter.
    
    Args:
        event_id: Direct event ID (recommended - if you know it)
        date: Date in natural language (e.g., '07 Mar 2026', 'March 7, 2026') - required if no event_id
        start_time: Start time in natural language (e.g., '8:30am', '9:00 AM', '8:30') - required if no event_id
        summary: Event title/name to match (optional, helps identify the exact event)
        location: Location name (optional). If provided and timezone is not specified, 
                  timezone will be automatically determined from location.
        calendar_id: Calendar ID (default: 'primary')
        timezone: Timezone (e.g., 'America/New_York', 'UTC', 'Asia/Kolkata'). Defaults to Asia/Kolkata (IST).
        impersonate_user: Optional email for service account domain-wide delegation.
    
    Returns:
        String confirming event deletion.
    """
    try:
        headers = _extract_headers_from_context(ctx)
        credentials = get_google_calendar_credentials(headers)
        service = get_calendar_service(credentials, impersonate_user)
        
        # If event_id is provided, delete directly
        if event_id:
            service.events().delete(
                calendarId=calendar_id,
                eventId=event_id
            ).execute()
            return f"Event {event_id} deleted successfully"
        
        # Otherwise, need date and start_time to search
        if not date or not start_time:
            raise ValueError(
                "Either provide 'event_id' OR both 'date' and 'start_time' to delete an event. "
                "Example: {\"date\": \"07 Mar 2026\", \"start_time\": \"8:30am\", \"summary\": \"Team Meeting\"}"
            )
        
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
        
        # Parse natural language date and time
        search_datetime_str, search_start_dt = parse_natural_datetime(date, start_time, target_timezone)
        
        # Search for the entire day (from start of day to end of day)
        # This ensures we find events even if there are timezone differences
        day_start = search_start_dt.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start + timedelta(days=1)
        
        # Format for Google Calendar API (RFC3339 format with timezone)
        time_min = day_start.isoformat()
        time_max = day_end.isoformat()
        
        logger.info(f"DELETE SEARCH: Looking for events between {time_min} and {time_max}, searching for {date} {start_time} (parsed as {search_start_dt})")
        
        events_result = service.events().list(
            calendarId=calendar_id,
            timeMin=time_min,
            timeMax=time_max,
            singleEvents=True,
            orderBy='startTime'
        ).execute()
        
        events = events_result.get('items', [])
        
        logger.info(f"DELETE SEARCH: Found {len(events)} total events on {date}")
        
        if not events:
            return f"No events found on {date}. Please check the date and try again."
        
        # Filter events by start_time and optionally summary
        matching_events = []
        
        # Convert search time to UTC for comparison (Google Calendar API returns times in UTC)
        search_start_utc = search_start_dt.astimezone(gettz('UTC'))
        logger.info(f"DELETE SEARCH: Looking for events at {search_start_dt} ({target_timezone}) = {search_start_utc} (UTC)")
        
        for event in events:
            event_start = event['start'].get('dateTime', event['start'].get('date'))
            event_summary = event.get('summary', 'No Title')
            event_timezone = event['start'].get('timeZone')
            
            # If timezone not in event['start'], try to detect from datetime string
            if not event_timezone and 'T' in event_start:
                # Check if datetime string has timezone offset (e.g., +05:30, -05:00, Z)
                if event_start.endswith('Z'):
                    event_timezone = 'UTC'
                elif '+' in event_start[-6:] or (event_start.count('-') > 2 and 'T' in event_start):
                    # Has timezone offset, try to infer timezone from offset
                    # For IST (+05:30), we'll use Asia/Kolkata
                    if '+05:30' in event_start or '+0530' in event_start:
                        event_timezone = 'Asia/Kolkata'
                    elif '+00:00' in event_start or event_start.endswith('Z'):
                        event_timezone = 'UTC'
                    # For other offsets, we'll still try to match using UTC comparison
            
            logger.info(f"DELETE CHECK: Event '{event_summary}' at {event_start} (timezone: {event_timezone or 'detected from string'})")
            
            # Handle both dateTime and date formats
            if 'T' in event_start:
                # Parse the event start time (Google Calendar API returns in UTC with Z)
                try:
                    # Parse with timezone info - keep the original timezone for comparison
                    if event_start.endswith('Z'):
                        event_start_dt_utc = datetime.fromisoformat(event_start.replace('Z', '+00:00'))
                        event_start_dt_original = event_start_dt_utc
                    elif '+' in event_start or (event_start.count('-') > 2 and 'T' in event_start):
                        # Has timezone offset - parse and keep original timezone
                        event_start_dt_original = datetime.fromisoformat(event_start)
                        # Convert to UTC for API consistency
                        if event_start_dt_original.tzinfo:
                            event_start_dt_utc = event_start_dt_original.astimezone(gettz('UTC'))
                        else:
                            # No timezone info, assume UTC
                            event_start_dt_utc = event_start_dt_original.replace(tzinfo=gettz('UTC'))
                            event_start_dt_original = event_start_dt_utc
                    else:
                        # No timezone suffix, but has T - assume UTC (Google Calendar API format)
                        event_start_dt_original = datetime.fromisoformat(event_start).replace(tzinfo=gettz('UTC'))
                        event_start_dt_utc = event_start_dt_original
                except ValueError as e:
                    logger.warning(f"Error parsing event time {event_start}: {e}")
                    continue
            else:
                # All-day event, skip for now
                logger.debug(f"Skipping all-day event: {event_summary}")
                continue
            
            # PRIMARY MATCHING: Direct hour:minute comparison from datetime string
            # This is the most reliable method - extract hour:minute directly and compare
            time_matched = False
            if 'T' in event_start:
                try:
                    # Extract hour:minute from event string (format: YYYY-MM-DDTHH:MM:SS+offset)
                    time_part = event_start.split('T')[1]
                    # Remove timezone offset and seconds
                    for sep in ['+', '-', 'Z']:
                        if sep in time_part:
                            time_part = time_part.split(sep)[0]
                    event_hour_min = time_part[:5]  # Get HH:MM
                    search_hour_min = f"{search_start_dt.hour:02d}:{search_start_dt.minute:02d}"
                    
                    # Parse and compare
                    event_hm_parts = event_hour_min.split(':')
                    search_hm_parts = search_hour_min.split(':')
                    if len(event_hm_parts) == 2 and len(search_hm_parts) == 2:
                        event_hm_minutes = int(event_hm_parts[0]) * 60 + int(event_hm_parts[1])
                        search_hm_minutes = int(search_hm_parts[0]) * 60 + int(search_hm_parts[1])
                        hm_diff = abs(event_hm_minutes - search_hm_minutes)
                        
                        # Check same day
                        event_date_str = event_start.split('T')[0]
                        search_date_str = search_start_dt.strftime('%Y-%m-%d')
                        same_day_direct = (event_date_str == search_date_str)
                        
                        logger.info(f"DELETE DIRECT CHECK: Event '{event_summary}' hour:min={event_hour_min}, Search hour:min={search_hour_min}, diff={hm_diff} min, same_day={same_day_direct}")
                        
                        # Match if same day and within 30 minutes
                        if hm_diff <= 30 and same_day_direct:
                            time_matched = True
                            logger.info(f"DELETE TIME MATCHED (direct): Event '{event_summary}' matches time criteria")
                except Exception as e:
                    logger.debug(f"Direct hour:minute comparison failed: {e}")
            
            # CRITICAL: Compare in the event's timezone context
            # If event has a timezone, interpret the UTC time in that timezone and compare with search time
            # Only do timezone comparison if direct comparison didn't already match
            if not time_matched and event_timezone:
                # Event has timezone - interpret UTC time as local time in event's timezone
                event_tz = gettz(event_timezone)
                if event_tz:
                    # Use the original datetime if it has timezone, otherwise convert from UTC
                    if event_start_dt_original.tzinfo:
                        event_start_dt_local = event_start_dt_original
                    else:
                        event_start_dt_local = event_start_dt_utc.astimezone(event_tz)
                    
                    # Compare with search time (both in their respective timezones, but same wall-clock time)
                    search_start_dt_local = search_start_dt  # Already in target_timezone
                    
                    # Compare hour and minute (wall-clock time comparison)
                    event_minutes = event_start_dt_local.hour * 60 + event_start_dt_local.minute
                    search_minutes = search_start_dt_local.hour * 60 + search_start_dt_local.minute
                    time_diff_minutes = abs(event_minutes - search_minutes)
                    
                    # Also check if same day
                    same_day = (event_start_dt_local.date() == search_start_dt_local.date())
                    
                    logger.info(f"DELETE TIME CHECK: Event local={event_start_dt_local} ({event_timezone}) vs Search local={search_start_dt_local} ({target_timezone}), wall-clock diff={time_diff_minutes} min, same_day={same_day}")
                    
                    # Match if same day and within 30 minutes
                    if same_day and time_diff_minutes <= 30:
                        time_matched = True
                        logger.info(f"DELETE TIME MATCHED (timezone): Event '{event_summary}' matches time criteria")
                    else:
                        continue
                else:
                    # Invalid timezone, fall back to UTC comparison
                    time_diff = abs((event_start_dt_utc - search_start_utc).total_seconds())
                    logger.info(f"DELETE TIME CHECK: Invalid timezone '{event_timezone}', using UTC comparison: diff={time_diff} seconds")
                    if time_diff <= 1800:
                        time_matched = True
                        logger.info(f"DELETE TIME MATCHED (UTC fallback): Event '{event_summary}' matches time criteria")
                    else:
                        continue
            elif not time_matched:
                # No timezone in event - compare in UTC (assume event was created in UTC)
                # But also try comparing as if it was in the target timezone
                time_diff_utc = abs((event_start_dt_utc - search_start_utc).total_seconds())
                
                # Try interpreting UTC time as if it was in target timezone
                event_as_local = event_start_dt_utc.replace(tzinfo=None)  # Remove UTC, treat as naive
                event_in_target_tz = gettz(target_timezone).localize(event_as_local) if gettz(target_timezone) else None
                
                if event_in_target_tz:
                    time_diff_local = abs((event_in_target_tz - search_start_dt).total_seconds())
                    logger.info(f"DELETE TIME CHECK: Event UTC={event_start_dt_utc}, trying as {target_timezone}={event_in_target_tz} vs Search={search_start_dt}, UTC diff={time_diff_utc/60:.1f} min, Local diff={time_diff_local/60:.1f} min")
                    # Use the smaller difference (more flexible matching)
                    time_diff = min(time_diff_utc, time_diff_local)
                else:
                    time_diff = time_diff_utc
                    logger.info(f"DELETE TIME CHECK: Event UTC={event_start_dt_utc} vs Search UTC={search_start_utc}, diff={time_diff} seconds")
                
                if time_diff <= 1800:  # Within 30 minutes
                    time_matched = True
                    logger.info(f"DELETE TIME MATCHED (UTC): Event '{event_summary}' matches time criteria")
                else:
                    continue
            
            # If time didn't match (neither direct nor timezone comparison), skip this event
            if not time_matched:
                continue
            
            # If summary provided, check if it matches
            if summary:
                if summary.lower() not in event_summary.lower():
                    logger.info(f"DELETE SUMMARY CHECK: '{summary}' not in '{event_summary}'")
                    continue
            
            # Event matches all criteria - add it
            matching_events.append(event)
            logger.info(f"DELETE MATCH: Found matching event '{event_summary}' at {event_start}")
        
        if not matching_events:
            criteria = f"on {date} at {start_time}"
            if summary:
                criteria += f" with title '{summary}'"
            # List all events found for debugging
            if events:
                event_list = "\n".join([
                    f"- {e.get('summary', 'No Title')} at {e['start'].get('dateTime', e['start'].get('date'))}"
                    for e in events[:5]  # Show first 5 events
                ])
                return f"No events found {criteria}. Found {len(events)} events on {date}:\n{event_list}\n\nPlease check the time and summary."
            return f"No events found {criteria}. Please check the details and try again."
        
        # Delete all matching events (if multiple events have same name and time, delete all)
        deleted_count = 0
        deleted_titles = []
        
        for event_to_delete in matching_events:
            event_id_to_delete = event_to_delete.get('id')
            event_title = event_to_delete.get('summary', 'Untitled Event')
            event_start_time = event_to_delete['start'].get('dateTime', event_to_delete['start'].get('date'))
            
            try:
                service.events().delete(
                    calendarId=calendar_id,
                    eventId=event_id_to_delete
                ).execute()
                deleted_count += 1
                deleted_titles.append(f"'{event_title}' ({event_start_time})")
                logger.info(f"Deleted event: {event_title} ({event_id_to_delete})")
            except Exception as delete_error:
                logger.error(f"Failed to delete event {event_id_to_delete}: {delete_error}")
                # Continue deleting other events even if one fails
        
        if deleted_count == 0:
            return f"Failed to delete any events. Please check your permissions and try again."
        elif deleted_count == 1:
            return f"Event {deleted_titles[0]} deleted successfully"
        else:
            events_list = "\n".join([f"  • {title}" for title in deleted_titles])
            return f"Successfully deleted {deleted_count} events:\n{events_list}"
        
    except Exception as e:
        logger.exception("Error deleting event")
        return f"Error deleting event: {format_calendar_error(e)}"
