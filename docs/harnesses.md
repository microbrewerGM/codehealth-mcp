# Installing CodeHealth in MCP clients

CodeHealth is a stdio MCP server. Every client below starts it with one
command:

| source | command |
|---|---|
| GitHub (now) | `uvx --from git+https://github.com/microbrewerGM/codehealth-mcp codehealth-mcp` |
| GitHub, pinned | `uvx --from git+https://github.com/microbrewerGM/codehealth-mcp@v0.1.0 codehealth-mcp` |
| PyPI (once published) | `uvx codehealth-mcp` |

You need [uv](https://docs.astral.sh/uv/) on `PATH`. The first start
downloads and caches the package, so give clients a generous startup timeout.
To use the PyPI form, replace `"args": ["--from", "git+https://...", "codehealth-mcp"]`
with `"args": ["codehealth-mcp"]` in the examples.

Optional PMD support (copy-paste detection for many languages, Java God
Class): install Java 8+ and run
`uvx --from git+https://github.com/microbrewerGM/codehealth-mcp codehealth install-pmd`
once. The server finds PMD in the per-user data directory, or wherever
`CODEHEALTH_PMD_HOME` points. Without PMD the server still works and lists the
smells it could not measure under `analyzers.unavailable_smells`.

GUI apps (Claude Desktop, Cursor, VS Code, Kiro) may not see your shell
`PATH`. If the server fails to start with "command not found", use the
absolute path of `uvx` (`which uvx`) as the command.

Example files: [`examples/`](../examples).

## Claude Code

Docs: https://code.claude.com/docs/en/mcp

```sh
# just you, every project
claude mcp add --transport stdio --scope user codehealth -- \
  uvx --from git+https://github.com/microbrewerGM/codehealth-mcp codehealth-mcp

# shared with the team through .mcp.json in the project root
claude mcp add --transport stdio --scope project codehealth -- \
  uvx --from git+https://github.com/microbrewerGM/codehealth-mcp codehealth-mcp
```

Scopes: `local` (default; this project, only you, stored in `~/.claude.json`),
`project` (`.mcp.json` in the repository, committed), `user` (all your
projects, `~/.claude.json`). Everything after `--` is the server command.
A `.mcp.json` file: [`examples/claude-code/mcp.json`](../examples/claude-code/mcp.json).

## Claude Desktop

Docs: https://modelcontextprotocol.io/docs/develop/connect-local-servers

Option 1, config file. Merge
[`examples/claude-desktop/claude_desktop_config.json`](../examples/claude-desktop/claude_desktop_config.json)
into:

- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Windows: `%APPDATA%\Claude\claude_desktop_config.json`

Restart Claude Desktop afterwards.

Option 2, MCP Bundle (`.mcpb`). Build it with the official MCPB CLI
(needs Node.js for `npx`):

```sh
scripts/build_mcpb.sh        # writes dist/codehealth-mcp-<version>.mcpb
```

Open the `.mcpb` file with Claude Desktop to install it. The bundle uses
the `uv` server type (`manifest_version` 0.4,
https://github.com/modelcontextprotocol/mcpb/blob/main/MANIFEST.md): it
ships `pyproject.toml`, `uv.lock` and `src/`, and the host installs the
dependencies with uv. Its optional "PMD directory" setting maps to
`CODEHEALTH_PMD_HOME`.

## OpenAI Codex CLI

Docs: https://developers.openai.com/codex/mcp

Append [`examples/codex/config.toml`](../examples/codex/config.toml) to
`~/.codex/config.toml` (or `.codex/config.toml` in a trusted project), or run:

```sh
codex mcp add codehealth -- uvx --from git+https://github.com/microbrewerGM/codehealth-mcp codehealth-mcp
```

```toml
[mcp_servers.codehealth]
command = "uvx"
args = ["--from", "git+https://github.com/microbrewerGM/codehealth-mcp", "codehealth-mcp"]
startup_timeout_sec = 60
tool_timeout_sec = 300
```

## Cursor

Docs: https://cursor.com/docs/context/mcp

Project: `.cursor/mcp.json`; all projects: `~/.cursor/mcp.json`. Content:
[`examples/cursor/mcp.json`](../examples/cursor/mcp.json) (top-level key
`mcpServers`).

## VS Code (GitHub Copilot agent mode)

Docs: https://code.visualstudio.com/docs/agents/reference/mcp-configuration

Workspace: `.vscode/mcp.json` with
[`examples/vscode/mcp.json`](../examples/vscode/mcp.json). Note the top-level
key is `servers` (not `mcpServers`) and `"type": "stdio"` is required. For
your user profile, run **MCP: Open User Configuration**, or:

```sh
code --add-mcp '{"name":"codehealth","type":"stdio","command":"uvx","args":["--from","git+https://github.com/microbrewerGM/codehealth-mcp","codehealth-mcp"]}'
```

## Kiro IDE and Kiro CLI

Docs: https://kiro.dev/docs/mcp/configuration/

Both use the same files: workspace `.kiro/settings/mcp.json` and user
`~/.kiro/settings/mcp.json` (workspace wins for a server with the same name).
Content: [`examples/kiro/mcp.json`](../examples/kiro/mcp.json). Its
`autoApprove` list holds the read-only tools only; remove it to confirm every
call.

Kiro CLI can also add the server for you
(https://kiro.dev/docs/reference/cli-commands/):

```sh
kiro-cli mcp add --name codehealth --scope global \
  --command "uvx --from git+https://github.com/microbrewerGM/codehealth-mcp codehealth-mcp"
```

If your Kiro CLI version does not split `--command` into arguments, edit
`~/.kiro/settings/mcp.json` with the example file instead.

## Agent instructions

Paste [`examples/AGENTS.md`](../examples/AGENTS.md) into your repository's
`AGENTS.md`, `CLAUDE.md` or `.kiro/steering/` file so agents call
`code_health_review` before and after edits and
`pre_commit_code_health_safeguard` before commits.
