"""
Create event tool for Google Calendar MCP Server.
"""

import logging
from datetime import datetime, timedelta
from typing import Optional

from mcp.server.fastmcp import Context

from google_calendar_mcp.auth import get_calendar_service
from google_calendar_mcp.config import (
    DEFAULT_CALENDAR_ID,
    DEFAULT_REMINDERS_MINUTES,
    get_google_calendar_credentials,
)
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
    """
    Create a calendar event with natural language date/time input.
    
    IMPORTANT: The organizer email (who creates the event) is AUTOMATICALLY determined
    from the access token - you do NOT need to provide it. Only provide attendee emails.
    
    When attendees are added and send_notifications is True, attendees will receive
    email notifications in Gmail showing "You have a meeting at [time]".
    
    Credentials are automatically retrieved from HTTP headers.
    No need to pass credentials as a parameter.
    
    Args:
        summary: Event title
        date: Date in natural language (e.g., '05 Mar 2026', 'March 5, 2026', '2026-03-05')
        start_time: Start time in natural language (e.g., '8am', '9:00 AM', '14:00', '2:30 PM')
        end_time: End time in natural language (optional, defaults to 1 hour after start)
        description: Event description (optional)
        location: Event location (optional). If provided and timezone is not specified, 
                  timezone will be automatically determined from location (e.g., "New York" -> "America/New_York")
        attendees: Comma-separated email addresses of people to invite
        send_notifications: Send email notifications to attendees (default: True)
        add_google_meet: Add Google Meet video conference link (default: True)
        reminders_minutes: Minutes before event to send reminder (default: 15, set None to disable)
        calendar_id: Calendar ID (default: 'primary')
        timezone: Timezone (e.g., 'America/New_York', 'UTC', 'Asia/Kolkata'). Defaults to Asia/Kolkata (IST).
        impersonate_user: Optional email for service account domain-wide delegation.
    
    Returns:
        String confirming event creation with event ID and Google Meet link if added.
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
        
        # Parse date and start_time
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
        
        # Log the event data being sent to Google Calendar
        logger.info(
            f"EVENT CREATION: start={start_datetime_str}, end={end_datetime_str}, "
            f"timeZone={target_timezone}, date={date}, start_time={start_time}, end_time={end_time or 'default 1h'}"
        )
        
        event = {
            'summary': summary,
            'start': {
                'dateTime': start_datetime_str,
                'timeZone': target_timezone,
            },
            'end': {
                'dateTime': end_datetime_str,
                'timeZone': target_timezone,
            },
        }
        
        if description:
            event['description'] = description
        if location:
            event['location'] = location
        
        # Add attendees if provided
        if attendees:
            attendee_list = [email.strip() for email in attendees.split(',')]
            event['attendees'] = [{'email': email} for email in attendee_list if email]
        
        # Add Google Meet video conference
        if add_google_meet:
            event['conferenceData'] = {
                'createRequest': {
                    'requestId': f"meet-{datetime.utcnow().timestamp()}",
                    'conferenceSolutionKey': {
                        'type': 'hangoutsMeet'
                    }
                }
            }
        
        # Add reminders
        if reminders_minutes is not None:
            event['reminders'] = {
                'useDefault': False,
                'overrides': [
                    {'method': 'email', 'minutes': reminders_minutes},
                    {'method': 'popup', 'minutes': reminders_minutes}
                ]
            }
        
        # Determine sendUpdates parameter
        send_updates = 'all' if send_notifications else 'none'
        
        # Create the event (will fail with clear error if calendar is not accessible)
        created_event = service.events().insert(
            calendarId=calendar_id,
            body=event,
            sendUpdates=send_updates,
            conferenceDataVersion=1 if add_google_meet else 0
        ).execute()
        
        result = f"Event created: {created_event.get('summary')} (ID: {created_event.get('id')})"
        
        # Add Google Meet link if created
        if add_google_meet:
            conference_data = created_event.get('conferenceData', {})
            if 'hangoutLink' in conference_data:
                result += f"\nGoogle Meet link: {conference_data['hangoutLink']}"
        
        # Confirm notifications sent
        if send_notifications and attendees:
            attendee_count = len(event.get('attendees', []))
            result += f"\nEmail notifications sent to {attendee_count} attendee(s)"
        
        return result
        
    except Exception as e:
        logger.exception("Error creating event")
        return f"Error creating event: {format_calendar_error(e)}"
