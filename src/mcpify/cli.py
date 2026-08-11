import argparse
import json
import os
import re
import shutil
import sys
import tempfile
import urllib.parse
from pathlib import Path

from mcpify import __version__
from mcpify import openapi, emit_mcp, emit_skill, emit_cli
from mcpify.utils import to_kebab, write_generated

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
MANIFEST_NAME = ".mcpify-manifest.json"


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
    p.add_argument("--force", action="store_true",
                   help="Overwrite files that already exist in the output directory")
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
    except (ValueError, RecursionError) as e:
        # A malformed $ref (circular, or nested deep enough to blow the
        # stack) or a document that fails the boundary type checks in
        # normalize() lands here; report it as a refusal, not a crash.
        detail = str(e) or e.__class__.__name__
        print(f"ERROR: not a usable OpenAPI document: {detail}", file=sys.stderr)
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

    # List every path this run would write before writing anything, so a
    # pre-existing file is judged up front instead of overwritten mid-run.
    planned = _planned_paths(out, name, channels)

    symlinked = [p for p in planned if p.is_symlink()]
    if symlinked:
        # Never follow a pre-existing symlink, --force or not: that is the
        # one thing --force must not be able to opt back into.
        names = ", ".join(str(p) for p in symlinked)
        raise RuntimeError(f"refusing to write through existing symlink(s): {names}")

    # Regenerating into the same --out is the normal way to use a generator,
    # so our own previous output is ours to replace. What must not be silently
    # destroyed is somebody else's file that happens to share a name — the
    # real hazard of pointing --out at "." or "~". The manifest records what
    # we wrote last time, which is exactly the line between those two cases.
    ours = _read_manifest(out)
    foreign = [p for p in planned
               if p.exists() and _rel(p, out) not in ours]
    if foreign and not args.force:
        print("ERROR: these files already exist and were not written by mcpify:",
              file=sys.stderr)
        for p in foreign:
            print(f"  {p}", file=sys.stderr)
        print("Re-run with --force to replace them.", file=sys.stderr)
        return 2

    # Generate every channel into a scratch directory first and only move the
    # results into place once everything has succeeded, so a failure partway
    # through (e.g. a syntax-invalid CLI channel) cannot leave --out with a
    # fresh mcp_server/ next to a stale skills/ from a previous run. The
    # scratch directory lives inside --out: it is known-writable (we just
    # created it) and on the same filesystem, so the moves below stay atomic.
    staging = Path(tempfile.mkdtemp(prefix=".mcpify-staging-", dir=str(out)))
    try:
        if "openapi" in channels:
            write_generated(staging / "openapi.json", openapi.dumps_capped(spec.raw), staging)

        if "mcp" in channels:
            emit_mcp.emit(spec, staging / "mcp_server", name=name, base_url=args.base_url, root=staging)

        if "skill" in channels:
            emit_skill.emit(spec, staging / "skills", name=name, root=staging)

        if "cli" in channels:
            emit_cli.emit(spec, staging / "cli", name=name, base_url=args.base_url, root=staging)

        # Move file by file. Never remove a directory in --out: it may hold
        # files this run knows nothing about, and deleting those to make room
        # would be more destructive than the overwriting this guard exists to
        # prevent. os.replace is atomic per file, which is what matters here.
        written: list = []
        for item in sorted(staging.rglob("*")):
            if item.is_dir():
                continue
            target = out / item.relative_to(staging)
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(str(item), str(target))
            written.append(_rel(target, out))
    finally:
        shutil.rmtree(staging, ignore_errors=True)

    _write_manifest(out, name, written)
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


def _rel(path: Path, out: Path) -> str:
    """Path relative to --out, as the manifest stores it."""
    try:
        return path.relative_to(out).as_posix()
    except ValueError:
        return str(path)


def _read_manifest(out: Path) -> set:
    """Files a previous run into this directory reported writing.

    Absent, unreadable, or malformed all mean the same thing — we cannot
    claim any file here as ours — so they collapse to the empty set and the
    caller falls back to refusing collisions.
    """
    path = out / MANIFEST_NAME
    if path.is_symlink() or not path.is_file():
        return set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return {str(f) for f in data["files"]}
    except (OSError, ValueError, KeyError, TypeError):
        return set()


def _write_manifest(out: Path, name: str, written: list) -> None:
    """Record what this run wrote, so the next one can tell ours from theirs.

    Best-effort: failing to write it costs a --force on the next run, which
    is not worth failing a successful generation over.
    """
    path = out / MANIFEST_NAME
    if path.is_symlink():
        return
    try:
        write_generated(
            path,
            json.dumps({"project": name, "files": sorted(written)},
                       ensure_ascii=False, indent=2) + "\n",
            out,
        )
    except (OSError, RuntimeError):
        pass


def _planned_paths(out: Path, name: str, channels: set) -> list:
    """List every file a run would write, for the pre-write existence check."""
    planned: list = []
    if "openapi" in channels:
        planned.append(out / "openapi.json")
    if "mcp" in channels:
        d = out / "mcp_server"
        planned += [d / "server.py", d / "requirements.txt", d / "README.md",
                    d / "claude_desktop_config.example.json"]
    if "skill" in channels:
        planned.append(out / "skills" / name / "SKILL.md")
    if "cli" in channels:
        d = out / "cli"
        planned += [d / f"{name}.py", d / "README.md"]
    return planned


def _slugify(title: str) -> str:
    return to_kebab(title) or "app"


if __name__ == "__main__":
    sys.exit(main())
