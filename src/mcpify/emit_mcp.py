from pathlib import Path
from typing import Optional

from mcpify.openapi import Operation, Spec


def emit(spec: Spec, out_dir: Path, name: str, base_url: Optional[str]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    server_py = out_dir / "server.py"
    server_py.write_text(_render_server(spec, name, base_url), encoding="utf-8")
    (out_dir / "requirements.txt").write_text(
        "mcp[cli]>=1.0.0\nhttpx>=0.27.0\n", encoding="utf-8"
    )
    (out_dir / "README.md").write_text(_render_readme(name, base_url), encoding="utf-8")
    (out_dir / "claude_desktop_config.example.json").write_text(
        _render_claude_config(name, str(server_py.resolve())), encoding="utf-8"
    )


def _render_server(spec: Spec, name: str, base_url: Optional[str]) -> str:
    effective_base = base_url or spec.base_url or ""
    lines = [
        '"""Auto-generated MCP server by MCPify (https://github.com/imai-design/mcpify)."""',
        "import os",
        "from typing import Any, Optional",
        "",
        "import httpx",
        "from mcp.server.fastmcp import FastMCP",
        "",
        f'mcp = FastMCP("{name}")',
        "",
        f'BASE_URL = os.environ.get("MCPIFY_BASE_URL", "{effective_base}")',
        'AUTH_HEADER_NAME = os.environ.get("MCPIFY_AUTH_HEADER", "Authorization")',
        'AUTH_TOKEN = os.environ.get("MCPIFY_AUTH_TOKEN", "")',
        'USER_AGENT = os.environ.get("MCPIFY_USER_AGENT", "MCPify/0.1")',
        'API_KEY = os.environ.get("MCPIFY_API_KEY", "")',
        'API_KEY_PARAM = os.environ.get("MCPIFY_API_KEY_PARAM", "key")',
        "",
        "",
        "def _headers() -> dict:",
        '    h: dict = {"Accept": "application/json", "User-Agent": USER_AGENT}',
        "    if AUTH_TOKEN:",
        '        h[AUTH_HEADER_NAME] = AUTH_TOKEN if AUTH_TOKEN.lower().startswith("bearer ") else f"Bearer {AUTH_TOKEN}"',
        "    return h",
        "",
        "",
        "def _request(method: str, path: str, *, path_params=None, query=None, headers=None, body=None):",
        "    url = BASE_URL.rstrip('/') + path",
        "    if path_params:",
        "        for k, v in path_params.items():",
        "            url = url.replace('{' + k + '}', str(v))",
        "    h = _headers()",
        "    if headers:",
        "        h.update({k: str(v) for k, v in headers.items() if v is not None})",
        "    q = {k: v for k, v in (query or {}).items() if v is not None}",
        "    if API_KEY:",
        "        q = {**q, API_KEY_PARAM: API_KEY}",
        "    with httpx.Client(timeout=60.0) as client:",
        "        resp = client.request(method, url, params=q, headers=h, json=body)",
        "    resp.raise_for_status()",
        "    if not resp.content:",
        "        return {'status_code': resp.status_code}",
        "    ctype = resp.headers.get('content-type', '')",
        "    if 'application/json' in ctype:",
        "        return resp.json()",
        "    return {'status_code': resp.status_code, 'text': resp.text}",
        "",
    ]
    for op in spec.operations:
        lines.append("")
        lines.append(_render_tool(op))
    lines.append("")
    lines.append('if __name__ == "__main__":')
    lines.append("    mcp.run()")
    return "\n".join(lines) + "\n"


def _render_tool(op: Operation) -> str:
    args: list = []
    arg_docs: list = []
    ordered = sorted(op.params, key=lambda x: (not x.required, x.py_name))
    for p in ordered:
        py_t = p.py_type
        if p.required:
            args.append(f"{p.py_name}: {py_t}")
        else:
            args.append(f"{p.py_name}: Optional[{py_t}] = None")
        if p.description:
            arg_docs.append(f"        {p.py_name}: {p.description}")
    if op.has_body:
        if op.body_required:
            args.insert(sum(1 for p in ordered if p.required), "body: dict")
        else:
            args.append("body: Optional[dict] = None")
        arg_docs.append("        body: JSON request body")

    sig = ", ".join(args)
    desc = (op.summary or op.description or f"{op.method} {op.path}").splitlines()[0].strip()
    desc = desc.replace('"""', "'''")

    path_params = [p for p in op.params if p.location == "path"]
    query_params = [p for p in op.params if p.location == "query"]
    header_params = [p for p in op.params if p.location == "header"]

    path_dict = "{" + ", ".join(f'"{p.name}": {p.py_name}' for p in path_params) + "}" if path_params else "None"
    query_dict = "{" + ", ".join(f'"{p.name}": {p.py_name}' for p in query_params) + "}" if query_params else "None"
    header_dict = "{" + ", ".join(f'"{p.name}": {p.py_name}' for p in header_params) + "}" if header_params else "None"
    body_expr = "body" if op.has_body else "None"

    docstring = f'"""{desc}"""' if not arg_docs else f'"""{desc}\n\n    Args:\n' + "\n".join(arg_docs) + '\n    """'

    return "\n".join([
        "@mcp.tool()",
        f"def {op.py_name}({sig}) -> Any:",
        f"    {docstring}",
        f"    return _request("
        f'"{op.method}", "{op.path}", '
        f"path_params={path_dict}, query={query_dict}, headers={header_dict}, body={body_expr})",
    ])


def _render_readme(name: str, base_url: Optional[str]) -> str:
    return f"""# {name} — MCP Server

Auto-generated by [MCPify](https://github.com/imai-design/mcpify).

## Install

```bash
pip install -r requirements.txt
```

## Run

```bash
export MCPIFY_BASE_URL="{base_url or 'https://your-api.example.com'}"
export MCPIFY_AUTH_TOKEN="your-token-here"
python server.py
```

## Connect to Claude Desktop

Copy the snippet from `claude_desktop_config.example.json` into
`~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) and
restart Claude Desktop.
"""


def _render_claude_config(name: str, server_path: str) -> str:
    import json as _json
    return _json.dumps({
        "mcpServers": {
            name: {
                "command": "python",
                "args": [server_path],
                "env": {
                    "MCPIFY_BASE_URL": "https://your-api.example.com",
                    "MCPIFY_AUTH_TOKEN": "your-token-here",
                },
            }
        }
    }, indent=2, ensure_ascii=False) + "\n"
