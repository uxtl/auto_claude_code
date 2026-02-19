# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**claude-vibe-scaffold** — A parallel Claude Code task execution framework. It schedules and runs multiple Claude Code agents concurrently, using git worktrees for isolation, with a web dashboard for monitoring and plan approval.

## Commands

```bash
# Install dependencies
uv sync

# Run tests
uv run pytest tests/ -v

# Run tests with coverage
uv run pytest tests/ --cov=src/vibe --cov-report=term-missing

# Run a single test file
uv run pytest tests/test_task.py -v

# Run a single test
uv run pytest tests/test_task.py::test_function_name -v

# CLI commands
uv run python -m vibe run                    # Execute task queue
uv run python -m vibe serve --port 8080      # Web dashboard + background loop
uv run python -m vibe list                   # List tasks by status
uv run python -m vibe add "description"      # Add a task
uv run python -m vibe recover                # Recover crashed .running files
```

## Architecture

**Package layout:** `src/vibe/` (hatchling src layout), entry point is `__main__.py`.

**Execution flow:**
```
__main__.py (CLI)
  → loop.py (scheduler: ThreadPoolExecutor, worktree lifecycle)
    → worker.py (per-worker loop: claim task, build prompt, execute)
      → manager.py (subprocess: claude -p ... --output-format stream-json)
```

**Key modules:**
- **config.py** — Dataclass config with defaults → `.env` → `VIBE_` env vars hierarchy
- **task.py** — Task model + TaskQueue using atomic file rename as lock (`.md` → `.md.running.{worker_id}`)
- **worker.py** — Worker loop; wraps task content with PROGRESS.md prompt prefix/suffix
- **manager.py** — Spawns Claude Code subprocess, parses stream-json output, dual-threaded stdout/stderr to avoid pipe deadlock
- **loop.py** — Orchestrates workers; single-worker fast path vs multi-worker with git worktrees
- **worktree.py** — Git worktree create/remove/merge, branch naming `vibe/{worker_id}-{timestamp}`
- **server.py** — FastAPI: task CRUD, SSE log streaming, plan approval endpoints, single-file HTML dashboard
- **approval.py** — Thread-safe plan approval workflow using `threading.Event`

**Dependency direction** (no circular imports): `loop → worker → manager`

**Plan mode:** Two-phase execution — `generate_plan()` (no permissions flag, safe) then `execute_plan()` (with `--dangerously-skip-permissions`). Web UI approval gate when `plan_auto_approve=False`.

**Retry mechanism:** Retry count embedded as HTML comment `<!-- RETRY: N -->` in task files. On failure: increment and re-queue; on max retries: move to `tasks/failed/`.

## Configuration

Config fields (set via `.env` or `VIBE_` env vars):
- `task_dir` (tasks), `done_dir` (tasks/done), `fail_dir` (tasks/failed)
- `timeout` (600s), `max_retries` (2), `max_workers` (1)
- `workspace` (.), `use_worktree` (true), `log_level` (INFO), `log_file` ("")
- `plan_mode` (false), `plan_auto_approve` (true)
- `use_docker` (false), `docker_image` (auto-claude-code), `docker_extra_args` ("")

**Docker isolation:** When `use_docker=True`, each Claude Code invocation is wrapped in `docker run`. The `_run_claude()` helper in `manager.py` handles both native and Docker modes. Pre-checks (`check_docker_available`, `ensure_docker_image`) run at startup in `loop.py`.

## Testing

pytest with fixtures in `conftest.py`: `workspace` (tmp_path with task dirs), `config`, `queue`. Tests use `httpx.AsyncClient` for FastAPI endpoint testing.

## Docker

`Dockerfile` builds on Ubuntu 24.04 with Node.js 22, uv, and Claude Code CLI. `docker-compose.yml` mounts target project to `/workspace`.
