# Changelog

## 0.1.3 — 2026-08-12

Robustness. The previous two releases stopped a hostile spec from doing harm;
this one stops an ordinary spec from producing quietly broken output.

### Fixed

- **Generated code is verified before it is written.** Every `.py` channel is
  compiled in memory first, so a spec that would produce invalid Python fails
  the run instead of leaving a file that only breaks when you try to use it.
- **Colliding operation and parameter names are made unique.** `getUser` and
  `get_user` both normalize to `get_user`; previously the second silently won,
  so a tool named `get_user` could call an entirely different endpoint. Names
  are now uniquified once, and all four channels agree on them.
- **Reserved words and awkward names no longer break generation.** A parameter
  named `from`, or one that normalizes to nothing (e.g. non-Latin names), used
  to produce a `SyntaxError` or a duplicate argument.
- **Local `$ref` parameters are resolved.** They were passed through unresolved,
  which dropped required path parameters and left `{id}` literal in the URL.
- **OpenAPI 3.1 type arrays** (`"type": ["string", "null"]`) are understood.
- **Non-string scalars are coerced at the boundary**, so a YAML `summary` that
  parses as a number no longer aborts the run.
- **Duplicate keys are rejected** in both JSON and YAML. A `servers:` appended
  at the end of a long document used to silently override the real one.
- **An HTML response is diagnosed as such** — a login page or bot check no
  longer surfaces as a confusing YAML or Unicode error.
- **Scheme handling is correct**: `HTTPS://` (uppercase) is a URL, unsupported
  schemes are rejected by name, and Windows drive letters stay local paths.

### Changed

- Output is generated into a scratch directory and moved into place only once
  every channel has succeeded, so a failure cannot leave a half-updated tree.
- MCPify now records what it wrote in `.mcpify-manifest.json`. Regenerating
  into the same `--out` works exactly as before; a colliding file that MCPify
  did not write is refused instead, and `--force` overrides that. Files MCPify
  does not manage are never removed, and a symlink is never written through —
  `--force` included.

## 0.1.2 — 2026-08-12

### Security

0.1.1 stopped a hostile spec from injecting into what MCPify *writes*. This
release covers what the generated code and the generator then *do*:

- **Credentials stay where you pointed them.** Generated clients now refuse a
  URL that leaves the configured base URL (including `user@host` forms), and
  refuse to send `MCPIFY_AUTH_TOKEN` / `MCPIFY_API_KEY` over plain HTTP.
  MCPify itself now refuses, by default, a spec whose `servers[0].url` host
  differs from the host the spec was served from — that host is where your
  credentials would go. Pass `--base-url` to choose the destination, or
  `--trust-spec-server` when the mismatch is intentional.
- **API keys no longer leak into error output.** Generated clients redact
  secret query parameters from error messages, so a 4xx no longer prints your
  key into a terminal, a CI log, or an agent transcript.
- **Generated files never follow a symlink.** All output is written with
  `O_NOFOLLOW` and checked to stay inside `--out`, so a symlink planted in the
  output directory can no longer redirect a write onto an existing file. The
  generated CLI is now `0755` and the Claude Desktop config example `0600`.
- **The local-network guard is harder to slip past.** An unresolvable spec host
  is now blocked rather than let through, and the address actually connected to
  is re-checked on the live socket, closing a DNS-rebinding window.
- **Malicious specs cannot exhaust the machine.** Spec size is capped
  (`MCPIFY_MAX_SPEC_BYTES`, default 32 MiB), non-regular files such as FIFOs are
  refused, YAML alias bombs are stopped by a node-count limit, and
  `openapi.json` is size-checked while being encoded.

### Fixed

- Generated `requirements.txt` now pins `mcp[cli]>=1.0.0,<2`; the generated
  server imports `mcp.server.fastmcp`, which does not exist in mcp 2.x.
- Guards that stop a run now report `ERROR: ...` and exit 2 instead of raising
  a traceback, so a refusal reads as a refusal rather than a crash.

## 0.1.1 — 2026-08-12

### Security

An OpenAPI document is untrusted input, but earlier versions interpolated
spec-derived strings into generated output without escaping them for the
destination format. A crafted spec fed to `mcpify` could produce output that
attacks whoever runs or reads it:

- **Generated Claude Code Skill (`SKILL.md`).** `info.title` and `tags` could
  break out of the YAML frontmatter and inject keys such as `allowed-tools`,
  and operation/parameter descriptions could inject headings, code fences, and
  agent-directed instructions into the body. A skill is a document an agent
  follows, so this was a prompt-injection channel.
- **Generated MCP server / CLI source.** A hostile `--name`, and `title`/`tags`
  in a few spots, were embedded into Python source without going through the
  literal helper, allowing code execution when the generated file was imported
  or run.
- **Credential destination.** A path key beginning with `@`, or a hostile
  `servers[0].url`, could redirect where a generated client sends its
  `MCPIFY_AUTH_TOKEN` / `MCPIFY_API_KEY`, and the generated README hid the real
  destination behind a placeholder.

**Fixes:** all spec-derived text is now neutralized for its destination
(`utils.one_line()` / `utils.yaml_scalar()`); unsafe path keys are rejected in
`normalize()`; `--name` is validated and every source interpolation goes
through `py_literal`; the effective base URL is surfaced in the run summary and
generated READMEs; `python -m mcpify` now propagates its exit code. Added
regression tests covering each case.

**Please upgrade from 0.1.0.**

## 0.1.0

Initial release — one command turns an OpenAPI document into an OpenAPI spec,
an MCP server, a Claude Code Skill, and a CLI.
