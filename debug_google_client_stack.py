"""
Diagnose Google Calendar connectivity using the same client stack as the MCP server.

This script helps isolate failures into:
- DNS resolution problems
- TCP connectivity issues (timeout/refused)
- HTTPS/TLS/proxy errors
- Google Calendar API/auth errors
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import ssl
from typing import Any, Dict, List, Optional

import httplib2
from googleapiclient.errors import HttpError

from google_calendar_mcp.auth import get_calendar_service


GOOGLE_HOSTS = [
    "www.googleapis.com",
    "oauth2.googleapis.com",
]

DISCOVERY_URL = "https://www.googleapis.com/discovery/v1/apis/calendar/v3/rest"


def _mask(value: Optional[str]) -> str:
    """Mask secrets for debug output."""
    if not value:
        return "<missing>"
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}...{value[-4:]}"


def _load_credentials(args: argparse.Namespace) -> str:
    """
    Resolve credentials in this order:
    1) --credentials (JSON or raw token)
    2) --credentials-file (file contents)
    3) GOOGLE_CALENDAR_CREDENTIALS env
    """
    if args.credentials:
        return args.credentials.strip()

    if args.credentials_file:
        with open(args.credentials_file, "r", encoding="utf-8") as f:
            return f.read().strip()

    env_value = os.getenv("GOOGLE_CALENDAR_CREDENTIALS", "").strip()
    if env_value:
        return env_value

    raise ValueError(
        "No credentials found. Pass --credentials, --credentials-file, "
        "or set GOOGLE_CALENDAR_CREDENTIALS."
    )


def _credential_summary(credentials_str: str) -> Dict[str, Any]:
    """Return non-sensitive summary about credential shape."""
    try:
        data = json.loads(credentials_str)
    except json.JSONDecodeError:
        data = {"access_token": credentials_str}

    token = data.get("access_token") or data.get("token")
    refresh = data.get("refresh_token")
    client_id = data.get("client_id") or os.getenv("GOOGLE_CLIENT_ID")
    client_secret = data.get("client_secret") or os.getenv("GOOGLE_CLIENT_SECRET")
    cred_type = data.get("type")

    return {
        "credential_type": cred_type or "oauth_token",
        "has_access_token": bool(token),
        "has_refresh_token": bool(refresh),
        "has_client_id": bool(client_id),
        "has_client_secret": bool(client_secret),
        "token_preview": _mask(token),
    }


def _dns_check(host: str) -> Dict[str, Any]:
    try:
        infos = socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
        ips = sorted({item[4][0] for item in infos})
        return {"ok": True, "ips": ips}
    except socket.gaierror as e:
        return {"ok": False, "error_type": "dns_error", "message": str(e)}
    except Exception as e:  # pragma: no cover - defensive
        return {"ok": False, "error_type": type(e).__name__, "message": str(e)}


def _tcp_check(host: str, timeout_seconds: float) -> Dict[str, Any]:
    try:
        with socket.create_connection((host, 443), timeout=timeout_seconds):
            return {"ok": True}
    except socket.timeout as e:
        return {"ok": False, "error_type": "timeout", "message": str(e)}
    except ConnectionRefusedError as e:
        return {"ok": False, "error_type": "connection_refused", "message": str(e)}
    except OSError as e:
        return {"ok": False, "error_type": "os_error", "message": str(e)}


def _https_check(timeout_seconds: float) -> Dict[str, Any]:
    try:
        # Same base transport family used by googleapiclient in this repo.
        http = httplib2.Http(timeout=timeout_seconds)
        response, _content = http.request(DISCOVERY_URL, "GET")
        return {
            "ok": True,
            "status": int(getattr(response, "status", 0)),
            "reason": getattr(response, "reason", ""),
        }
    except socket.timeout as e:
        return {"ok": False, "error_type": "timeout", "message": str(e)}
    except ssl.SSLError as e:
        return {"ok": False, "error_type": "ssl_error", "message": str(e)}
    except httplib2.ServerNotFoundError as e:
        return {"ok": False, "error_type": "server_not_found", "message": str(e)}
    except Exception as e:
        return {"ok": False, "error_type": type(e).__name__, "message": str(e)}


def _google_client_check(
    credentials: str, timeout_seconds: float, impersonate_user: Optional[str]
) -> Dict[str, Any]:
    try:
        service = get_calendar_service(credentials, impersonate_user=impersonate_user)
        # Force the same stack path that currently fails in list_calendars.
        request = service.calendarList().list(maxResults=1)

        # The google client accepts num_retries, but low-level socket timeout
        # behavior is what we want to observe quickly. Keep retries minimal.
        result = request.execute(num_retries=0)
        items = result.get("items", [])
        return {"ok": True, "calendar_count_returned": len(items)}
    except HttpError as e:
        return {
            "ok": False,
            "error_type": "http_error",
            "status_code": int(getattr(e.resp, "status", 0)),
            "message": str(e),
        }
    except socket.timeout as e:
        return {"ok": False, "error_type": "timeout", "message": str(e)}
    except ssl.SSLError as e:
        return {"ok": False, "error_type": "ssl_error", "message": str(e)}
    except httplib2.ServerNotFoundError as e:
        return {"ok": False, "error_type": "server_not_found", "message": str(e)}
    except Exception as e:
        return {"ok": False, "error_type": type(e).__name__, "message": str(e)}


def _proxy_summary() -> Dict[str, str]:
    return {
        "HTTP_PROXY": os.getenv("HTTP_PROXY", ""),
        "HTTPS_PROXY": os.getenv("HTTPS_PROXY", ""),
        "NO_PROXY": os.getenv("NO_PROXY", ""),
    }


def run_diagnostics(
    credentials: str, timeout_seconds: float, impersonate_user: Optional[str]
) -> Dict[str, Any]:
    host_results: List[Dict[str, Any]] = []
    for host in GOOGLE_HOSTS:
        host_results.append(
            {
                "host": host,
                "dns": _dns_check(host),
                "tcp_443": _tcp_check(host, timeout_seconds=timeout_seconds),
            }
        )

    previous_default_timeout = socket.getdefaulttimeout()
    socket.setdefaulttimeout(timeout_seconds)
    try:
        google_client_result = _google_client_check(
            credentials=credentials,
            timeout_seconds=timeout_seconds,
            impersonate_user=impersonate_user,
        )
    finally:
        socket.setdefaulttimeout(previous_default_timeout)

    report = {
        "proxy_env": _proxy_summary(),
        "credentials": _credential_summary(credentials),
        "hosts": host_results,
        "https_discovery": _https_check(timeout_seconds=timeout_seconds),
        "google_client_stack": google_client_result,
    }
    return report


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Diagnose Google Calendar network/auth issues with the MCP client stack."
    )
    parser.add_argument(
        "--credentials",
        help="Google credentials as JSON string or raw access token",
    )
    parser.add_argument(
        "--credentials-file",
        help="Path to a file containing Google credentials JSON or access token",
    )
    parser.add_argument(
        "--impersonate-user",
        help="Optional user email for service-account domain-wide delegation",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=8.0,
        help="Socket/connect timeout in seconds (default: 8.0)",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Pretty-print JSON output",
    )
    args = parser.parse_args()

    credentials = _load_credentials(args)
    report = run_diagnostics(
        credentials=credentials,
        timeout_seconds=args.timeout,
        impersonate_user=args.impersonate_user,
    )

    if args.pretty:
        print(json.dumps(report, indent=2))
    else:
        print(json.dumps(report))


if __name__ == "__main__":
    main()
