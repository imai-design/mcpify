import http.client
import ipaddress
import json
import os
import socket
import stat
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

# 小さな仕様書1枚でディスク満杯・OOM・無限ハングを起こせないための上限。
MAX_SPEC_BYTES = int(os.environ.get("MCPIFY_MAX_SPEC_BYTES", 32 * 1024 * 1024))
MAX_SPEC_NODES = 200_000


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


def _resolved_addresses(host: str, fail_closed: bool = True):
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as e:
        if not fail_closed:
            # Best-effort callers (e.g. vetting servers[0].url at generation
            # time) would otherwise reject every spec that uses a
            # placeholder/example host, which is far more common than an
            # actual attack; nothing is being connected to here.
            return []
        # fail-closed: a host we cannot resolve is a host we cannot vet, and
        # letting it through (as before) is how proxy/split-horizon DNS setups
        # smuggled internal hostnames past this guard.
        raise LocalAddressBlocked(
            f"{host} could not be resolved, so it cannot be checked against "
            f"local networks. Pass --allow-local if you meant to reach it."
        ) from e
    return [ipaddress.ip_address(i[4][0]) for i in infos]


def _assert_public(ip) -> None:
    if (ip.is_private or ip.is_loopback or ip.is_link_local
            or ip.is_reserved or ip.is_multicast or ip.is_unspecified):
        raise LocalAddressBlocked(f"connection resolved to {ip} (local/private)")


def _reject_internal(url: str, fail_closed: bool = True) -> None:
    """Refuse URLs that point back into the local or private networks.

    Fetching a spec is a request made on the caller's behalf, so a URL like
    http://169.254.169.254/... or http://10.0.0.5/ reaches things the caller
    may not have meant to expose. Checked per hop, since a public URL can
    redirect inward.

    fail_closed=True (the default, used when a request is actually about to
    be made) treats an unresolvable host as blocked. fail_closed=False is for
    best-effort, no-network-access checks such as vetting servers[0].url at
    generation time, where an unresolvable placeholder host must not abort
    generation.
    """
    host = urllib.parse.urlparse(url).hostname
    if not host:
        return
    for ip in _resolved_addresses(host, fail_closed=fail_closed):
        _assert_public(ip)


# Public alias: cli.py checks the effective base URL (servers[0].url), not
# just the spec's own fetch URL, so this needs a name outside this module.
reject_internal = _reject_internal


class _GuardedRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Apply the same check to every redirect target, not just the first URL."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _reject_internal(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class _PinnedHTTPConnection(http.client.HTTPConnection):
    """Re-check the address actually connected to, not just the resolved one.

    _reject_internal resolves the hostname once before connecting; DNS can
    return a different (internal) address on the real connection attempt
    (DNS rebinding). This is the last line of defense, checked on the live
    socket after TCP/TLS setup.
    """

    def connect(self):
        super().connect()
        _assert_public(ipaddress.ip_address(self.sock.getpeername()[0]))


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def connect(self):
        super().connect()
        _assert_public(ipaddress.ip_address(self.sock.getpeername()[0]))


class _PinnedHTTPHandler(urllib.request.HTTPHandler):
    def http_open(self, req):
        return self.do_open(_PinnedHTTPConnection, req)


class _PinnedHTTPSHandler(urllib.request.HTTPSHandler):
    def https_open(self, req):
        # HTTPSHandler carries its TLS settings in private attributes whose
        # shape changed across versions: 3.12 folded check_hostname into the
        # context and dropped _check_hostname entirely. Forward only what this
        # interpreter actually has, or every https:// spec URL fails with an
        # AttributeError before a connection is ever made.
        kwargs = {"context": self._context}
        check_hostname = getattr(self, "_check_hostname", None)
        if check_hostname is not None:
            kwargs["check_hostname"] = check_hostname
        return self.do_open(_PinnedHTTPSConnection, req, **kwargs)


def _read_capped(fp) -> bytes:
    data = fp.read(MAX_SPEC_BYTES + 1)
    if len(data) > MAX_SPEC_BYTES:
        raise RuntimeError(f"spec exceeds {MAX_SPEC_BYTES} bytes; refusing to load it.")
    return data


def load(target: str, allow_local: bool = False) -> dict:
    """Fetch and parse an OpenAPI document from URL or filesystem path."""
    if target.startswith(("http://", "https://")):
        if allow_local:
            opener = urllib.request.build_opener()
        else:
            _reject_internal(target)
            opener = urllib.request.build_opener(
                _GuardedRedirectHandler(), _PinnedHTTPHandler(), _PinnedHTTPSHandler()
            )
        req = urllib.request.Request(target, headers={"User-Agent": USER_AGENT})
        with opener.open(req, timeout=30) as resp:
            data = _read_capped(resp)
    else:
        path = Path(target).expanduser()
        st = path.stat()  # raises FileNotFoundError for a missing path, as before
        if not stat.S_ISREG(st.st_mode):
            raise RuntimeError(f"{path} is not a regular file (device or FIFO); refusing to read it.")
        if st.st_size > MAX_SPEC_BYTES:
            raise RuntimeError(f"{path} exceeds {MAX_SPEC_BYTES} bytes.")
        with open(path, "rb") as f:
            data = _read_capped(f)
    try:
        return json.loads(data)
    except json.JSONDecodeError:
        return _parse_yaml(data.decode("utf-8"))


def dumps_capped(obj, max_bytes: int = None) -> str:
    """json.dumps, but abort before building an oversized string.

    A YAML alias bomb parses cheaply (shared references) but explodes when
    written back out as a fully-expanded JSON tree. Encoding incrementally
    lets us bail out once the running total crosses the cap instead of
    materializing the whole (potentially gigabyte-scale) string first.
    """
    cap = MAX_SPEC_BYTES if max_bytes is None else max_bytes
    encoder = json.JSONEncoder(ensure_ascii=False, indent=2)
    parts: list = []
    total = 0
    for chunk in encoder.iterencode(obj):
        total += len(chunk.encode("utf-8"))
        if total > cap:
            raise RuntimeError(f"generated openapi.json would exceed {cap} bytes; refusing to write it.")
        parts.append(chunk)
    return "".join(parts)


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
            def __init__(self, stream):
                super().__init__(stream)
                self._node_count = 0

            def compose_node(self, parent, index):
                self._node_count += 1
                if self._node_count > MAX_SPEC_NODES:
                    # Anchors/aliases let a tiny document expand into millions
                    # of nodes once composed (an "alias bomb"); count as we go
                    # rather than after the fact.
                    raise yaml.YAMLError(
                        "spec has too many nodes; refusing to expand it (alias bomb?)"
                    )
                return super().compose_node(parent, index)

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
