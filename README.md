---
title: Google Calendar MCP Server
emoji: 📅
colorFrom: blue
colorTo: purple
sdk: docker
app_port: 7860
---

# Google Calendar MCP Server

A FastMCP server for managing Google Calendar events with natural language date/time parsing. Built with Python and FastMCP, this server provides both simplified REST endpoints for workflows and full MCP (Model Context Protocol) support for AI agents.

## Features

- ✅ **Natural Language Date/Time Parsing** - Create events using human-readable dates like "05 Mar 2026" and times like "8am"
- ✅ **Multiple Calendar Operations** - List calendars, get events, create events, check availability, and delete events
- ✅ **Automatic Timezone Detection** - Auto-detects timezone from location (e.g., "New York" → "America/New_York")
- ✅ **Email Notifications** - Send email invitations to attendees automatically
- ✅ **Google Meet Integration** - Automatically add Google Meet video conference links
- ✅ **Flexible Authentication** - Supports OAuth tokens, service accounts, and automatic token refresh

- ✅ **Default Timezone** - Defaults to Asia/Kolkata (IST) but can be customized
- ✅ **Production Ready** - Multi-stage Docker build, health checks, and Docker Compose support

## Installation

### Using Docker (Recommended)

**Option 1: Docker Compose (Recommended for Production)**

```bash
# Build and run with docker-compose
docker-compose up -d

# View logs
docker-compose logs -f

# Stop the service
docker-compose down
```

**Option 2: Docker Run**

```bash
# Build the Docker image
docker build -t google-calendar-mcp .

# Run the container
docker run -p 7860:7860 \
  -e PORT=7860 \
  -e HOST=0.0.0.0 \
  google-calendar-mcp
```

**Verify the server:**

```bash
curl http://localhost:7860/google-calendar/mcp
```

Expected: JSON with `"transport": "HTTP_STREAMABLE"` and a short message.

### Local Development

```bash
# Clone the repository
git clone <repository-url>
cd google-calendar-mcp-server

# Create and activate virtual environment (recommended)
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Install the package in editable mode
pip install -e .

# Run the server
python -m google_calendar_mcp
```

The server will start on `http://0.0.0.0:7860` by default.

## Authentication

The server supports multiple authentication methods. Credentials can be provided via HTTP headers or environment variables.

### Supported Credential Formats

1. **Simple Access Token** (expires in ~1 hour, **no automatic refresh**)
   ```
   X-Google-Calendar-Credentials: ya29.a0AfH6SMB...
   ```
   
   **Note:** If you provide only an access token (without refresh_token, client_id, and client_secret), the token will expire within approximately 1 hour and will **not** be automatically refreshed. You will need to provide a new access token after expiration.

2. **OAuth JSON with Auto-Refresh** (recommended for long-running services)
   ```json
   {
     "access_token": "ya29...",
     "refresh_token": "1//04...",
     "client_id": "your-client-id.apps.googleusercontent.com",
     "client_secret": "your-client-secret",
     "token_uri": "https://oauth2.googleapis.com/token"
   }
   ```
   
   **Note:** When you provide **all four components** (access_token, refresh_token, client_id, and client_secret), the server will **automatically refresh** the access token when it expires. This is the recommended approach for production deployments and long-running services.

3. **Service Account JSON**
   ```json
   {
     "type": "service_account",
     "project_id": "...",
     "private_key": "...",
     "client_email": "..."
   }
   ```

### Authentication Methods

#### Method 1: HTTP Headers (Recommended)

**Option A: Separate Headers**
```
X-Google-Calendar-Credentials: <access_token>
X-Google-Calendar-Refresh-Token: <refresh_token> (optional)
X-Google-Calendar-Client-Id: <client_id> (optional)
X-Google-Calendar-Client-Secret: <client_secret> (optional)
```

**Option B: Single JSON Header**
```
X-Google-Calendar-Credentials: {"access_token":"ya29...","refresh_token":"...","client_id":"...","client_secret":"..."}
```

**Token Refresh Behavior:**
- **With refresh token + client credentials:** If you provide `access_token`, `refresh_token`, `client_id`, and `client_secret` together, the server will automatically refresh the access token when it expires.
- **Access token only:** If you provide only the `access_token` (without refresh_token, client_id, and client_secret), the token will expire in ~1 hour and will **not** be automatically refreshed.

**Priority:** HTTP headers are checked first, then environment variables.

## API Endpoints

### Discovery Endpoint

**GET** `/google-calendar/mcp`

Returns transport information for MCP clients. This endpoint is used by MCP clients to discover the server's transport configuration.

**Response:**
```json
{
  "transport": "HTTP_STREAMABLE",
  "protocol": "streamable-http",
  "message": "Google Calendar MCP Server - Set transport to HTTP_STREAMABLE"
}
```

The streamable HTTP transport is also available at the same path (`/google-calendar/mcp`).

### Simplified REST Endpoints (For Workflows)

These endpoints accept simplified JSON without JSON-RPC wrapper.

#### Create Event

**POST** `/create_event`

```json
{
  "summary": "Team Meeting",
  "date": "07 Mar 2026",
  "start_time": "8am",
  "end_time": "9am",
  "description": "Quarterly planning session",
  "location": "New York",
  "attendees": "john@example.com, jane@example.com",
  "send_notifications": true,
  "add_google_meet": true,
  "reminders_minutes": 15,
  "calendar_id": "primary",
  "timezone": "America/New_York"
}
```

**Response:**
```json
{
  "success": true,
  "result": "Event created: Team Meeting (ID: abc123...)\nGoogle Meet link: https://meet.google.com/...\nEmail notifications sent to 2 attendee(s)"
}
```

#### Get Events

**POST** `/get_events`

```json
{
  "calendar_id": "primary",
  "max_results": 10,
  "date": "07 Mar 2026",
  "location": "New York"
}
```

**Response:**
```json
{
  "success": true,
  "result": "Found 3 event(s):\n- Team Meeting (07 Mar 2026, 08:00 AM) [ID: abc123...]\n..."
}
```

#### Check Availability

**POST** `/check_availability`

```json
{
  "date": "07 Mar 2026",
  "start_time": "8am",
  "end_time": "10am",
  "location": "New York"
}
```

**Response:**
```json
{
  "success": true,
  "result": "Available: The time slot is free."
}
```

#### Delete Event

**POST** `/delete_event`

**Option 1: Delete by Event ID**
```json
{
  "event_id": "abc123..."
}
```

**Option 2: Delete by Date, Time, and Summary**
```json
{
  "date": "07 Mar 2026",
  "start_time": "8:30am",
  "summary": "Team Meeting"
}
```

**Option 3: Delete by Date and Time Only**
```json
{
  "date": "07 Mar 2026",
  "start_time": "8:30am"
}
```

#### List Calendars

**POST** `/list_calendars`

```json
{}
```

**Response:**
```json
{
  "success": true,
  "result": "- My Calendar (ID: primary)\n- Work Calendar (ID: work@example.com)"
}
```

### MCP JSON-RPC Endpoint (For AI Agents)

**POST** `/google-calendar/mcp`

Full MCP protocol support for AI agents using JSON-RPC 2.0 format. The streamable HTTP transport and discovery endpoint are both available at `/google-calendar/mcp`.

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/call",
  "params": {
    "name": "create_event",
    "arguments": {
      "summary": "Team Meeting",
      "date": "07 Mar 2026",
      "start_time": "8am",
      "end_time": "9am",
      "attendees": "john@example.com"
    }
  }
}
```

## Available Tools

### `list_calendars`
List all available calendars for the authenticated user.

**Parameters:**
- `impersonate_user` (optional): Email for service account domain-wide delegation

### `get_events`
Retrieve calendar events.

**Parameters:**
- `calendar_id` (default: "primary"): Calendar ID
- `max_results` (default: 10): Maximum number of events
- `time_min` (optional): Start time in ISO format
- `time_max` (optional): End time in ISO format
- `impersonate_user` (optional): Email for service account domain-wide delegation

### `create_event`
Create a new calendar event with natural language date/time.

**Parameters:**
- `summary` (required): Event title
- `date` (required): Date in natural language (e.g., "05 Mar 2026", "March 5, 2026")
- `start_time` (required): Start time in natural language (e.g., "8am", "9:00 AM", "14:00")
- `end_time` (optional): End time (defaults to 1 hour after start)
- `description` (optional): Event description
- `location` (optional): Event location (timezone auto-detected if provided)
- `attendees` (optional): Comma-separated email addresses
- `send_notifications` (default: true): Send email notifications to attendees
- `add_google_meet` (default: true): Add Google Meet video conference link
- `reminders_minutes` (default: 15): Minutes before event for reminder (set to null to disable)
- `calendar_id` (default: "primary"): Calendar ID
- `timezone` (optional): Timezone (e.g., "America/New_York", defaults to "Asia/Kolkata")
- `impersonate_user` (optional): Email for service account domain-wide delegation

### `check_availability`
Check if a time slot is available.

**Parameters:**
- `date` (required): Date in natural language
- `start_time` (required): Start time in natural language
- `end_time` (optional): End time (defaults to 1 hour after start)
- `location` (optional): Location for timezone detection
- `calendar_id` (default: "primary"): Calendar ID
- `timezone` (optional): Timezone
- `impersonate_user` (optional): Email for service account domain-wide delegation

### `delete_event`
Delete a calendar event.

**Parameters:**
- `event_id` (optional): Event ID (preferred method)
- `date` (optional): Date in natural language
- `start_time` (optional): Start time in natural language
- `summary` (optional): Event summary/title
- `location` (optional): Location for timezone detection
- `calendar_id` (default: "primary"): Calendar ID
- `timezone` (optional): Timezone
- `impersonate_user` (optional): Email for service account domain-wide delegation

## Date and Time Formats

The server supports flexible natural language date and time parsing:

### Date Formats
- `"05 Mar 2026"`
- `"March 5, 2026"`
- `"2026-03-05"`
- `"5/3/2026"`

### Time Formats
- `"8am"` or `"8AM"`
- `"9pm"` or `"9PM"`
- `"9:00 AM"` or `"9:00AM"`
- `"14:00"` (24-hour format)
- `"2:30 PM"`

## Timezone Handling

1. **Explicit Timezone**: If `timezone` parameter is provided, it's used directly.
2. **Location-Based**: If `location` is provided, timezone is auto-detected using geocoding.
3. **Default**: Falls back to `Asia/Kolkata` (IST) if neither is provided.

**Supported Locations for Auto-Detection:**
- Major cities (New York, London, Tokyo, Mumbai, etc.)
- Countries (USA, UK, India, etc.)
- Custom locations via geocoding (requires internet connection)

## Configuration

### Environment Variables

- `PORT` (default: 7860): Server port
- `HOST` (default: 0.0.0.0): Server host
- `GOOGLE_CALENDAR_CREDENTIALS`: Fallback credentials if not in headers (JSON string or access token)
- `GOOGLE_CLIENT_ID`: OAuth client ID (for token refresh)
- `GOOGLE_CLIENT_SECRET`: OAuth client secret (for token refresh)

### Docker Environment

When using Docker or Docker Compose, you can set environment variables in:
- `.env` file (loaded automatically by docker-compose)
- Docker run command: `-e VARIABLE=value`
- Docker Compose `environment` section

### Default Values

- Default Calendar: `"primary"`
- Default Max Results: `10`
- Default Reminders: `15 minutes`
- Default Timezone: `"Asia/Kolkata"` (IST)

## Project Structure

```
google-calendar-mcp-server/
├── google_calendar_mcp/
│   ├── __init__.py
│   ├── __main__.py          # Entry point
│   ├── server.py            # FastMCP server and routes
│   ├── auth.py              # Authentication and credential handling
│   ├── config.py            # Configuration and constants
│   ├── utils.py             # Utility functions (parsing, formatting)
│   └── tools/               # MCP tools
│       ├── __init__.py
│       ├── create_event.py
│       ├── delete_event.py
│       ├── get_events.py
│       ├── list_calendars.py
│       └── check_availability.py
├── Dockerfile               # Multi-stage production Docker build
├── docker-compose.yml       # Docker Compose configuration
├── pyproject.toml            # Package configuration
├── requirements.txt         # Python dependencies
├── .dockerignore            # Docker build exclusions
└── README.md
```

## Usage Examples

### Example 1: Create Event with cURL

```bash
curl -X POST http://localhost:7860/create_event \
  -H "Content-Type: application/json" \
  -H "X-Google-Calendar-Credentials: ya29.a0AfH6SMB..." \
  -d '{
    "summary": "Team Standup",
    "date": "10 Mar 2026",
    "start_time": "9am",
    "end_time": "9:30am",
    "location": "San Francisco",
    "attendees": "team@example.com"
  }'
```

### Example 2: Get Events for a Specific Date

```bash
curl -X POST http://localhost:7860/get_events \
  -H "Content-Type: application/json" \
  -H "X-Google-Calendar-Credentials: ya29.a0AfH6SMB..." \
  -d '{
    "date": "10 Mar 2026",
    "max_results": 20
  }'
```

### Example 3: Check Availability

```bash
curl -X POST http://localhost:7860/check_availability \
  -H "Content-Type: application/json" \
  -H "X-Google-Calendar-Credentials: ya29.a0AfH6SMB..." \
  -d '{
    "date": "10 Mar 2026",
    "start_time": "2pm",
    "end_time": "3pm"
  }'
```

## Error Handling

The server provides user-friendly error messages for common issues:

- **401 Unauthorized**: Authentication failed - check credentials
- **403 Forbidden**: Access denied - check calendar permissions
- **404 Not Found**: Calendar not found or not accessible
- **Invalid Date/Time**: Unable to parse the provided date/time format

## Token Refresh

### Automatic Token Refresh

For automatic token refresh, you **must provide all four components**:
- `access_token` - The current access token
- `refresh_token` - The refresh token for obtaining new access tokens
- `client_id` - Your OAuth client ID
- `client_secret` - Your OAuth client secret

When all four components are provided, the server will **automatically refresh** the access token when it expires (typically after ~1 hour). The refresh happens transparently during API calls, so you don't need to manually update the token.

### Access Token Only (No Refresh)

If you provide **only** the `access_token` (without refresh_token, client_id, and client_secret):
- The token will work for approximately **1 hour**
- After expiration, the token will **not** be automatically refreshed
- You will need to provide a new access token manually

**Recommendation:** For production deployments and long-running services, always provide all four components (access_token, refresh_token, client_id, client_secret) to enable automatic token refresh.

## Service Account Support

Service accounts can be used with domain-wide delegation:

```json
{
  "type": "service_account",
  "project_id": "...",
  "private_key": "...",
  "client_email": "..."
}
```

Use the `impersonate_user` parameter to specify which user to impersonate.

## Development

### Running Locally

```bash
# Install dependencies
pip install -r requirements.txt

# Install the package in editable mode (recommended)
pip install -e .

# Run the server
python -m google_calendar_mcp
```

### Docker: Build and Verify

**1. Build the image**

```bash
docker build -t google-calendar-mcp .
```

**2. Run the container**

```bash
docker run -d -p 7860:7860 \
  -e PORT=7860 \
  -e HOST=0.0.0.0 \
  --name google-calendar-mcp \
  google-calendar-mcp
```

**3. Verify the server**

```bash
curl -s http://localhost:7860/google-calendar/mcp
```

Expected: JSON with `"transport": "HTTP_STREAMABLE"` and a short message. A healthy container passes the Docker HEALTHCHECK (discovery endpoint returns 200).

**PowerShell (Windows):** Use `;` instead of `\` for line continuation, or run the `docker run` command as a single line as above.

**Optional – docker-compose:** The repo includes `docker-compose.yml` for convenience (e.g. `docker-compose up -d`). It is not required if you run the container with `docker run` or deploy via another orchestrator.

### Testing

Test the server using the simplified endpoints or MCP JSON-RPC format. Ensure you have valid Google Calendar credentials.

### MCP Configuration

**Gateway / tool metadata:**

```ts
{
  templateId: "google-calendar-mcp",
  name: "Google Calendar MCP",
  description: "Manage Google Calendar events with natural language date/time parsing. Credentials via headers: X-Google-Calendar-Credentials.",
  category: "Productivity",
  icon: "i-lucide-calendar",
  url: "",
  transport: "HTTP_STREAMABLE" as const,
  metadata: {
    transport: "HTTP_STREAMABLE" as const,
    timeout: 30000,
    sse_read_timeout: 30000,
    terminate_on_close: true,
  },
  requiredFields: [],
  baseHeaders: {},
  isEnabled: false,
}
```

**Local MCP client (JSON):**

```json
{
  "transport": "HTTP_STREAMABLE",
  "url": "http://localhost:7860/google-calendar/mcp",
  "headers": {
    "X-Google-Calendar-Credentials": "your_access_token"
  },
  "timeout": 30000,
  "sse_read_timeout": 30000
}
```


