import argparse
import json
import sys
from pathlib import Path

from mcpify import __version__
from mcpify import openapi, emit_mcp, emit_skill, emit_cli


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="mcpify",
        description=("One command, four channels — turn any existing app into "
                     "OpenAPI + MCP server + Claude Code Skill + CLI."),
    )
    p.add_argument("target",
                   help="OpenAPI document: URL (http/https) or local path (json/yaml)")
    p.add_argument("--out", "-o", default="./output",
                   help="Output directory (default: ./output)")
    p.add_argument("--name", "-n", default=None,
                   help="Project slug (default: derived from OpenAPI title)")
    p.add_argument("--base-url", default=None,
                   help="Override servers[0].url in generated code")
    p.add_argument("--only",
                   choices=["openapi", "mcp", "skill", "cli", "all"],
                   default="all",
                   help="Emit only the chosen channel (default: all)")
    p.add_argument("--allow-local", action="store_true",
                   help="Allow spec URLs on local/private networks (e.g. localhost dev servers)")
    p.add_argument("--version", action="version", version=f"mcpify {__version__}")
    return p


def main(argv: list = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        raw = openapi.load(args.target, allow_local=args.allow_local)
    except openapi.LocalAddressBlocked as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    spec = openapi.normalize(raw)
    if not spec.operations:
        print("ERROR: no operations found in the OpenAPI document.", file=sys.stderr)
        return 2

    name = args.name or _slugify(spec.title)
    out = Path(args.out).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)

    channels = {"openapi", "mcp", "skill", "cli"} if args.only == "all" else {args.only}

    if "openapi" in channels:
        (out / "openapi.json").write_text(
            json.dumps(spec.raw, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    if "mcp" in channels:
        emit_mcp.emit(spec, out / "mcp_server", name=name, base_url=args.base_url)

    if "skill" in channels:
        emit_skill.emit(spec, out / "skills", name=name)

    if "cli" in channels:
        emit_cli.emit(spec, out / "cli", name=name, base_url=args.base_url)

    summary = {
        "project": name,
        "title": spec.title,
        "version": spec.version,
        "operations": len(spec.operations),
        "channels": sorted(channels),
        "out": str(out),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def _slugify(title: str) -> str:
    from mcpify.utils import to_kebab
    return to_kebab(title) or "app"


if __name__ == "__main__":
    sys.exit(main())
