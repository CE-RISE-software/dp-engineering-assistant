FROM python:3.12-slim

LABEL io.modelcontextprotocol.server.name="io.github.CE-RISE-software/dp-engineering-assistant"

WORKDIR /app

COPY data/ data/
COPY server/ server/

ENTRYPOINT ["python", "/app/server/mcp_server.py"]
