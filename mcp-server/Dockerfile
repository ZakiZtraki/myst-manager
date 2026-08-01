FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Install crypto-portfolio dependencies
COPY crypto-portfolio/requirements.txt /tmp/cp_requirements.txt
RUN pip install --no-cache-dir -r /tmp/cp_requirements.txt

# Install MCP server dependencies
COPY mcp-server/requirements.txt /tmp/mcp_requirements.txt
RUN pip install --no-cache-dir -r /tmp/mcp_requirements.txt

# Copy source code
COPY crypto-portfolio/src /app/crypto-portfolio/src
COPY mcp-server/server.py  /app/mcp-server/server.py
COPY mcp-server/scheduler.py /app/mcp-server/scheduler.py

# Data directory for portfolio.json and exports
RUN mkdir -p /data

WORKDIR /app/mcp-server

EXPOSE 8000

ENV PYTHONPATH=/app
ENV PORTFOLIO_FILE=/data/portfolio.json
ENV MCP_HOST=0.0.0.0
ENV MCP_PORT=8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import socket; s=socket.socket(); s.settimeout(3); s.connect(('localhost', 8000)); s.close()" || exit 1

CMD ["python", "server.py"]
