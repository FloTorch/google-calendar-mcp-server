#!/usr/bin/env python3
"""
Google Calendar MCP Server using FastMCP
Run this locally to create an MCP server for Google Calendar

This server accepts Google Calendar credentials as a parameter for each tool call,
allowing multiple users to access their own calendars dynamically.
"""

import json
import os
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional

from mcp.server.fastmcp import FastMCP, Context
from google.oauth2.credentials import Credentials
from google.oauth2 import service_account
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

logging.basicConfig(format="[%(levelname)s]: %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuration
SCOPES = ['https://www.googleapis.com/auth/calendar']

# Create FastMCP server
mcp = FastMCP(
    "Google Calendar MCP",
    instructions="A Google Calendar MCP server that provides tools to view, create, update, and manage calendar events. Credentials are automatically retrieved from environment variables or request context - no need to pass credentials as parameters.",
    json_response=True
)

def get_credentials_from_header(ctx: Context = None) -> str:
    """
    Extract Google Calendar credentials from HTTP headers only.
    Supports two formats:
    1. JSON string: '{"access_token":"ya29..."}'
    2. Plain access token: 'ya29...'
    
    Raises ValueError if credentials are not found in headers.
    """
    if not ctx:
        raise ValueError("Context is required to extract credentials from headers")
    
    try:
        # Access the Starlette Request object from request context
        request_context = ctx.request_context
        if not hasattr(request_context, 'request') or not request_context.request:
            raise ValueError("Request context not available")
        
        # For streamable HTTP, request is a Starlette Request object
        request = request_context.request
        
        # Access headers from Starlette Request object
        # request.headers is a Headers object (case-insensitive dict-like)
        header_dict = {}
        for name in request.headers.keys():
            header_dict[name.lower()] = request.headers[name]
        
        # Check for Google Calendar credentials header
        # Try common header names
        creds_header = (
            header_dict.get('x-google-calendar-credentials') or
            header_dict.get('google-calendar-credentials') or
            header_dict.get('authorization')
        )
        
        if not creds_header:
            raise ValueError(
                "Google Calendar credentials not found in HTTP headers. "
                "Expected header: 'X-Google-Calendar-Credentials', 'Google-Calendar-Credentials', or 'Authorization'"
            )
        
        # Handle Bearer token format
        if creds_header.startswith('Bearer '):
            token = creds_header.replace('Bearer ', '').strip()
            # Convert to JSON string format
            return json.dumps({"access_token": token})
        
        # Check if it's already a JSON string
        try:
            # Try to parse as JSON to validate
            json.loads(creds_header)
            # If it parses successfully, return as-is
            return creds_header
        except json.JSONDecodeError:
            # If not JSON, treat as plain token and convert to JSON
            token = creds_header.strip()
            if token.startswith(('ya29.', '1//', 'ya.a0')):
                return json.dumps({"access_token": token})
            # Return as-is if we can't determine format (get_calendar_service will validate)
            return creds_header
    except ValueError:
        # Re-raise ValueError (our own errors)
        raise
    except Exception as e:
        logger.error(f"Error extracting credentials from headers: {e}")
        raise ValueError(f"Failed to extract credentials from headers: {str(e)}")


def get_calendar_service(google_calendar_credentials: str, impersonate_user: Optional[str] = None):
    """
    Get authenticated Google Calendar service from user-provided credentials.
    
    Args:
        google_calendar_credentials: Can be:
            - Simple access token string: "ya29.a0AfH6SMB..."
            - Simple JSON with access_token: {"access_token": "ya29.a0AfH6SMB..."}
            - OAuth Token JSON: {"access_token":"...","refresh_token":"...","client_id":"...","client_secret":"..."}
            - Service Account JSON: {"type":"service_account","project_id":"...","private_key":"...","client_email":"..."}
        impersonate_user: Optional email for service account domain-wide delegation
    
    Returns:
        Authenticated Google Calendar service object
    """
    creds_data = None
    
    # Try to parse as JSON first
    try:
        creds_data = json.loads(google_calendar_credentials)
    except json.JSONDecodeError:
        # If not JSON, treat as simple access token string
        # Check if it looks like a token (starts with common OAuth token prefixes)
        if google_calendar_credentials.strip().startswith(('ya29.', '1//', 'ya.a0')):
            creds_data = {"access_token": google_calendar_credentials.strip()}
        else:
            raise ValueError(
                "Invalid credentials format. Must be:\n"
                "1. Simple access token string: 'ya29.a0AfH6SMB...'\n"
                "2. JSON with access_token: {\"access_token\":\"...\"}\n"
                "3. Full OAuth JSON: {\"access_token\":\"...\",\"refresh_token\":\"...\",\"client_id\":\"...\",\"client_secret\":\"...\"}\n"
                "4. Service Account JSON: {\"type\":\"service_account\",...}"
            )
    
    creds = None
    
    # Method 1: Service Account (check for service account type)
    if creds_data.get('type') == 'service_account':
        try:
            creds = service_account.Credentials.from_service_account_info(
                creds_data, scopes=SCOPES
            )
            
            # If impersonating a user (for domain-wide delegation)
            if impersonate_user:
                creds = creds.with_subject(impersonate_user)
            
            return build('calendar', 'v3', credentials=creds)
        except Exception as e:
            raise ValueError(f"Service Account authentication failed: {e}")
    
    # Method 2: OAuth Token (check for OAuth token fields)
    elif 'token' in creds_data or 'access_token' in creds_data:
        try:
            # Handle both 'token' and 'access_token' field names
            token = creds_data.get('token') or creds_data.get('access_token')
            refresh_token = creds_data.get('refresh_token')
            token_uri = creds_data.get('token_uri', 'https://oauth2.googleapis.com/token')
            client_id = creds_data.get('client_id')
            client_secret = creds_data.get('client_secret')
            
            if not token:
                raise ValueError("OAuth token must contain 'token' or 'access_token' field")
            
            # Check if we have all required fields for automatic refresh
            has_refresh_capability = refresh_token and client_id and client_secret
            
            if not has_refresh_capability:
                # Mode 1: Simple access token only - works for ~1 hour
                # No automatic refresh, user needs to provide new token after expiry
                creds = Credentials(
                    token=token,
                    scopes=SCOPES
                )
            else:
                # Mode 2: Full OAuth credentials with automatic refresh capability
                # Will automatically refresh when expired - long-term access
                creds = Credentials(
                    token=token,
                    refresh_token=refresh_token,
                    token_uri=token_uri,
                    client_id=client_id,
                    client_secret=client_secret,
                    scopes=SCOPES
                )
                
                # Automatically refresh if expired (before making API calls)
                if creds.expired:
                    try:
                        creds.refresh(Request())
                    except Exception as refresh_error:
                        raise ValueError(
                            f"Failed to refresh expired token: {refresh_error}. "
                            "Please provide a new access token or check your refresh_token, client_id, and client_secret."
                        )
            
            # Build service - Google API client will use credentials
            # Note: We refresh before building, but the client library may need
            # credentials to be refreshed again if they expire during long operations
            service = build('calendar', 'v3', credentials=creds)
            
            # Return service with credentials attached for potential future refresh
            # The credentials object will be used by the API client
            return service
        except Exception as e:
            raise ValueError(f"OAuth token authentication failed: {e}")
    
    else:
        raise ValueError(
            "Invalid credentials format. Must be:\n"
            "1. Simple access token string: 'ya29.a0AfH6SMB...'\n"
            "2. JSON with access_token: {\"access_token\":\"...\"}\n"
            "3. Full OAuth JSON: {\"access_token\":\"...\",\"refresh_token\":\"...\",\"client_id\":\"...\",\"client_secret\":\"...\"}\n"
            "4. Service Account JSON: {\"type\":\"service_account\",...}"
        )


@mcp.tool()
def list_calendars(
    impersonate_user: Optional[str] = None,
    ctx: Context = None
) -> str:
    """List all available calendars.
    
    Credentials are automatically retrieved from HTTP headers.
    No need to pass credentials as a parameter.
    
    Args:
        impersonate_user: Optional email for service account domain-wide delegation.
    
    Returns:
        String listing all available calendars with their IDs.
    """
    try:
        google_calendar_credentials = get_credentials_from_header(ctx)
        service = get_calendar_service(google_calendar_credentials, impersonate_user)
        calendars = service.calendarList().list().execute()
        
        result = []
        for calendar in calendars.get('items', []):
            result.append(f"- {calendar['summary']} (ID: {calendar['id']})")
        
        return "\n".join(result) if result else "No calendars found."
    except Exception as e:
        return f"Error listing calendars: {str(e)}"


@mcp.tool()
def get_events(
    calendar_id: str = "primary",
    max_results: int = 10,
    time_min: Optional[str] = None,
    impersonate_user: Optional[str] = None,
    ctx: Context = None
) -> str:
    """Get calendar events. 
    
    Credentials are automatically retrieved from HTTP headers.
    No need to pass credentials as a parameter.
    
    Args:
        calendar_id: Calendar ID (default: 'primary')
        max_results: Maximum number of events to return (default: 10)
        time_min: Start time in ISO format (default: now)
        impersonate_user: Optional email for service account domain-wide delegation.
    
    Returns:
        String listing calendar events with their titles and start times.
    """
    try:
        google_calendar_credentials = get_credentials_from_header(ctx)
        service = get_calendar_service(google_calendar_credentials, impersonate_user)
        
        if not time_min:
            time_min = datetime.utcnow().isoformat() + 'Z'
        
        events_result = service.events().list(
            calendarId=calendar_id,
            timeMin=time_min,
            maxResults=max_results,
            singleEvents=True,
            orderBy='startTime'
        ).execute()
        
        events = events_result.get('items', [])
        
        if not events:
            return "No upcoming events found."
        
        result = []
        for event in events:
            start = event['start'].get('dateTime', event['start'].get('date'))
            summary = event.get('summary', 'No Title')
            event_id = event.get('id', 'N/A')
            result.append(f"- {summary} ({start}) [ID: {event_id}]")
        
        return "\n".join(result)
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        logger.error(f"Error getting events: {str(e)}\n{error_details}")
        return f"Error getting events: {str(e)}. Please check your credentials and try again."


@mcp.tool()
def create_event(
    summary: str,
    start_time: str,
    end_time: Optional[str] = None,
    description: Optional[str] = None,
    location: Optional[str] = None,
    attendees: Optional[str] = None,
    send_notifications: bool = True,
    add_google_meet: bool = False,
    reminders_minutes: Optional[int] = 15,
    calendar_id: str = "primary",
    impersonate_user: Optional[str] = None,
    ctx: Context = None
) -> str:
    """Create a calendar event with optional attendees, notifications, and reminders.
    
    IMPORTANT: The organizer email (who creates the event) is AUTOMATICALLY determined
    from the access token - you do NOT need to provide it. Only provide attendee emails.
    
    When attendees are added and send_notifications is True, attendees will receive
    email notifications in Gmail showing "You have a meeting at [time]".
    
    Credentials are automatically retrieved from environment variables or request headers.
    No need to pass credentials as a parameter.
    
    Args:
        summary: Event title
        start_time: Start time in ISO format (e.g., '2024-01-15T14:00:00')
        end_time: End time in ISO format (optional, defaults to 1 hour after start)
        description: Event description (optional)
        location: Event location (optional)
        attendees: Comma-separated email addresses of people to invite (e.g., 'user1@example.com,user2@example.com').
            The organizer email (from access token) is automatically set - you only need to provide attendee emails.
        send_notifications: Send email notifications to attendees (default: True)
        add_google_meet: Add Google Meet video conference link (default: False)
        reminders_minutes: Minutes before event to send reminder (default: 15, set None to disable)
        calendar_id: Calendar ID (default: 'primary')
        impersonate_user: Optional email for service account domain-wide delegation.
    
    Returns:
        String confirming event creation with event ID and Google Meet link if added.
    """
    try:
        # Get credentials from HTTP headers only
        google_calendar_credentials = get_credentials_from_header(ctx)
        service = get_calendar_service(google_calendar_credentials, impersonate_user)
        
        # Parse and format times
        if not end_time:
            start_dt = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
            end_dt = start_dt + timedelta(hours=1)
            end_time = end_dt.isoformat()
        
        event = {
            'summary': summary,
            'start': {
                'dateTime': start_time,
                'timeZone': 'UTC',
            },
            'end': {
                'dateTime': end_time,
                'timeZone': 'UTC',
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
        
        created_event = service.events().insert(
            calendarId=calendar_id,
            body=event,
            sendUpdates=send_updates,
            conferenceDataVersion=1 if add_google_meet else 0
        ).execute()
        
        result = f"Event created: {created_event.get('summary')} (ID: {created_event.get('id')})"
        
        # Add Google Meet link if created
        if add_google_meet and 'hangoutLink' in created_event.get('conferenceData', {}):
            meet_link = created_event['conferenceData']['hangoutLink']
            result += f"\nGoogle Meet link: {meet_link}"
        
        # Confirm notifications sent
        if send_notifications and attendees:
            attendee_count = len(event.get('attendees', []))
            result += f"\nEmail notifications sent to {attendee_count} attendee(s)"
        
        return result
    except Exception as e:
        return f"Error creating event: {str(e)}"


@mcp.tool()
def check_availability(
    time_min: str,
    time_max: str,
    calendar_id: str = "primary",
    impersonate_user: Optional[str] = None,
    ctx: Context = None
) -> str:
    """Check calendar availability for a time range.
    
    Credentials are automatically retrieved from HTTP headers.
    No need to pass credentials as a parameter.
    
    Args:
        time_min: Start time in ISO format
        time_max: End time in ISO format
        calendar_id: Calendar ID (default: 'primary')
        impersonate_user: Optional email for service account domain-wide delegation.
    
    Returns:
        String indicating availability or listing busy periods.
    """
    try:
        google_calendar_credentials = get_credentials_from_header(ctx)
        service = get_calendar_service(google_calendar_credentials, impersonate_user)
        
        # Get events in the time range
        events_result = service.events().list(
            calendarId=calendar_id,
            timeMin=time_min,
            timeMax=time_max,
            singleEvents=True,
            orderBy='startTime'
        ).execute()
        
        events = events_result.get('items', [])
        
        if not events:
            return f"Available from {time_min} to {time_max}"
        else:
            result = [f"Busy periods from {time_min} to {time_max}:"]
            for event in events:
                start = event['start'].get('dateTime', event['start'].get('date'))
                end = event['end'].get('dateTime', event['end'].get('date'))
                summary = event.get('summary', 'No Title')
                result.append(f"- {summary}: {start} to {end}")
            return "\n".join(result)
    except Exception as e:
        return f"Error checking availability: {str(e)}"


@mcp.tool()
def delete_event(
    event_id: str,
    calendar_id: str = "primary",
    impersonate_user: Optional[str] = None,
    ctx: Context = None
) -> str:
    """Delete a calendar event.
    
    Credentials are automatically retrieved from HTTP headers.
    No need to pass credentials as a parameter.
    
    Args:
        event_id: Event ID to delete
        calendar_id: Calendar ID (default: 'primary')
        impersonate_user: Optional email for service account domain-wide delegation.
    
    Returns:
        String confirming event deletion.
    """
    try:
        google_calendar_credentials = get_credentials_from_header(ctx)
        service = get_calendar_service(google_calendar_credentials, impersonate_user)
        service.events().delete(
            calendarId=calendar_id,
            eventId=event_id
        ).execute()
        return f"Event {event_id} deleted successfully"
    except Exception as e:
        return f"Error deleting event: {str(e)}"


async def main():
    port = int(os.getenv("PORT", 8000))
    host = "0.0.0.0"
    
    # Update server settings for host and port
    mcp.settings.host = host
    mcp.settings.port = port
    mcp.settings.log_level = "INFO"
    
    # Run with streamable HTTP transport (async)
    await mcp.run_streamable_http_async()


if __name__ == "__main__":
    asyncio.run(main())
