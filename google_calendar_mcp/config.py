"""
Configuration for the Google Calendar MCP Server.

Provides credential resolution, constants, and configuration settings.
"""

import json
import os
from typing import Optional

# Google Calendar API scopes
SCOPES = ['https://www.googleapis.com/auth/calendar']

# Default values
DEFAULT_CALENDAR_ID = "primary"
DEFAULT_MAX_RESULTS = 10
DEFAULT_REMINDERS_MINUTES = 15


def get_google_calendar_credentials(headers: Optional[dict] = None) -> str:
    """
    Extract Google Calendar credentials from headers or environment.
    
    Supports two formats:
    
    Format 1: Separate headers (recommended)
    - X-Google-Calendar-Credentials: access_token value
    - X-Google-Calendar-Refresh-Token: refresh_token value (optional)
    - X-Google-Calendar-Client-Id: client_id value (optional)
    - X-Google-Calendar-Client-Secret: client_secret value (optional)
    
    Format 2: Single JSON header (backward compatible)
    - X-Google-Calendar-Credentials: '{"access_token":"ya29...","refresh_token":"...","client_id":"...","client_secret":"..."}'
    - Or: Authorization: 'Bearer ya29...'
    
    Priority:
    1. HTTP headers (separate headers or single JSON header)
    2. Environment variables (GOOGLE_CALENDAR_CREDENTIALS) - FALLBACK ONLY
    
    Args:
        headers: Dictionary of HTTP headers (lowercase keys)
        
    Returns:
        JSON string containing credentials
        
    Raises:
        ValueError: If credentials are not found in headers or environment
    """
    if not headers:
        headers = {}
    
    # Format 1: Check for separate headers
    access_token = (
        headers.get("x-google-calendar-credentials")
        or headers.get("google-calendar-credentials")
    )
    refresh_token = headers.get("x-google-calendar-refresh-token")
    client_id = headers.get("x-google-calendar-client-id")
    client_secret = headers.get("x-google-calendar-client-secret")
    
    # If we have access_token from separate header, build JSON from separate headers
    if access_token:
        creds_dict = {"access_token": access_token.strip()}
        
        if refresh_token:
            creds_dict["refresh_token"] = refresh_token.strip()
        if client_id:
            creds_dict["client_id"] = client_id.strip()
        if client_secret:
            creds_dict["client_secret"] = client_secret.strip()
        
        return json.dumps(creds_dict)
    
    # Format 2: Check for single JSON header or Authorization header
    # IMPORTANT: Check x-google-calendar-credentials first (could be JSON string)
    creds_value = (
        headers.get("x-google-calendar-credentials")
        or headers.get("google-calendar-credentials")
        or headers.get("authorization", "")
    ).strip()
    
    # Only fall back to environment variable if headers don't have credentials
    if not creds_value:
        creds_value = os.getenv("GOOGLE_CALENDAR_CREDENTIALS", "").strip()
    
    if not creds_value:
        raise ValueError(
            "Google Calendar credentials not found. "
            "Set X-Google-Calendar-Credentials header (with access_token) or GOOGLE_CALENDAR_CREDENTIALS env variable."
        )
    
    # Handle Bearer token format
    if creds_value.startswith('Bearer '):
        token = creds_value.replace('Bearer ', '').strip()
        return json.dumps({"access_token": token})
    
    # Check if it's already a JSON string
    try:
        json.loads(creds_value)
        return creds_value
    except json.JSONDecodeError:
        # If not JSON, treat as plain token and convert to JSON
        token = creds_value.strip()
        if token.startswith(('ya29.', '1//', 'ya.a0')):
            return json.dumps({"access_token": token})
        # Return as-is if we can't determine format (get_calendar_service will validate)
        return creds_value