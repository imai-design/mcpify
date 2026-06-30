# Xquik OpenAPI Example

This example generates all MCPify outputs from Xquik's published OpenAPI document.

## Generate

```bash
mcpify https://xquik.com/openapi.json
```

MCPify creates the normalized OpenAPI file, MCP server, Claude Code Skill, and CLI under `output/`.

## Run The Generated MCP Server

```bash
cd output/mcp_server
pip install -r requirements.txt
export MCPIFY_BASE_URL="https://xquik.com"
export MCPIFY_AUTH_HEADER="x-api-key"
export MCPIFY_AUTH_TOKEN="<your-xquik-api-key>"
python server.py
```

`MCPIFY_AUTH_HEADER` tells the generated server to send Xquik's API key header instead of a bearer token.

## Try A Read Operation

Start with read operations such as tweet lookup, tweet search, user lookup, or trends. The generated MCP server keeps each operation's parameters aligned with the OpenAPI schema.

Write and automation operations should stay explicit user actions because they can create or modify X content.
