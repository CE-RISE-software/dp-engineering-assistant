#!/usr/bin/env bash
set -eu

exec python server/mcp_server.py "$@"
