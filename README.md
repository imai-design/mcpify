# MCPify

> **One command, four channels.** Turn any existing app into an OpenAPI spec, an MCP Server, a Claude Code Skill, and a CLI — all at once.

```bash
mcpify https://petstore3.swagger.io/api/v3/openapi.json --name petstore
```

…and you get:

```
output/
├── openapi.json                 # normalized OpenAPI 3.x spec
├── mcp_server/
│   ├── server.py                # Python MCP server (FastMCP)
│   ├── requirements.txt
│   ├── claude_desktop_config.example.json
│   └── README.md
├── skills/petstore/
│   └── SKILL.md                 # Claude Code skill — operation guide in plain language
└── cli/
    ├── petstore.py              # standalone Python CLI with subcommands per operation
    └── README.md
```

## Why

> なんでみんなアプリに行くんだ？なぜエージェント向けAPIに行かないの？  
> — Siglume (@Siglume736)

> API・MCP・Skills・CLI を全展開すれば、API docs を読まずに非エンジニアでもAIが操作できる。  
> — Taiyo (@taiyo_ai_gakuse)

AI agents are the new front door. If your app does not expose an authenticated MCP server, an OpenAPI surface, a Claude Code Skill, and a CLI, then agents can't find or drive it. **MCPify ships all four from a single source of truth.**

## Install

Requires Python 3.9+.

```bash
git clone https://github.com/imai-design/mcpify.git
cd mcpify
pip install -e .
```

Or run without installing:

```bash
PYTHONPATH=src python3 -m mcpify <target>
```

## Usage

```
mcpify TARGET [--out PATH] [--name NAME] [--base-url URL] [--only CHANNEL]

  TARGET         OpenAPI document. URL (http/https) or local path (json/yaml).
  --out, -o      Output directory (default: ./output)
  --name, -n     Project slug (default: derived from OpenAPI title)
  --base-url     Override servers[0].url in generated code
  --only         One of: openapi | mcp | skill | cli | all (default: all)
```

### Examples

```bash
# Full generation from a public OpenAPI URL
mcpify https://petstore3.swagger.io/api/v3/openapi.json --name petstore

# Local YAML, only generate the MCP server
mcpify ./my-api.yaml --only mcp --name myapp

# Override base URL (useful when the spec uses a relative servers[].url)
mcpify ./spec.json --base-url https://prod.example.com --name myapp
```

## Running the generated MCP server

```bash
cd output/mcp_server
pip install -r requirements.txt
export MCPIFY_BASE_URL="https://your-api.example.com"
export MCPIFY_AUTH_TOKEN="your-bearer-token"
python server.py
```

Add to Claude Desktop by copying the snippet in `claude_desktop_config.example.json`
into `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS).

## Running the generated CLI

```bash
export MCPIFY_BASE_URL="https://your-api.example.com"
export MCPIFY_AUTH_TOKEN="your-token"
python output/cli/petstore.py --help
python output/cli/petstore.py find-pets-by-status --status available
```

## Auth

The generated MCP server and CLI both honor:

| Env var               | Purpose                                                   |
|-----------------------|-----------------------------------------------------------|
| `MCPIFY_BASE_URL`      | Override the base URL of the upstream API                 |
| `MCPIFY_AUTH_HEADER`   | Header name (default `Authorization`)                     |
| `MCPIFY_AUTH_TOKEN`    | Token; auto-prefixed with `Bearer ` if no prefix is given |
| `MCPIFY_API_KEY`       | API key sent as a query parameter                         |
| `MCPIFY_API_KEY_PARAM` | Query parameter name for the key (default `key`)          |
| `MCPIFY_USER_AGENT`    | User-Agent to identify with (default `MCPify/0.1`)        |

Not every API takes a bearer token. Google APIs, for instance, expect the key
as a query parameter — use `MCPIFY_API_KEY` for those:

```bash
export MCPIFY_API_KEY="AIza..."          # YouTube Data API, Maps, ...
python3 out/cli/youtube.py youtube-search-list --part snippet --q "openapi"
```

Full OAuth2 / cookie-session proxy is on the v0.2 roadmap.

## Roadmap

- **v0.1** ✅ OpenAPI → 4 channels (this release)
- **v0.2** Framework route detection: Next.js / Django / Rails / Laravel
- **v0.3** Playwright recorder mode — works without source code
- **v0.4** OAuth2 / cookie-session proxy (Gatekeeper layer)
- **v0.5** TypeScript MCP server output option

## License

MIT — © 2026 RYOSEIWORLD合同会社 / imai-design

## Credits

Born from a 2026-05-28 thread between **@Siglume736** and **@taiyo_ai_gakuse** on X.
Built in one sitting by Claude as the loyal retainer of his King.
