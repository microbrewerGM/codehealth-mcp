## Code Health (codehealth MCP server)

This repository uses the `codehealth` MCP server to keep code maintainable.
Pass absolute paths to every tool.

- Before editing a source file, call `code_health_review` on it. Note its
  score and findings so you do not make them worse.
- After editing, call `code_health_review` again. The score must not drop and
  no new smell may appear in a function you touched. Fix new findings with
  small refactorings (extract function, flatten nesting, simplify
  conditionals), not by disabling rules or raising thresholds.
- Before every commit, call `pre_commit_code_health_safeguard` with the
  repository root. Do not commit while `quality_gate` is `failed`; fix the
  files listed as `degraded` first, or ask a human to accept the risk.
- Before opening a pull request, call `analyze_change_set` with the base
  branch (for example `main`).
- Use `explain_code_health` with a smell name when a finding is unclear.
- Aim for a score of 9.5 or higher on files you edit autonomously.
