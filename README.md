# choreo-cli

**A Claude-Code-style coding agent harness built on [choreoai](https://github.com/choreo-ai/choreo).**

`choreo-cli` is an interactive terminal REPL that runs a coding agent in your current
directory using choreoai's `LLMAgent`, tools, budget, and trace — so the harness itself is
budget-bounded and observable.

> **Status: pre-alpha.** This is a minimal but working slice (v0), not a full Claude Code clone.

## Features (v0)

- Interactive REPL (`choreo-cli`) with `/help`, `/reset`, `/exit`
- Coding tools: `read_file`, `write_file`, `list_dir`, `run_shell`
- Shell commands require confirmation unless `--auto` is set
- Built on choreoai: `LLMAgent` tool loop, `Budget` + `Trace` middleware, typed event stream
- Default model: `claude-sonnet-5` (via choreoai / Anthropic)

## Install from source

Requires **Python 3.10+**.

```bash
git clone https://github.com/choreo-ai/choreo-cli
cd choreo-cli
pip install -e ".[dev]"
```

This pulls **choreoai** from GitHub (`git+https://github.com/choreo-ai/choreo`) as a dependency.

### Local choreoai development

If you have a local checkout of choreo and want offline / editable installs:

```bash
pip install -e /path/to/choreo
pip install -e ".[dev]"
```

## Usage

```bash
# Live agent (requires ANTHROPIC_API_KEY)
export ANTHROPIC_API_KEY=sk-ant-...
choreo-cli

# Skip shell confirmation prompts (use carefully)
choreo-cli --auto

# Single non-interactive command
choreo-cli -c "List the files in this directory"

# Custom working directory
choreo-cli --cwd /path/to/project
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
