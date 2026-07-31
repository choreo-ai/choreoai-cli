<p align="center">
  <img src="https://raw.githubusercontent.com/choreo-ai/choreoai/main/assets/banner.png" alt="ChoreoAI — Multi-agent systems, in production." width="840">
</p>

<p align="center">
  <img src="https://raw.githubusercontent.com/choreo-ai/choreoai/main/assets/logo.svg" alt="ChoreoAI" width="64">
</p>

# choreoai-cli

**A Claude-Code-style coding agent harness built on [ChoreoAI](https://github.com/choreo-ai/choreoai) (`choreoai`).**

`choreoai-cli` is an interactive terminal REPL that runs a coding agent in your current
directory using ChoreoAI's `LLMAgent`, tools, budget, and trace — so the harness itself is
budget-bounded and observable.

<p align="center">
  <img src="https://img.shields.io/badge/status-pre--alpha-C06B4E?style=flat-square" alt="status: pre-alpha">
  <img src="https://img.shields.io/badge/python-3.10%2B-33302B?style=flat-square" alt="python 3.10+">
  <img src="https://img.shields.io/badge/license-MIT-A8583D?style=flat-square" alt="license: MIT">
  <a href="https://pypi.org/project/choreoai-cli/"><img src="https://img.shields.io/pypi/v/choreoai-cli?style=flat-square&color=A8583D" alt="PyPI"></a>
</p>

> **Status: pre-alpha.** This is a minimal but working slice (v0), not a full Claude Code clone.

## Features (v0)

- Interactive REPL (`choreoai-cli`) with `/help`, `/reset`, `/exit`
- Polished terminal UI: **rich** panels/markdown/syntax + **prompt_toolkit** history/multiline input
- Live-streamed tool calls via ChoreoAI event subscribers (spinner while the model thinks)
- Coding tools: `read_file`, `write_file`, `list_dir`, `run_shell` (path jail under `--cwd`)
- Shell commands require confirmation unless `--auto` is set
- Built on ChoreoAI: `LLMAgent` tool loop, `Budget` + `Trace` middleware, typed event stream
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

### Local ChoreoAI development

PyPI requires a normal version pin (`choreoai>=0.0.1`), not a git URL. For local / offline
development against a checkout of the framework:

```bash
# Install framework from local checkout first (editable)
pip install -e /path/to/choreoai

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
| `/reset` | Clear session budget, shell approvals, and trace |
| `/exit`  | Quit                    |

Anything else is sent to the coding agent as an instruction.

Input uses `prompt_toolkit` when the terminal is interactive (history, Esc+Enter
for multiline submit). Pipes and tests fall back to plain `input`.

### Environment

| Variable            | Required | Notes                                      |
|---------------------|----------|--------------------------------------------|
| `ANTHROPIC_API_KEY` | For live | Default model is `claude-sonnet-5`         |

Offline tests inject a fake `BaseChatModel` and do **not** need an API key.

## Tests

```bash
# Prefer editable local choreoai if you have a checkout
pip install -e /path/to/choreoai
pip install -e ".[dev]"
pytest
```

Tests are offline: no network and no `ANTHROPIC_API_KEY`.

## How it works

1. Builds a ChoreoAI `LLMAgent` with a coding-assistant system prompt and file/shell tools.
2. Wraps each turn in ChoreoAI `BudgetMiddleware` + `TraceMiddleware` (onion stack).
3. Runs the agent tool loop; prints tool calls, the final answer (rich), budget usage, and a short trace summary.

## License

[MIT](LICENSE) © 2026 Karthik Reddy

<p align="center">
  <img src="https://raw.githubusercontent.com/choreo-ai/choreoai/main/assets/logo.svg" alt="ChoreoAI" width="28"><br>
  <sub><strong>ChoreoAI</strong> &middot; multi-agent systems, in production &middot;
  <a href="https://github.com/choreo-ai/choreoai-cli">github.com/choreo-ai/choreoai-cli</a></sub>
</p>
