FROM node:22-slim AS node

FROM python:3.11-slim

WORKDIR /app

# Bring Node 22 + npm into the Python image for Binance Agentic Wallet CLI.
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -s /usr/local/lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Install Binance Web3 Wallet CLI used by the MCP Web3 tools.
RUN npm install -g @binance/agentic-wallet

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
    CMD python -c "import socket; s=socket.create_connection(('localhost', 8000), 5); s.close()" || exit 1

CMD ["python", "server.py"]
