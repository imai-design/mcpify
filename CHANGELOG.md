# Changelog

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
