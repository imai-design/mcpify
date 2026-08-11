# MCPify

[![test](https://github.com/imai-design/mcpify/actions/workflows/test.yml/badge.svg)](https://github.com/imai-design/mcpify/actions/workflows/test.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)

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

MCPify itself runs on the standard library. JSON specs need nothing else.
**YAML specs need PyYAML** (`pip install pyyaml`) — many public specs are YAML,
so install it unless you know yours are JSON. The generated CLI is also
dependency-free; only the generated MCP server pulls in `mcp` and `httpx`,
listed in its own `requirements.txt`.

## Usage

```
mcpify TARGET [--out PATH] [--name NAME] [--base-url URL] [--only CHANNEL]
              [--allow-local] [--trust-spec-server] [--force]

  TARGET               OpenAPI document. URL (http/https) or local path (json/yaml).
  --out, -o            Output directory (default: ./output)
  --name, -n           Project slug (default: derived from OpenAPI title)
  --base-url           Override servers[0].url in generated code
  --only               One of: openapi | mcp | skill | cli | all (default: all)
  --allow-local        Permit spec URLs on local/private networks (see below)
  --trust-spec-server  Trust servers[0].url even when its host differs from
                        the spec's own host (see "A note on untrusted specs")
  --force              Replace files in the output directory that MCPify did
                        not write (see "Regenerating")
```

### Regenerating

Running again into the same `--out` replaces MCPify's own output and needs no
extra flags. MCPify tracks what it wrote in `.mcpify-manifest.json`, so if a
file it did not write is sitting at one of those paths — the usual way to
discover you meant `--out ./output` rather than `--out .` — it stops and lists
them instead of overwriting. Pass `--force` when replacing them is what you
want. Files MCPify does not manage are left alone either way, and a symlink is
never written through, `--force` included.

### Examples

```bash
# Full generation from a public OpenAPI URL
mcpify https://petstore3.swagger.io/api/v3/openapi.json --name petstore

# Local YAML, only generate the MCP server
mcpify ./my-api.yaml --only mcp --name myapp

# Override base URL (useful when the spec uses a relative servers[].url)
mcpify ./spec.json --base-url https://prod.example.com --name myapp
```

### End to end: YouTube Data API

Real APIs are the point, so here is one from spec to live data. YouTube takes
its key as a query parameter rather than a bearer token:

```bash
mcpify https://api.apis.guru/v2/specs/googleapis.com/youtube/v3/openapi.json \
  --out output --name youtube        # 76 operations across 39 paths

export MCPIFY_API_KEY="AIza..."      # from Google Cloud Console
python3 output/cli/youtube.py youtube-search-list \
  --part snippet --q "openapi" --max-results 3
```

Subcommand names come from the spec's `operationId`, kebab-cased —
`search.list` becomes `youtube-search-list`. Run the CLI with `--help` to
list every operation it generated.

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

## A note on untrusted specs

MCPify turns a spec into source code you then run, so a spec is executable
input. Values taken from the document are escaped before they reach the
generated file ([`utils.py_literal`](src/mcpify/utils.py)); a crafted
parameter name could otherwise have broken out of a string literal and run
arbitrary code. The regression tests for this live in `tests/test_smoke.py`.

Generating from a spec never executes it, but do read what comes out before
running it against anything that matters.

Spec URLs on local or private networks — loopback, RFC 1918, link-local — are
refused, including when a public URL redirects to one. This keeps a spec URL
from being used to reach something only the machine running MCPify can see,
such as `169.254.169.254`. Serving a spec from your own dev server is a normal
thing to do, so pass `--allow-local` for that:

```bash
mcpify http://localhost:8000/openapi.json --allow-local --name myapp
```

The spec's `servers[0].url` is picked by whoever wrote the spec, not by you —
and it is where the generated code sends `MCPIFY_AUTH_TOKEN` /
`MCPIFY_API_KEY`. If that host differs from the host the spec itself was
served from, MCPify refuses to generate by default (re-run with `--base-url`
to point at the host you actually trust, or `--trust-spec-server` if the
mismatch is intentional). **Never run a spec from someone you don't know
without `--base-url` pointed at the API you mean to use.**

## Development

```bash
pip install -e ".[dev]"
pytest
```

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
