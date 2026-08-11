# Changelog

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
