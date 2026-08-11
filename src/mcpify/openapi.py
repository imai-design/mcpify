import ipaddress
import json
import os
import socket
import sys
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from mcpify.utils import py_identifier, schema_to_py_type

HTTP_METHODS = ("get", "post", "put", "patch", "delete")
USER_AGENT = os.environ.get("MCPIFY_USER_AGENT", "MCPify/0.1")
_BAD_PATH_CHARS = "@\\ \t\n\r"


@dataclass
class Param:
    name: str
    py_name: str
    location: str  # path | query | header | body
    py_type: str
    required: bool
    description: str = ""


@dataclass
class Operation:
    op_id: str
    py_name: str
    method: str
    path: str
    summary: str = ""
    description: str = ""
    tags: list = field(default_factory=list)
    params: list = field(default_factory=list)
    has_body: bool = False
    body_required: bool = False


@dataclass
class Spec:
    title: str
    version: str
    base_url: str
    operations: list = field(default_factory=list)
    raw: dict = field(default_factory=dict)


class LocalAddressBlocked(RuntimeError):
    """A spec URL resolved to an address on the machine's own networks."""


def _resolved_addresses(host: str):
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return []  # unresolvable; let the request fail on its own terms
    return [ipaddress.ip_address(i[4][0]) for i in infos]


def _reject_internal(url: str) -> None:
    """Refuse URLs that point back into the local or private networks.

    Fetching a spec is a request made on the caller's behalf, so a URL like
    http://169.254.169.254/... or http://10.0.0.5/ reaches things the caller
    may not have meant to expose. Checked per hop, since a public URL can
    redirect inward.
    """
    host = urllib.parse.urlparse(url).hostname
    if not host:
        return
    for ip in _resolved_addresses(host):
        if (ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_reserved or ip.is_multicast or ip.is_unspecified):
            raise LocalAddressBlocked(
                f"{url} resolves to {ip}, which is on a local or private network. "
                f"Pass --allow-local if that is what you meant "
                f"(e.g. a spec served by your own dev server)."
            )


class _GuardedRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Apply the same check to every redirect target, not just the first URL."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _reject_internal(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def load(target: str, allow_local: bool = False) -> dict:
    """Fetch and parse an OpenAPI document from URL or filesystem path."""
    if target.startswith(("http://", "https://")):
        opener = urllib.request.build_opener()
        if not allow_local:
            _reject_internal(target)
            opener = urllib.request.build_opener(_GuardedRedirectHandler())
        req = urllib.request.Request(target, headers={"User-Agent": USER_AGENT})
        with opener.open(req, timeout=30) as resp:
            data = resp.read()
    else:
        data = Path(target).expanduser().read_bytes()
    try:
        return json.loads(data)
    except json.JSONDecodeError:
        return _parse_yaml(data.decode("utf-8"))


def _parse_yaml(text: str) -> dict:
    try:
        import yaml  # type: ignore
    except ImportError as e:
        raise RuntimeError(
            "YAML OpenAPI detected but PyYAML is not installed. "
            "Install with: pip install pyyaml"
        ) from e
    return yaml.load(text, Loader=_spec_loader(yaml))


def _spec_loader(yaml):
    """A SafeLoader that leaves timestamps as strings.

    YAML 1.1 resolves things like `2015-02-22T20:00:45Z` into datetime
    objects. The document is written back out as JSON, and datetime is not
    JSON-serializable, so a spec containing a single date would abort
    generation. Everything else keeps its native type.
    """
    global _SPEC_LOADER
    if _SPEC_LOADER is None:
        class SpecLoader(yaml.SafeLoader):
            pass

        SpecLoader.yaml_implicit_resolvers = {
            ch: [(tag, regexp) for tag, regexp in resolvers
                 if tag != "tag:yaml.org,2002:timestamp"]
            for ch, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
        }
        _SPEC_LOADER = SpecLoader
    return _SPEC_LOADER


_SPEC_LOADER = None


def normalize(raw: dict) -> Spec:
    info = raw.get("info") or {}
    title = info.get("title") or "Untitled API"
    version = info.get("version") or "0.0.0"
    servers = raw.get("servers") or []
    base_url = servers[0]["url"] if servers and isinstance(servers[0], dict) else ""

    operations: list = []
    paths = raw.get("paths") or {}
    for path, path_item in paths.items():
        if not isinstance(path_item, dict):
            continue
        if not isinstance(path, str) or not path.startswith("/") or path.startswith("//"):
            print(f"warning: skipping path key {path!r} (must start with a single '/')",
                  file=sys.stderr)
            continue
        if any(c in path for c in _BAD_PATH_CHARS):
            print(f"warning: skipping path key {path!r} (unsafe characters)", file=sys.stderr)
            continue
        path_level_params = path_item.get("parameters") or []
        for method in HTTP_METHODS:
            op = path_item.get(method)
            if not isinstance(op, dict):
                continue
            operations.append(_build_op(method, path, op, path_level_params))
    return Spec(title=title, version=version, base_url=base_url,
                operations=operations, raw=raw)


def _build_op(method: str, path: str, op: dict, path_params: list) -> Operation:
    op_id = op.get("operationId") or f"{method}_{path}"
    py_name = py_identifier(op_id)

    merged_params: list = []
    seen: set = set()
    for p in list(path_params) + list(op.get("parameters") or []):
        if not isinstance(p, dict):
            continue
        key = (p.get("name"), p.get("in"))
        if key in seen:
            continue
        seen.add(key)
        schema = p.get("schema") or {}
        merged_params.append(Param(
            name=p.get("name", "param"),
            py_name=py_identifier(p.get("name", "param")),
            location=p.get("in", "query"),
            py_type=schema_to_py_type(schema),
            required=bool(p.get("required") or p.get("in") == "path"),
            description=p.get("description") or "",
        ))

    request_body = op.get("requestBody")
    has_body = isinstance(request_body, dict) and bool(request_body.get("content"))
    body_required = has_body and bool(request_body.get("required"))

    return Operation(
        op_id=op_id,
        py_name=py_name,
        method=method.upper(),
        path=path,
        summary=op.get("summary") or "",
        description=op.get("description") or "",
        tags=list(op.get("tags") or []),
        params=merged_params,
        has_body=has_body,
        body_required=body_required,
    )
