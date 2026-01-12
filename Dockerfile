# Use Python 3.11 slim image for smaller size
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PORT=8000

# Copy requirements file
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the MCP server file
COPY google_calendar_mcp_server.py .

# Expose the port (default 8000, can be overridden via PORT env var)
EXPOSE 8000

# Run the MCP server
CMD ["python", "google_calendar_mcp_server.py"]

