from pathlib import Path
from typing import Optional

from mcpify.openapi import Spec
from mcpify.utils import one_line, py_literal, to_kebab


def emit(spec: Spec, out_dir: Path, name: str, base_url: Optional[str]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    effective_base = base_url or spec.base_url or ""
    slug = to_kebab(name)
    (out_dir / f"{slug}.py").write_text(_render(spec, name, base_url), encoding="utf-8")
    (out_dir / "README.md").write_text(_render_readme(slug, effective_base), encoding="utf-8")


def _render(spec: Spec, name: str, base_url: Optional[str]) -> str:
    effective_base = base_url or spec.base_url or ""
    head = '#!/usr/bin/env python3\n"""Auto-generated CLI by MCPify."""\n' \
           "import argparse\n" \
           "import json\n" \
           "import os\n" \
           "import sys\n" \
           "import urllib.request\n" \
           "import urllib.error\n" \
           "import urllib.parse\n\n" \
           f'BASE_URL = os.environ.get("MCPIFY_BASE_URL", {py_literal(effective_base)})\n' \
           'AUTH_HEADER_NAME = os.environ.get("MCPIFY_AUTH_HEADER", "Authorization")\n' \
           'AUTH_TOKEN = os.environ.get("MCPIFY_AUTH_TOKEN", "")\n' \
           'USER_AGENT = os.environ.get("MCPIFY_USER_AGENT", "MCPify/0.1")\n' \
           'API_KEY = os.environ.get("MCPIFY_API_KEY", "")\n' \
           'API_KEY_PARAM = os.environ.get("MCPIFY_API_KEY_PARAM", "key")\n\n' \
           "\n" \
           "def _request(method, path, path_params=None, query=None, body=None):\n" \
           "    url = BASE_URL.rstrip('/') + path\n" \
           "    if path_params:\n" \
           "        for k, v in path_params.items():\n" \
           "            url = url.replace('{' + k + '}', urllib.parse.quote(str(v)))\n" \
           "    q = {k: v for k, v in (query or {}).items() if v is not None}\n" \
           "    if API_KEY:\n" \
           "        q = {**q, API_KEY_PARAM: API_KEY}\n" \
           "    if q:\n" \
           "        url = url + ('&' if '?' in url else '?') + urllib.parse.urlencode(q)\n" \
           "    headers = {'Accept': 'application/json', 'User-Agent': USER_AGENT}\n" \
           "    if AUTH_TOKEN:\n" \
           "        headers[AUTH_HEADER_NAME] = (\n" \
           "            AUTH_TOKEN if AUTH_TOKEN.lower().startswith('bearer ') else f'Bearer {AUTH_TOKEN}'\n" \
           "        )\n" \
           "    data = None\n" \
           "    if body is not None:\n" \
           "        data = json.dumps(body).encode('utf-8')\n" \
           "        headers['Content-Type'] = 'application/json'\n" \
           "    req = urllib.request.Request(url, data=data, headers=headers, method=method)\n" \
           "    try:\n" \
           "        with urllib.request.urlopen(req, timeout=60) as r:\n" \
           "            text = r.read().decode('utf-8') if r.length != 0 else ''\n" \
           "    except urllib.error.HTTPError as e:\n" \
           "        detail = e.read().decode('utf-8', 'replace').strip()\n" \
           "        sys.stderr.write(f'HTTP {e.code} {e.reason}  {method} {url}\\n')\n" \
           "        if detail:\n" \
           "            sys.stderr.write(detail[:800] + ('...' if len(detail) > 800 else '') + '\\n')\n" \
           "        if e.code in (401, 403):\n" \
           "            sys.stderr.write(\n" \
           "                'Hint: this endpoint needs credentials. Set MCPIFY_AUTH_TOKEN for a\\n'\n" \
           "                'bearer token, or MCPIFY_API_KEY if the API takes a key as a query\\n'\n" \
           "                'parameter (Google APIs do; override the name with MCPIFY_API_KEY_PARAM).\\n')\n" \
           "        raise SystemExit(1)\n" \
           "    except urllib.error.URLError as e:\n" \
           "        sys.stderr.write(f'Could not reach {url}: {e.reason}\\n')\n" \
           "        raise SystemExit(1)\n" \
           "    try:\n" \
           "        return json.loads(text) if text else {'status': 'ok'}\n" \
           "    except json.JSONDecodeError:\n" \
           "        return {'text': text}\n\n"

    main_parts = [
        "\n",
        "def main():\n",
        f'    parser = argparse.ArgumentParser(prog={py_literal(name)}, description="Auto-generated CLI by MCPify.")\n',
        '    sub = parser.add_subparsers(dest="cmd", required=True)\n',
    ]
    handlers: list = []
    for op in spec.operations:
        cmd_name = to_kebab(op.py_name)
        main_parts.append(f'    p = sub.add_parser({py_literal(cmd_name)}, help={py_literal(one_line(op.summary) or op.method + " " + op.path)})\n')
        for prm in op.params:
            arg_kwargs: list = []
            if not prm.required:
                arg_kwargs.append("default=None")
            arg_kwargs.append(f'help={py_literal(one_line(prm.description) or prm.location)}')
            opt_flag = f'"--{to_kebab(prm.py_name)}"'
            main_parts.append(f'    p.add_argument({opt_flag}, {"required=True, " if prm.required else ""}{", ".join(arg_kwargs)})\n')
        if op.has_body:
            main_parts.append(f'    p.add_argument("--body", {"required=True, " if op.body_required else ""}help="JSON body string or @file.json")\n')
        main_parts.append(f'    p.set_defaults(_handler={py_literal(op.py_name)})\n')

        handler = [
            f"def _handle_{op.py_name}(ns):\n",
        ]
        path_pairs = ", ".join(f'{py_literal(p.name)}: ns.{p.py_name}' for p in op.params if p.location == "path")
        query_pairs = ", ".join(f'{py_literal(p.name)}: ns.{p.py_name}' for p in op.params if p.location == "query")
        handler.append(f"    path_params = {{{path_pairs}}}\n")
        handler.append(f"    query = {{{query_pairs}}}\n")
        if op.has_body:
            handler.append("    raw = ns.body\n")
            handler.append("    if raw and raw.startswith('@'):\n")
            handler.append("        with open(raw[1:], 'r', encoding='utf-8') as f:\n")
            handler.append("            raw = f.read()\n")
            handler.append("    body = json.loads(raw) if raw else None\n")
        else:
            handler.append("    body = None\n")
        handler.append(f"    return _request({py_literal(op.method)}, {py_literal(op.path)}, path_params=path_params, query=query, body=body)\n\n")
        handlers.append("".join(handler))

    main_parts.append("    args = parser.parse_args()\n")
    main_parts.append("    handler = globals()['_handle_' + args._handler]\n")
    main_parts.append("    result = handler(args)\n")
    main_parts.append("    print(json.dumps(result, ensure_ascii=False, indent=2))\n")
    main_parts.append("\n\n")
    main_parts.append('if __name__ == "__main__":\n')
    main_parts.append("    main()\n")

    return head + "".join(handlers) + "".join(main_parts)


def _render_readme(slug: str, base_url) -> str:
    return f"""# {slug} — CLI

Auto-generated by [MCPify](https://github.com/imai-design/mcpify).

## Usage

```bash
export MCPIFY_BASE_URL="{base_url or 'https://your-api.example.com'}"
export MCPIFY_AUTH_TOKEN="your-token-here"
python {slug}.py --help
```
"""
