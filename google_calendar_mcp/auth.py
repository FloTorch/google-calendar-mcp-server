"""
Authentication and credential handling for Google Calendar MCP Server.

Provides functions to extract credentials from HTTP headers and create
authenticated Google Calendar service instances.
"""

import json
import logging
import os
import socket
from datetime import datetime, timezone
from typing import Optional

import httplib2
import google_auth_httplib2
from google.oauth2 import service_account
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from mcp.server.fastmcp import Context

from google_calendar_mcp.config import SCOPES

logger = logging.getLogger(__name__)


def _is_truthy_env(name: str) -> bool:
    """Parse common truthy env values."""
    value = os.getenv(name, "").strip().lower()
    return value in {"1", "true", "yes", "on"}


class _IPv4OnlyHttp(httplib2.Http):
    """
    httplib2 transport that prefers IPv4 DNS answers.

    This is a targeted workaround for environments where IPv6 connect
    attempts can stall and produce TimeoutError during Google API calls.
    """

    def request(self, uri, method="GET", body=None, headers=None, **kwargs):
        original_getaddrinfo = socket.getaddrinfo

        def ipv4_only_getaddrinfo(host, port, *args, **kwargs):
            infos = original_getaddrinfo(host, port, *args, **kwargs)
            ipv4_infos = [info for info in infos if info[0] == socket.AF_INET]
            return ipv4_infos if ipv4_infos else infos

        socket.getaddrinfo = ipv4_only_getaddrinfo
        try:
            return super().request(uri, method=method, body=body, headers=headers, **kwargs)
        finally:
            socket.getaddrinfo = original_getaddrinfo


def _build_calendar_service_with_transport(creds):
    """
    Build Google Calendar service with optional network transport overrides.

    Env options:
    - GOOGLE_FORCE_IPV4=true: force IPv4 DNS resolution for httplib2
    - GOOGLE_HTTP_TIMEOUT_SECONDS=20: socket timeout for Google HTTP calls
    """
    force_ipv4 = True
    timeout_seconds = 40

    if force_ipv4:
        logger.info("GOOGLE_FORCE_IPV4 is enabled. Using IPv4-only HTTP transport.")
        base_http = _IPv4OnlyHttp(timeout=timeout_seconds)
    else:
        base_http = httplib2.Http(timeout=timeout_seconds)

    can_auto_refresh = True
    if isinstance(creds, Credentials):
        # OAuth token-only credentials cannot refresh without these fields.
        can_auto_refresh = bool(
            creds.refresh_token and creds.client_id and creds.client_secret and creds.token_uri
        )

    if not can_auto_refresh:
        logger.info(
            "OAuth credentials do not include refresh fields. "
            "Disabling auto-refresh-on-401 for this session."
        )

    authed_http = google_auth_httplib2.AuthorizedHttp(
        creds,
        http=base_http,
        refresh_status_codes=(401,) if can_auto_refresh else (),
        max_refresh_attempts=2 if can_auto_refresh else 0,
    )
    return build("calendar", "v3", http=authed_http, cache_discovery=False)


def _extract_headers_from_context(ctx: Optional[Context]) -> dict:
    """Extract HTTP headers from request context as lowercase dict."""
    if not ctx:
        logger.warning("Context is None - no headers available")
        return {}
    
    # Check if headers are stored directly in context (for custom routes)
    if hasattr(ctx, "headers") and ctx.headers:
        logger.info(f"Found headers in ctx.headers: {list(ctx.headers.keys())}")
        return {k.lower(): v for k, v in ctx.headers.items()}
    
    # Try to extract from request context (for MCP tool calls)
    try:
        request_context = ctx.request_context
        if hasattr(request_context, "request") and request_context.request:
            request = request_context.request
            headers_dict = {name.lower(): request.headers[name] for name in request.headers.keys()}
            logger.info(f"Extracted headers from request: {list(headers_dict.keys())}")
            return headers_dict
    except Exception as e:
        logger.warning(f"Could not extract headers from request context: {e}")
    
    logger.warning("No headers found in context")
    return {}


def get_credentials_from_header(ctx: Optional[Context] = None) -> str:
    """
    Extract Google Calendar credentials from HTTP headers.
    
    Supports multiple formats:
    1. JSON string: '{"access_token":"ya29..."}'
    2. Plain access token: 'ya29...'
    3. Bearer token: 'Bearer ya29...'
    
    Args:
        ctx: MCP Context object
        
    Returns:
        JSON string containing credentials
        
    Raises:
        ValueError: If credentials are not found in headers
    """
    if not ctx:
        raise ValueError("Context is required to extract credentials from headers")
    
    try:
        header_dict = _extract_headers_from_context(ctx)
        
        if not header_dict:
            raise ValueError("Request context not available or headers could not be extracted")
        
        # Check for Google Calendar credentials header
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
            return json.dumps({"access_token": token})
        
        # Check if it's already a JSON string
        try:
            json.loads(creds_header)
            return creds_header
        except json.JSONDecodeError:
            # If not JSON, treat as plain token and convert to JSON
            token = creds_header.strip()
            if token.startswith(('ya29.', '1//', 'ya.a0')):
                return json.dumps({"access_token": token})
            return creds_header
            
    except ValueError:
        raise
    except Exception as e:
        logger.error(f"Error extracting credentials from headers: {e}")
        raise ValueError(f"Failed to extract credentials from headers: {str(e)}")


def get_calendar_service(
    google_calendar_credentials: str,
    impersonate_user: Optional[str] = None
):
    """
    Get authenticated Google Calendar service from credentials with automatic token refresh.
    
    Supports multiple credential formats:
    1. Simple access token string: "ya29.a0AfH6SMB..." (expires in ~1 hour, no auto-refresh)
    2. Simple JSON with access_token: {"access_token": "ya29.a0AfH6SMB..."} (expires in ~1 hour, no auto-refresh)
    3. Full OAuth JSON with auto-refresh: {
         "access_token": "ya29...",
         "refresh_token": "1//04...",
         "client_id": "your-client-id.apps.googleusercontent.com",
         "client_secret": "your-client-secret",
         "token_uri": "https://oauth2.googleapis.com/token"  // optional, defaults to this
       }
    4. Service Account JSON: {"type":"service_account","project_id":"...","private_key":"...","client_email":"..."}
    
    IMPORTANT for automatic token refresh:
    - To enable automatic refresh, provide: access_token, refresh_token, client_id, and client_secret
    - The access token will be automatically refreshed when it expires (every ~1 hour)
    - Without client_id and client_secret, you'll need to manually provide a new access token every hour
    
    Args:
        google_calendar_credentials: Credentials in one of the supported formats
        impersonate_user: Optional email for service account domain-wide delegation
        
    Returns:
        Authenticated Google Calendar service object (tokens automatically refreshed if credentials support it)
        
    Raises:
        ValueError: If credentials format is invalid or authentication fails
    """
    creds_data = None
    
    # Try to parse as JSON first
    try:
        creds_data = json.loads(google_calendar_credentials)
    except json.JSONDecodeError:
        # If not JSON, treat as simple access token string
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
    
    # Method 1: Service Account
    if creds_data.get('type') == 'service_account':
        try:
            creds = service_account.Credentials.from_service_account_info(
                creds_data, scopes=SCOPES
            )
            
            if impersonate_user:
                creds = creds.with_subject(impersonate_user)
            
            return _build_calendar_service_with_transport(creds)
        except Exception as e:
            raise ValueError(f"Service Account authentication failed: {e}")
    
    # Method 2: OAuth Token
    elif 'token' in creds_data or 'access_token' in creds_data:
        try:
            token = creds_data.get('token') or creds_data.get('access_token')
            refresh_token = creds_data.get('refresh_token')
            token_uri = creds_data.get('token_uri', 'https://oauth2.googleapis.com/token')
            client_id = creds_data.get('client_id')
            client_secret = creds_data.get('client_secret')
            
            # Try to get client_id and client_secret from environment if not provided
            if not client_id:
                client_id = os.getenv("GOOGLE_CLIENT_ID")
            if not client_secret:
                client_secret = os.getenv("GOOGLE_CLIENT_SECRET")
            
            if not token:
                raise ValueError("OAuth token must contain 'token' or 'access_token' field")
            
            # Check if we have refresh capability
            has_refresh_token = bool(refresh_token)
            has_client_credentials = bool(client_id and client_secret)
            
            if has_refresh_token and not has_client_credentials:
                logger.warning(
                    "Refresh token provided but client_id and client_secret are missing. "
                    "Automatic token refresh will not work. Please provide client_id and client_secret for automatic refresh."
                )
                # Still create credentials but without refresh capability
                creds = Credentials(token=token, scopes=SCOPES)
            elif has_refresh_token and has_client_credentials:
                # Full OAuth credentials with automatic refresh capability
                creds = Credentials(
                    token=token,
                    refresh_token=refresh_token,
                    token_uri=token_uri,
                    client_id=client_id,
                    client_secret=client_secret,
                    scopes=SCOPES
                )
                
                # Automatically refresh if expired
                # The Credentials object automatically handles expiry checking
                if creds.expired:
                    try:
                        logger.info("Access token expired. Refreshing token automatically...")
                        creds.refresh(Request())
                        logger.info("Token refreshed successfully. New expiry: %s", creds.expiry)
                    except Exception as refresh_error:
                        logger.error(f"Failed to refresh token: {refresh_error}")
                        raise ValueError(
                            f"Failed to refresh expired token: {refresh_error}. "
                            "Please check your refresh_token, client_id, and client_secret are correct."
                        )
                else:
                    # Token is still valid, but log when it will expire
                    if creds.expiry:
                        now = datetime.now(creds.expiry.tzinfo if creds.expiry.tzinfo else timezone.utc)
                        time_until_expiry = (creds.expiry - now).total_seconds()
                        if time_until_expiry > 0:
                            logger.debug(f"Access token valid. Expires in {int(time_until_expiry/60)} minutes")
            else:
                # Simple access token only - works for ~1 hour
                logger.warning(
                    "No refresh token provided. Access token will expire in ~1 hour. "
                    "To enable automatic refresh, provide refresh_token, client_id, and client_secret."
                )
                creds = Credentials(token=token, scopes=SCOPES)
            
            return _build_calendar_service_with_transport(creds)
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
