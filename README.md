# cq

> A lightweight task queue / buffer for [Claude Code](https://docs.anthropic.com/en/docs/agents-and-tools/claude-code/overview).

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

`cq` lets you dump tasks into a queue and have Claude Code consume them one by one. It solves the classic problem:

> "I just thought of task B, but Claude is still working on task A."

Instead of interrupting the current session, queue the new task and let `cq` feed it to Claude automatically.

---

## Table of Contents

- [Features](#features)
- [Installation](#installation)
- [Quick Start](#quick-start)
- [Usage](#usage)
- [Command Reference](#command-reference)
- [How It Works](#how-it-works)
- [Configuration](#configuration)
- [Development](#development)
- [Testing](#testing)
- [Contributing](#contributing)
- [License](#license)

---

## Features

- **Simple CLI**: Add, list, and manage tasks from the terminal.
- **SQLite-backed queue**: Durable, local-first storage with no external services.
- **One reliable execution mode**: `cq run` processes tasks sequentially via `claude -c -p`.
- **Context preservation**: `context_policy == "continue"` continues the previous Claude conversation; `"new"` starts fresh.
- **Automatic cleanup**: Completed tasks are purged after a configurable retention period (default 24 hours).
- **Easy to extend**: Clean Python package structure; tests included.

---

## Installation

Clone the repository and install in editable mode:

```bash
git clone https://github.com/yourusername/cq.git
cd cq
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS / Linux
source .venv/bin/activate

pip install -e .
```

For development, install the optional dev dependencies:

```bash
pip install -e ".[dev]"
```

---

## Quick Start

For a concrete step-by-step walkthrough, see [USAGE.md](USAGE.md).

1. **Initialize the queue:**

   ```bash
   cq init
   ```

2. **Add tasks anytime:**

   ```bash
   cq add "fix login redirect"
   cq add "optimize database query"
   ```

3. **Run the queue:**

   ```bash
   cq run
   ```

   `cq` will invoke Claude Code for each task, one at a time, until the queue is empty.

---

## Usage

```bash
# Initialize a new queue in .cq/
cq init

# Add tasks
cq add "refactor auth module"
cq add "update README"

# Inspect the queue
cq list

# Run all pending tasks
cq run

# Run a single task
cq run --once

# Keep completed tasks for only 1 hour
cq run --retention-hours 1
```

---

## Command Reference

| Command | Description |
|---------|-------------|
| `cq init` | Create the queue database. |
| `cq add "..."` | Append a new task to the queue. |
| `cq add "..." --context-policy new` | Append a task that starts with a fresh Claude context. |
| `cq list` | Display all tasks and their statuses. |
| `cq next` | Manually claim the next pending task. |
| `cq complete ID` | Mark a task as completed. |
| `cq reset` | Reset `in_progress` / `failed` tasks to `pending`. |
| `cq run` | Process the queue via `claude -c -p`. |
| `cq run --once` | Process a single task. |
| `cq run --retention-hours 12` | Override how long completed tasks are kept. |
| `cq cleanup` | Purge completed tasks older than the retention period. |
| `cq cleanup --retention-hours 0` | Disable retention and keep all completed tasks. |

---

## How It Works

`cq run` processes pending tasks sequentially. For each task it invokes Claude Code with a prompt like:

```text
You are working through a task queue. Current task (N): <description>. Complete ...
```

- Tasks with `context_policy == "continue"` are invoked as `claude -c -p`, so Claude preserves the previous task's conversation context.
- Tasks with `context_policy == "new"` are invoked as `claude -p`, starting fresh.

Each task still runs in its own process, so a failure in one task does not poison the rest. After each task, `cq` automatically deletes completed tasks older than the retention period.

---

## Configuration

| File / Variable | Purpose |
|-----------------|---------|
| `.cq/queue.db` | Default SQLite queue database. |
| `CQ_DB_PATH` | Environment variable to override the database path. |
| `--db PATH` | Per-command flag to override the database path. |
| `CQ_COMPLETED_RETENTION_HOURS` | Hours to keep completed tasks before auto-deletion (default: 24). Set to `0` to disable. |
| `--retention-hours HOURS` | Per-command override for completed-task retention. |
| `.claude/CLAUDE.md` | Instructions loaded by Claude Code when invoked by `cq run`. |

Example:

```bash
export CQ_DB_PATH=/path/to/my-queue.db
export CQ_COMPLETED_RETENTION_HOURS=12
cq init
cq add "deploy staging build"
cq run
```

---

## Development

The project is organized as a standard Python package:

```text
.
├── cq/              # Main package
│   ├── cli.py       # CLI entry point
│   ├── store.py     # SQLite queue backend
│   └── wrapper.py   # Claude wrapper
├── tests/           # Test suite
├── pyproject.toml   # Project metadata and dependencies
├── README.md        # This file
└── USAGE.md         # Step-by-step usage example
```

---

## Testing

Run the test suite with [pytest](https://pytest.org/):

```bash
pytest
```

To run tests with more detail:

```bash
pytest -v
```

---

## Contributing

Contributions are welcome!

1. Fork the repository.
2. Create a feature branch: `git checkout -b feature/my-feature`.
3. Make your changes and add tests where appropriate.
4. Ensure the test suite passes: `pytest`.
5. Submit a pull request with a clear description of your changes.

Please open an issue first for major changes or new features so we can discuss the design.

---

## License

This project is licensed under the [MIT License](LICENSE).
