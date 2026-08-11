import argparse
import json
import re
import sys
import urllib.parse
from pathlib import Path

from mcpify import __version__
from mcpify import openapi, emit_mcp, emit_skill, emit_cli
from mcpify.utils import to_kebab, write_generated

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


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
    p.add_argument("--trust-spec-server", action="store_true",
                   help=("Trust servers[0].url even when its host differs from the spec's "
                         "own host (default: refuse, since that host receives your credentials)"))
    p.add_argument("--version", action="version", version=f"mcpify {__version__}")
    return p


def main(argv: list = None) -> int:
    """Run the generator, reporting refusals as errors rather than crashes.

    The guards below (symlinked output, oversized specs, blocked addresses)
    raise to stop the work. Letting those reach the user as a traceback reads
    like MCPify broke, when in fact it refused on purpose — so translate them
    into the same `ERROR: ...` / exit 2 shape the argument checks already use.
    """
    try:
        return _run(argv)
    except openapi.LocalAddressBlocked as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    except FileNotFoundError as e:
        print(f"ERROR: spec not found: {e.filename}", file=sys.stderr)
        return 2
    except RuntimeError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2


def _run(argv: list = None) -> int:
    args = build_parser().parse_args(argv)

    raw = openapi.load(args.target, allow_local=args.allow_local)
    spec = openapi.normalize(raw)
    if not spec.operations:
        print("ERROR: no operations found in the OpenAPI document.", file=sys.stderr)
        return 2

    name = to_kebab(args.name) if args.name else _slugify(spec.title)
    if not _SLUG_RE.match(name):
        print(f"ERROR: --name must be a slug like 'petstore' (got {args.name!r})",
              file=sys.stderr)
        return 2

    effective_base = args.base_url or spec.base_url or ""

    # The spec's own author picks servers[0].url, which is where your
    # MCPIFY_AUTH_TOKEN / MCPIFY_API_KEY end up going. If that host doesn't
    # match the host the spec itself was served from, refuse by default.
    if args.base_url is None and not args.trust_spec_server:
        spec_host = urllib.parse.urlparse(args.target).hostname
        srv_host = urllib.parse.urlparse(spec.base_url).hostname
        if spec_host and srv_host and spec_host != srv_host:
            print(f"ERROR: the spec served from {spec_host} points servers[0].url at {srv_host}. "
                  f"Your credentials would be sent there. Re-run with --base-url <url>, "
                  f"or --trust-spec-server if that is intended.", file=sys.stderr)
            return 2

    # servers[0].url is attacker-controlled the same way the spec's fetch URL
    # is, so it needs the same local/private-network check.
    if effective_base and not args.allow_local:
        try:
            openapi.reject_internal(effective_base, fail_closed=False)
        except openapi.LocalAddressBlocked as e:
            print(f"ERROR: the spec's servers[0].url is not usable: {e}", file=sys.stderr)
            return 2

    out = Path(args.out).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)

    channels = {"openapi", "mcp", "skill", "cli"} if args.only == "all" else {args.only}

    if "openapi" in channels:
        write_generated(out / "openapi.json", openapi.dumps_capped(spec.raw), out)

    if "mcp" in channels:
        emit_mcp.emit(spec, out / "mcp_server", name=name, base_url=args.base_url, root=out)

    if "skill" in channels:
        emit_skill.emit(spec, out / "skills", name=name, root=out)

    if "cli" in channels:
        emit_cli.emit(spec, out / "cli", name=name, base_url=args.base_url, root=out)

    summary = {
        "project": name,
        "title": spec.title,
        "version": spec.version,
        "base_url": effective_base,
        "operations": len(spec.operations),
        "channels": sorted(channels),
        "out": str(out),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def _slugify(title: str) -> str:
    return to_kebab(title) or "app"


if __name__ == "__main__":
    sys.exit(main())
