# choreoai-cli

**A Claude-Code-style coding agent harness built on [choreoai](https://github.com/choreo-ai/choreo).**

`choreoai-cli` is an interactive terminal REPL that runs a coding agent in your current
directory using choreoai's `LLMAgent`, tools, budget, and trace — so the harness itself is
budget-bounded and observable.

> **Status: pre-alpha.** This is a minimal but working slice (v0), not a full Claude Code clone.

## Features (v0)

- Interactive REPL (`choreoai-cli`) with `/help`, `/reset`, `/exit`
- Coding tools: `read_file`, `write_file`, `list_dir`, `run_shell`
- Shell commands require confirmation unless `--auto` is set
- Built on choreoai: `LLMAgent` tool loop, `Budget` + `Trace` middleware, typed event stream
- Default model: `claude-sonnet-5` (via choreoai / Anthropic)

## Install

Requires **Python 3.10+**.

```bash
pip install choreoai-cli
```

This installs the PyPI package `choreoai-cli` and its dependency `choreoai` (also from PyPI).

### Install from source

```bash
git clone https://github.com/choreo-ai/choreoai-cli
cd choreoai-cli
pip install -e ".[dev]"
```

### Local choreoai development

PyPI requires a normal version pin (`choreoai>=0.0.1`), not a git URL. For local / offline
development against a checkout of the framework:

```bash
# Install framework from local checkout first (editable)
pip install -e C:\karthik\repos\choreo   # or: pip install -e /path/to/choreo

# Then install the CLI (and optional dev extras)
pip install -e ".[dev]"
```

If `choreoai` is already installed editable, `pip install -e ".[dev]"` will satisfy
`choreoai>=0.0.1` without hitting PyPI for that package.

## Usage

```bash
# Live agent (requires ANTHROPIC_API_KEY)
export ANTHROPIC_API_KEY=sk-ant-...
choreoai-cli

# Skip shell confirmation prompts (use carefully)
choreoai-cli --auto

# Single non-interactive command
choreoai-cli -c "List the files in this directory"

# Custom working directory
choreoai-cli --cwd /path/to/project
```

### REPL commands

| Command  | Action                |
|----------|-------------------------|
| `/help`  | Show help               |
| `/reset` | Clear the event trace   |
| `/exit`  | Quit                    |

Anything else is sent to the coding agent as an instruction.

### Environment

| Variable            | Required | Notes                                      |
|---------------------|----------|--------------------------------------------|
| `ANTHROPIC_API_KEY` | For live | Default model is `claude-sonnet-5`         |

Offline tests inject a fake `BaseChatModel` and do **not** need an API key.

## Tests

```bash
# Prefer editable local choreoai if you have a checkout
pip install -e /path/to/choreo
pip install -e ".[dev]"
pytest
```

Tests are offline: no network and no `ANTHROPIC_API_KEY`.

## How it works

1. Builds a choreoai `LLMAgent` with a coding-assistant system prompt and file/shell tools.
2. Wraps each turn in choreoai `BudgetMiddleware` + `TraceMiddleware` (onion stack).
3. Runs the agent tool loop; prints tool calls, the final answer (rich), budget usage, and a short trace summary.

## License

[MIT](LICENSE) © 2026 Karthik Reddy
