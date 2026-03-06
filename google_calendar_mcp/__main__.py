"""
Entry point for running the Google Calendar MCP Server.

Usage:
    python -m google_calendar_mcp
"""

import asyncio

from google_calendar_mcp.server import main

if __name__ == "__main__":
    asyncio.run(main())
