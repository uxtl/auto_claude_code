# auto_claude_code

并行 Claude Code 任务执行框架 — 基于文件队列调度多个 Claude Code agent 并发工作，通过 git worktree 实现文件隔离，配备 Web 仪表盘进行监控与审批。

## 特性

- **文件队列调度** — 将 Markdown 文件放入 `tasks/` 目录即为一个任务，原子 rename 实现线程安全认领
- **多 Worker 并行** — ThreadPoolExecutor 驱动，每个 worker 独立认领和执行任务
- **Git Worktree 隔离** — 多 worker 时自动为每个 worker 创建独立 worktree，执行完成后 merge 回主分支
- **Plan Mode** — 两阶段执行：先生成计划（安全，无写权限），再按计划执行
- **人工审批** — Plan Mode 下可启用 Web UI 审批门控，人工确认计划后再执行
- **Web 仪表盘** — 实时查看任务状态、添加/删除/重试任务、SSE 日志流、审批管理
- **自动重试** — 任务失败后自动重试（可配置次数），超限后移入 `tasks/failed/`
- **崩溃恢复** — `.running` 文件可通过 `recover` 命令一键恢复为待执行状态

## 前置要求

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) 包管理器
- [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) (`npm install -g @anthropic-ai/claude-code`)
- `ANTHROPIC_API_KEY` 环境变量已设置
- Git（如需 worktree 隔离）

## 安装

```bash
git clone <repo-url> auto_claude_code
cd auto_claude_code
uv sync
```

安装开发依赖（测试）：

```bash
uv sync --dev
```

## 快速开始

### 1. 初始化目标项目

将 agent 指令模板和任务目录注入到你的目标项目中：

```bash
bash scripts/init.sh /path/to/your/project
```

这会在目标项目中创建：
- `CLAUDE.md` — agent 行为规范（请编辑其中的 `{project_name}`）
- `PROGRESS.md` — agent 进度日志模板
- `tasks/` 和 `tasks/done/` 目录

### 2. 编写任务

在目标项目的 `tasks/` 目录中创建 Markdown 文件，每个文件就是一个任务：

```bash
# 手动创建
echo "实现用户登录功能，使用 JWT token 认证" > /path/to/your/project/tasks/001_login.md

# 或使用 CLI
uv run python -m vibe add "实现用户登录功能，使用 JWT token 认证" -w /path/to/your/project
```

任务文件命名建议：`NNN_描述.md`（如 `001_login.md`、`002_dashboard.md`），编号用于排序。

### 3. 执行任务

```bash
# 单 worker 执行
uv run python -m vibe run -w /path/to/your/project

# 多 worker 并行（自动使用 git worktree 隔离）
uv run python -m vibe run -w /path/to/your/project -n 3
```

### 4. 启动 Web 仪表盘

```bash
uv run python -m vibe serve -w /path/to/your/project --port 8080
```

打开 `http://localhost:8080` 即可看到仪表盘，功能包括：
- 任务状态总览（pending / running / done / failed）
- 添加新任务
- 重试失败任务 / 删除任务
- 实时日志流（SSE）
- Plan Mode 审批管理

`serve` 模式会同时在后台运行任务循环，无需单独启动 `run`。

## CLI 命令参考

```
uv run python -m vibe <command> [options]
```

### `run` — 执行任务队列

```bash
uv run python -m vibe run [options]
```

| 选项 | 说明 |
|------|------|
| `-w, --workspace PATH` | 目标项目工作目录 |
| `-n, --workers N` | 并行 worker 数量（默认 1） |
| `--no-worktree` | 禁用 git worktree 隔离 |
| `--plan-mode` | 启用 Plan Mode（先生成计划再执行） |
| `--docker` | 启用 Docker 隔离模式 |
| `--docker-image NAME` | Docker 镜像名（默认 `auto-claude-code`） |

扫描 `tasks/` 目录中的 `.md` 文件，逐个认领并执行。执行完成的任务移入 `tasks/done/`，失败的移入 `tasks/failed/`。队列清空后自动退出。

### `serve` — Web 仪表盘 + 后台任务循环

```bash
uv run python -m vibe serve [options]
```

| 选项 | 说明 |
|------|------|
| `-w, --workspace PATH` | 目标项目工作目录 |
| `-n, --workers N` | 并行 worker 数量 |
| `--host HOST` | 监听地址（默认 `0.0.0.0`） |
| `--port PORT` | 监听端口（默认 `8080`） |
| `--docker` | 启用 Docker 隔离模式 |
| `--docker-image NAME` | Docker 镜像名（默认 `auto-claude-code`） |

### `list` — 查看任务状态

```bash
uv run python -m vibe list [-w PATH]
```

输出所有任务的状态（pending / running / done / failed）。

### `add` — 快速添加任务

```bash
uv run python -m vibe add "任务描述" [-w PATH]
```

自动编号，生成 `NNN_描述.md` 文件到 `tasks/` 目录。

### `recover` — 恢复崩溃任务

```bash
uv run python -m vibe recover [-w PATH]
```

将 `.md.running.*` 文件恢复为 `.md`，使中断的任务可以重新被认领。

## 配置

配置通过三层覆盖加载：**默认值 → `.env` 文件 → 环境变量**（后者优先）。

环境变量统一使用 `VIBE_` 前缀。在目标项目根目录放置 `.env` 文件或直接设置环境变量均可。

| 配置项 | 环境变量 | 默认值 | 说明 |
|--------|----------|--------|------|
| `task_dir` | `VIBE_TASK_DIR` | `tasks` | 任务文件目录 |
| `done_dir` | `VIBE_DONE_DIR` | `tasks/done` | 已完成任务归档目录 |
| `fail_dir` | `VIBE_FAIL_DIR` | `tasks/failed` | 失败任务归档目录 |
| `timeout` | `VIBE_TIMEOUT` | `600` | 单个任务超时秒数 |
| `max_retries` | `VIBE_MAX_RETRIES` | `2` | 最大重试次数 |
| `max_workers` | `VIBE_MAX_WORKERS` | `1` | 并行 worker 数量 |
| `workspace` | `VIBE_WORKSPACE` | `.` | 目标项目工作目录 |
| `use_worktree` | `VIBE_USE_WORKTREE` | `true` | 是否启用 git worktree 隔离 |
| `log_level` | `VIBE_LOG_LEVEL` | `INFO` | 日志级别 |
| `log_file` | `VIBE_LOG_FILE` | *(空)* | 日志文件路径（为空则仅输出到控制台） |
| `plan_mode` | `VIBE_PLAN_MODE` | `false` | 是否启用 Plan Mode |
| `plan_auto_approve` | `VIBE_PLAN_AUTO_APPROVE` | `true` | Plan Mode 是否自动审批 |
| `use_docker` | `VIBE_USE_DOCKER` | `false` | 是否启用 Docker 隔离模式 |
| `docker_image` | `VIBE_DOCKER_IMAGE` | `auto-claude-code` | Docker 镜像名 |
| `docker_extra_args` | `VIBE_DOCKER_EXTRA_ARGS` | *(空)* | 额外 docker run 参数 |

`.env` 文件示例：

```env
VIBE_MAX_WORKERS=3
VIBE_TIMEOUT=900
VIBE_PLAN_MODE=true
VIBE_PLAN_AUTO_APPROVE=false
VIBE_LOG_LEVEL=DEBUG
```

## Plan Mode 与人工审批

Plan Mode 将任务执行分为两个阶段：

1. **生成计划** — 不带写权限调用 Claude Code，只产出执行方案
2. **执行计划** — 带权限按计划执行实际修改

### 自动审批（默认）

```bash
uv run python -m vibe run -w /path/to/project --plan-mode
```

生成计划后自动进入执行阶段，无需人工干预。

### 人工审批

需要通过 Web 仪表盘使用。在 `.env` 中配置：

```env
VIBE_PLAN_MODE=true
VIBE_PLAN_AUTO_APPROVE=false
```

然后启动 `serve` 模式：

```bash
uv run python -m vibe serve -w /path/to/project
```

工作流程：
1. Worker 认领任务，调用 Claude Code 生成执行计划
2. 计划提交到审批队列，Worker 阻塞等待
3. Web 仪表盘显示待审批计划（含完整计划文本）
4. 人工点击 **Approve**（批准执行）或 **Reject**（拒绝，标记任务失败）
5. Worker 收到通知，继续执行或标记失败

> **注意**: CLI 模式（`run` 子命令）不支持人工审批（无 Web UI），会自动覆盖为 `plan_auto_approve=true` 并输出警告。

## 任务生命周期

```
tasks/001_feature.md                    ← pending（待认领）
  ↓ worker 认领
tasks/001_feature.md.running.w0         ← running（执行中）
  ↓ 成功
tasks/done/20260219_143000_001_feature.md   ← done
  ↓ 失败（重试次数未耗尽）
tasks/001_feature.md                    ← 重新入队（文件头部注入 <!-- RETRY: N -->）
  ↓ 失败（重试耗尽）
tasks/failed/20260219_143500_001_feature.md ← failed
```

## Docker 隔离模式

启用 Docker 隔离后，每次 Claude Code 调用都会自动包装在 `docker run` 容器内执行，将破坏范围限制在容器内部。

### 使用方式

```bash
# 先构建镜像（首次使用或 Dockerfile 更新后）
docker build -t auto-claude-code .

# CLI 模式
uv run python -m vibe run -w /path/to/project --docker

# Web 仪表盘模式
uv run python -m vibe serve -w /path/to/project --docker

# 指定自定义镜像
uv run python -m vibe run -w /path/to/project --docker --docker-image my-image
```

也可通过环境变量 / `.env` 配置：

```env
VIBE_USE_DOCKER=true
VIBE_DOCKER_IMAGE=auto-claude-code
VIBE_DOCKER_EXTRA_ARGS=--network=none --memory=4g
```

### 工作原理

- 每次 `claude` 命令调用被包装为 `docker run --rm -i -v {cwd}:/workspace -w /workspace -e ANTHROPIC_API_KEY {image} claude ...`
- 工作目录通过 `-v` 挂载到容器的 `/workspace`
- `ANTHROPIC_API_KEY` 自动传递到容器内
- 启动时自动检查 Docker 可用性和镜像是否存在（不存在则自动构建）

### 已知限制

- 容器内创建的文件归 root 所有，可通过 `VIBE_DOCKER_EXTRA_ARGS="--user $(id -u):$(id -g)"` 解决
- Git worktree + Docker 模式下，容器内 git 操作可能因无法访问父 `.git` 目录而受限
- 框架自身运行在 Docker 内时（docker-compose 场景）不应再启用 `use_docker`（避免 Docker-in-Docker）

## Docker 部署

### docker-compose

```bash
# 设置环境变量
export ANTHROPIC_API_KEY=sk-ant-...
export TARGET_PROJECT=/path/to/your/project

# 启动
docker-compose up vibe
```

`docker-compose.yml` 会将脚手架代码挂载到 `/app`，目标项目挂载到 `/workspace`。

通过环境变量控制行为：

```bash
ANTHROPIC_API_KEY=sk-ant-...    # 必需
TARGET_PROJECT=/path/to/project  # 目标项目路径（默认当前目录）
VIBE_MAX_WORKERS=3               # 并行数
VIBE_PORT=8080                   # Web 端口
```

### 直接使用 Dockerfile

```bash
docker build -t vibe .
docker run -v /path/to/project:/workspace \
  -e ANTHROPIC_API_KEY=sk-ant-... \
  -p 8080:8080 \
  vibe uv run python -m vibe serve --port 8080
```

## 测试

```bash
# 运行全部测试
uv run pytest tests/ -v

# 带覆盖率
uv run pytest tests/ --cov=src/vibe --cov-report=term-missing

# 运行单个测试文件
uv run pytest tests/test_approval.py -v

# 运行单个测试
uv run pytest tests/test_approval.py::test_function_name -v
```

## 项目结构

```
auto_claude_code/
├── src/vibe/
│   ├── __main__.py       # CLI 入口（run / serve / list / add / recover）
│   ├── config.py         # 分层配置加载
│   ├── task.py           # Task 模型 + 文件队列
│   ├── worker.py         # Worker 执行循环
│   ├── manager.py        # Claude Code 子进程管理
│   ├── loop.py           # 调度器（单/多 worker）
│   ├── worktree.py       # Git worktree 生命周期
│   ├── server.py         # FastAPI Web 服务
│   ├── approval.py       # Plan 审批流程
│   └── dashboard.html    # Web 仪表盘（单文件 HTML）
├── templates/
│   ├── CLAUDE.md         # 注入目标项目的 agent 指令模板
│   └── PROGRESS.md       # 进度日志模板
├── scripts/
│   └── init.sh           # 一键初始化目标项目
├── tests/                # pytest 测试
├── Dockerfile
├── docker-compose.yml
└── pyproject.toml
```

## License

MIT
