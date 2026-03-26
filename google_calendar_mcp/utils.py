"""
Utility functions for the Google Calendar MCP Server.

Provides error formatting, event formatting, and helper functions.
"""

import logging
from datetime import datetime
from typing import Dict, Optional, Tuple

from dateutil import parser as date_parser
from dateutil.tz import gettz

try:
    from geopy.geocoders import Nominatim
    from timezonefinder import TimezoneFinder
    GEOCODING_AVAILABLE = True
except ImportError:
    GEOCODING_AVAILABLE = False

logger = logging.getLogger(__name__)

# Common location to timezone mappings (fallback if geocoding fails)
LOCATION_TIMEZONE_MAP = {
    # Major cities
    'new york': 'America/New_York',
    'los angeles': 'America/Los_Angeles',
    'chicago': 'America/Chicago',
    'denver': 'America/Denver',
    'miami': 'America/New_York',
    'boston': 'America/New_York',
    'seattle': 'America/Los_Angeles',
    'san francisco': 'America/Los_Angeles',
    'houston': 'America/Chicago',
    'atlanta': 'America/New_York',
    'phoenix': 'America/Phoenix',
    'dallas': 'America/Chicago',
    'mumbai': 'Asia/Kolkata',
    'delhi': 'Asia/Kolkata',
    'bangalore': 'Asia/Kolkata',
    'hyderabad': 'Asia/Kolkata',
    'chennai': 'Asia/Kolkata',
    'kolkata': 'Asia/Kolkata',
    'pune': 'Asia/Kolkata',
    'london': 'Europe/London',
    'paris': 'Europe/Paris',
    'berlin': 'Europe/Berlin',
    'rome': 'Europe/Rome',
    'madrid': 'Europe/Madrid',
    'amsterdam': 'Europe/Amsterdam',
    'tokyo': 'Asia/Tokyo',
    'beijing': 'Asia/Shanghai',
    'shanghai': 'Asia/Shanghai',
    'singapore': 'Asia/Singapore',
    'sydney': 'Australia/Sydney',
    'melbourne': 'Australia/Melbourne',
    'toronto': 'America/Toronto',
    'vancouver': 'America/Vancouver',
    'mexico city': 'America/Mexico_City',
    'sao paulo': 'America/Sao_Paulo',
    'buenos aires': 'America/Argentina/Buenos_Aires',
    'cairo': 'Africa/Cairo',
    'johannesburg': 'Africa/Johannesburg',
    'dubai': 'Asia/Dubai',
    'riyadh': 'Asia/Riyadh',
    # Countries (fallback)
    'india': 'Asia/Kolkata',
    'usa': 'America/New_York',
    'united states': 'America/New_York',
    'uk': 'Europe/London',
    'united kingdom': 'Europe/London',
    'canada': 'America/Toronto',
    'australia': 'Australia/Sydney',
    'japan': 'Asia/Tokyo',
    'china': 'Asia/Shanghai',
}


def format_calendar_error(error: Exception) -> str:
    """
    Format calendar API errors into user-friendly messages.
    
    Args:
        error: Exception from Google Calendar API
        
    Returns:
        Formatted error message string
    """
    error_msg = str(error).strip()
    
    if not error_msg:
        return f"Calendar API error: {type(error).__name__}"
    
    # Handle common Google API errors
    if "401" in error_msg or "unauthorized" in error_msg.lower():
        return "Authentication failed. Please check your credentials."
    
    if "403" in error_msg or "forbidden" in error_msg.lower():
        return "Access denied. Check calendar permissions."
    
    if "404" in error_msg or "not found" in error_msg.lower():
        return "Calendar not found or not accessible. Please check: 1) Your credentials have access to the calendar, 2) The calendar ID is correct (use 'primary' for your main calendar), 3) Your Google account has calendar access enabled."
    
    if "timed out" in error_msg.lower() or "winerror 10060" in error_msg.lower():
        return (
            "Network timeout while connecting to Google Calendar API. "
            "If your environment has IPv6 routing issues, set GOOGLE_FORCE_IPV4=true. "
            "You can also increase GOOGLE_HTTP_TIMEOUT_SECONDS (default: 20)."
        )

    if "necessary fields need to refresh the access token" in error_msg.lower():
        return (
            "Access token cannot be refreshed because refresh credentials are missing. "
            "Provide refresh_token, client_id, and client_secret, or send a new access token."
        )

    if "invalid" in error_msg.lower():
        return f"Invalid request: {error_msg[:200]}"
    
    return error_msg[:500]


def format_event_summary(event: Dict, timezone: str = 'Asia/Kolkata') -> str:
    """
    Format a calendar event into a readable summary string.
    
    Args:
        event: Event dictionary from Google Calendar API
        timezone: Timezone for formatting (default: Asia/Kolkata)
        
    Returns:
        Formatted event summary string
    """
    from datetime import datetime
    from dateutil.tz import gettz
    
    summary = event.get('summary', 'No Title')
    event_id = event.get('id', 'N/A')
    start = event.get('start', {})
    start_time_str = start.get('dateTime') or start.get('date', 'N/A')
    
    # Format time in readable format
    try:
        if 'T' in start_time_str:
            # Parse datetime
            if start_time_str.endswith('Z'):
                dt = datetime.fromisoformat(start_time_str.replace('Z', '+00:00'))
            else:
                dt = datetime.fromisoformat(start_time_str)
            
            # Convert to target timezone
            tz_obj = gettz(timezone)
            if tz_obj and dt.tzinfo:
                dt_local = dt.astimezone(tz_obj)
            elif tz_obj:
                dt_local = dt.replace(tzinfo=gettz('UTC')).astimezone(tz_obj)
            else:
                dt_local = dt
            
            # Format as readable date/time
            formatted_time = dt_local.strftime('%d %b %Y, %I:%M %p')
        else:
            # All-day event
            formatted_time = start_time_str
    except Exception:
        # Fallback to original format if parsing fails
        formatted_time = start_time_str
    
    return f"- {summary} ({formatted_time}) [ID: {event_id}]"


def format_calendar_summary(calendar: Dict) -> str:
    """
    Format a calendar into a readable summary string.
    
    Args:
        calendar: Calendar dictionary from Google Calendar API
        
    Returns:
        Formatted calendar summary string
    """
    summary = calendar.get('summary', 'Unnamed Calendar')
    calendar_id = calendar.get('id', 'N/A')
    
    return f"- {summary} (ID: {calendar_id})"


def parse_natural_datetime(date_str: str, time_str: Optional[str] = None, timezone: str = 'Asia/Kolkata') -> Tuple[str, datetime]:
    """
    Parse natural language date and time strings.
    
    Examples:
        date_str="05 Mar 2026", time_str="8am" -> datetime
        date_str="March 5, 2026", time_str="9:00 AM" -> datetime
        date_str="2026-03-05", time_str="14:00" -> datetime
    
    Returns:
        Tuple of (formatted_datetime_string, datetime_object)
    """
    from datetime import datetime
    from dateutil import parser as date_parser
    from dateutil.tz import gettz
    
    try:
        # Combine date and time if both provided
        if time_str:
            # Clean up time string
            time_str = time_str.strip().lower()
            # Handle formats like "8am", "9pm", "14:00", "2:30 PM"
            if 'am' in time_str or 'pm' in time_str:
                # Already has AM/PM
                combined = f"{date_str} {time_str}"
            else:
                # Assume 24-hour format or add default
                if ':' in time_str:
                    combined = f"{date_str} {time_str}"
                else:
                    # Just hour, assume AM
                    combined = f"{date_str} {time_str}:00"
        else:
            combined = date_str
        
        # Get timezone object
        tz_obj = gettz(timezone)
        if tz_obj is None:
            raise ValueError(f"Invalid timezone: {timezone}")
        
        # Parse using dateutil (handles many formats)
        # IMPORTANT: Parse as naive datetime (no timezone) to avoid timezone conversion issues
        # We want "8am" to mean 8am in IST, not 8am in system timezone converted to IST
        dt_naive = date_parser.parse(combined, default=datetime.now().replace(hour=0, minute=0, second=0, microsecond=0))
        
        # CRITICAL: Remove any timezone info that dateutil might have added
        # We want a truly naive datetime so we can assign IST timezone without conversion
        if dt_naive.tzinfo is not None:
            dt_naive = dt_naive.replace(tzinfo=None)
        
        # Create datetime with the specified timezone
        # Using replace() attaches timezone without conversion - this is what we want
        # "8am" should be 8am IST, not converted from another timezone
        dt = dt_naive.replace(tzinfo=tz_obj)
        
        # Format for Google Calendar API (RFC3339 without timezone suffix, timezone specified separately)
        formatted = dt.strftime('%Y-%m-%dT%H:%M:%S')
        
        # Log for debugging
        logger.info(f"PARSING DEBUG: Input='{combined}', Timezone='{timezone}', Parsed naive={dt_naive}, Final={dt}, Formatted={formatted}")
        
        return formatted, dt
        
    except Exception as e:
        raise ValueError(f"Could not parse date/time: {date_str} {time_str or ''}. Error: {e}")


def get_timezone_from_location(location: str) -> Optional[str]:
    """
    Get timezone from location name (city, country, etc.).
    
    Examples:
        "New York" -> "America/New_York"
        "Mumbai" -> "Asia/Kolkata"
        "London" -> "Europe/London"
    
    Args:
        location: Location name (city, country, etc.)
        
    Returns:
        Timezone string (e.g., "America/New_York") or None if not found
    """
    if not location:
        return None
    
    location_lower = location.lower().strip()
    
    # First, check common mappings
    if location_lower in LOCATION_TIMEZONE_MAP:
        timezone = LOCATION_TIMEZONE_MAP[location_lower]
        logger.info(f"Found timezone from mapping: {location} -> {timezone}")
        return timezone
    
    # Try geocoding if available
    if GEOCODING_AVAILABLE:
        try:
            geolocator = Nominatim(user_agent="google-calendar-mcp")
            location_data = geolocator.geocode(location, timeout=10)
            
            if location_data:
                lat, lon = location_data.latitude, location_data.longitude
                tf = TimezoneFinder()
                timezone = tf.timezone_at(lat=lat, lng=lon)
                
                if timezone:
                    logger.info(f"Found timezone via geocoding: {location} ({lat}, {lon}) -> {timezone}")
                    return timezone
        except Exception as e:
            logger.warning(f"Geocoding failed for location '{location}': {e}")
    
    # If geocoding fails, try partial matches in the mapping
    for key, tz in LOCATION_TIMEZONE_MAP.items():
        if key in location_lower or location_lower in key:
            logger.info(f"Found timezone from partial match: {location} -> {tz}")
            return tz
    
    logger.warning(f"Could not determine timezone for location: {location}")
    return None
