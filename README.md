# codehealth-mcp

Maintainability scoring for AI coding agents. CodeHealth scores source files
from 1 to 10 (Healthy >= 9, Warning >= 4, Alert < 4), lists code smells with
the function, line range, measured value, threshold and a fix hint, and gates
commits and pull requests on whether touched code got worse. It runs as an
MCP server for Claude Code, Claude Desktop, Codex, Cursor, VS Code and Kiro,
and as a CLI.

It reads about 30 languages through [lizard](https://github.com/terryyin/lizard)
(per-function metrics), adds [tree-sitter](https://tree-sitter.github.io/)
analysis for Python, JavaScript, TypeScript/TSX, Java and Go (nested logic,
complex conditionals, class cohesion, renamed clones), and uses
[PMD](https://pmd.github.io/) when it is installed (copy-paste detection,
Java God Class). See [DESIGN.md](DESIGN.md) for the model.

## Quick start

Requires [uv](https://docs.astral.sh/uv/). Run the server from GitHub:

```sh
uvx --from git+https://github.com/microbrewerGM/codehealth-mcp codehealth-mcp
```

Once the package is on PyPI: `uvx codehealth-mcp`.

Add it to Claude Code for all your projects:

```sh
claude mcp add --transport stdio --scope user codehealth -- \
  uvx --from git+https://github.com/microbrewerGM/codehealth-mcp codehealth-mcp
```

Every other client (Claude Desktop config and MCP Bundle, Codex CLI, Cursor,
VS Code, Kiro IDE and CLI) is covered in [docs/harnesses.md](docs/harnesses.md),
with ready-to-copy files in [examples/](examples).

To make agents use it, paste [examples/AGENTS.md](examples/AGENTS.md) into
your repository's agent instructions: review before and after edits, run the
pre-commit safeguard before every commit.

## MCP tools

| tool | purpose |
|---|---|
| `code_health_score` | file -> score, category, analyzers |
| `code_health_review` | file -> score and findings (smell, function, lines, value, threshold, severity, hint) |
| `pre_commit_code_health_safeguard` | repository -> staged and modified files vs HEAD, quality gate |
| `analyze_change_set` | repository + base ref -> per-file verdict on the branch, quality gate |
| `rules_config_validate` | check `.codehealth/rules.json` |
| `rules_config_list_thresholds` | thresholds and defaults per language |
| `rules_config_set_rule` / `rules_config_set_threshold` | edit `.codehealth/rules.json` |
| `explain_code_health` | the model, a smell, or the score bands |

Results are structured objects (MCP `structuredContent`), with the same JSON
as text for older clients. All paths must be absolute.

## Optional: PMD

PMD needs Java 8+. Install the pinned release (SHA-256 checked) once:

```sh
uvx --from git+https://github.com/microbrewerGM/codehealth-mcp codehealth install-pmd
# or: codehealth install-pmd --dir /some/dir   (then set CODEHEALTH_PMD_HOME)
```

The default location is the per-user data directory
(`~/Library/Application Support/codehealth-mcp/pmd` on macOS,
`$XDG_DATA_HOME/codehealth-mcp/pmd` or `~/.local/share/codehealth-mcp/pmd` on
Linux). Without PMD or Java every tool still works; smells that needed PMD are
listed under `analyzers.unavailable_smells`.

| variable | meaning |
|---|---|
| `CODEHEALTH_PMD_HOME` | PMD `pmd-bin-*` directory (or a directory that holds one); also the `install-pmd` target |
| `CODEHEALTH_NO_PMD=1` | do not use PMD |
| `CODEHEALTH_PMD_TIMEOUT` | seconds per PMD run (default 120) |
| `CODEHEALTH_CACHE_DIR` | PMD cache and scratch copies (default `~/.cache/codehealth`) |
| `JAVA_HOME` | Java runtime for PMD (else `java` on `PATH`) |

## Configuration

Put rule weights and threshold overrides in `.codehealth/rules.json` at the
repository root (the first rule set whose glob matches a file applies):

```json
{"rule_sets": [{"matching_content_path": "tests/**",
                "rules": [{"name": "Large Method", "weight": 0}],
                "thresholds": [{"name": "function_lines_of_code_warning", "value": 120}]}]}
```

A comment `@codehealth(disable:"Complex Method")` or `@codehealth(disable-all)`
right before a function skips function-level smells for that function.

## CLI

```sh
codehealth review path/to/file.py     # score + findings
codehealth score src/                 # scores for a tree
codehealth delta                      # uncommitted changes vs HEAD (exit 1 when the gate fails)
codehealth delta --base main          # branch vs merge base
codehealth serve                      # MCP server on stdio (same as codehealth-mcp)
codehealth install-pmd [--dir DIR]    # optional PMD install
```

## Development

```sh
uv sync
uv run pytest                                   # PMD tests run when PMD + Java are found
CODEHEALTH_NO_PMD=1 uv run pytest               # without PMD (pmd tests skip)
uv run python scripts/dogfood.py                # review this repo through its own MCP server
uv build                                        # sdist + wheel in dist/
scripts/build_mcpb.sh                           # Claude Desktop bundle in dist/
```

`.mcp.json` registers the server from this checkout (`uv run codehealth-mcp`)
for Claude Code. The benchmark against human maintainability ratings is in
[bench/](bench/README.md).

## Influences and acknowledgements

CodeHealth is an independent implementation. No third-party product code or
binaries were used. It is shaped by the following public work:

- **CodeScene** public Code Health documentation
  (https://codescene.io/docs/guides/technical/code-health.html) and its
  published default rule thresholds, which our default threshold names and
  values (`src/codehealth/thresholds.py`, rows marked "published default")
  follow. The score formula, weights and severity model are our own.
- **Adam Tornhill's writing**: https://adamtornhill.substack.com and his
  books on behavioral code analysis (*Your Code as a Crime Scene*, *Software
  Design X-Rays*), which shaped the agent guidance (delta-first gates, small
  refactoring loops).
- **Research papers**:
  - Adam Tornhill, Markus Borg. "Code Red: The Business Impact of Code
    Quality -- A Quantitative Study of 39 Proprietary Production Codebases".
    TechDebt 2022. https://arxiv.org/abs/2203.04374
  - Markus Borg, Ilyana Pruvost, Enys Mones, Adam Tornhill. "Increasing, not
    Diminishing: Investigating the Returns of Highly Maintainable Code".
    TechDebt 2024, DOI 10.1145/3644384.3644471. https://arxiv.org/abs/2401.13407
  - Markus Borg, Marwa Ezzouhri, Adam Tornhill. "Ghost Echoes Revealed:
    Benchmarking Maintainability Metrics and Machine Learning Predictions
    Against Human Assessments". ICSME 2024 industry track, pp. 678-688,
    DOI 10.1109/ICSME58944.2024.00072. https://arxiv.org/abs/2408.10754
  - Adam Tornhill, Markus Borg, Nadim Hagatulah, Emma Söderberg. "ACE:
    Automated Technical Debt Remediation with Validated Large Language Model
    Refactorings". FSE Companion '25 (AI-IDE workshop), DOI
    10.1145/3696630.3730565. https://arxiv.org/abs/2507.03536
- **lizard** (MIT, Terry Yin and contributors): per-function metrics.
- **PMD** (BSD-style licence): CPD copy-paste detection and Java design rules.
- **tree-sitter** (MIT) and **tree-sitter-language-pack** (MIT OR Apache-2.0): parsing.
- **Datasets** used by the benchmark (not redistributed; see
  [bench/README.md](bench/README.md)):
  - Markus Schnappinger, Arnaud Fietzke, Alexander Pretschner. "A Software
    Maintainability Dataset", DOI 10.6084/m9.figshare.12801215.v3, CC BY 4.0.
  - Ghost Echoes replication package, Zenodo 12548630
    (DOI 10.5281/zenodo.12548630), CC BY 4.0.

Licences of the runtime dependencies: [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

## Licence

MIT, see [LICENSE](LICENSE).
