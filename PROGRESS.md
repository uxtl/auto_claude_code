# Progress Log

## 项目概览

**项目名称**: auto_claude_code
**定位**: 并行 Claude Code 任务执行脚手架 — 基于文件队列的自动化开发 agent 调度框架
**技术栈**: Python 3.11+, uv, Docker (Ubuntu 24.04), Claude Code CLI

### 核心模块

| 模块 | 路径 | 职责 |
|------|------|------|
| `config` | `src/vibe/config.py` | 分层配置加载（默认值 → .env → 环境变量），`VIBE_` 前缀 |
| `task` | `src/vibe/task.py` | Task 数据模型 + 线程安全的文件队列（原子 rename 认领） |
| `worker` | `src/vibe/worker.py` | 单 worker 执行循环，构建 prompt 并调用 manager |
| `loop` | `src/vibe/loop.py` | 调度入口，单 worker 快速路径 / 多 worker ThreadPoolExecutor |
| `manager` | `src/vibe/manager.py` | subprocess 启动 Claude Code，流式 JSON 解析，结果封装 |
| `__main__` | `src/vibe/__main__.py` | CLI 入口（run / serve / list / add / recover 子命令） |
| `worktree` | `src/vibe/worktree.py` | Git worktree 生命周期（创建/合并/清理） |
| `server` | `src/vibe/server.py` | FastAPI Web 管理界面 + SSE 日志推送 |
| `approval` | `src/vibe/approval.py` | 线程安全的 Plan 审批流程（Event 同步 + 内存存储） |

### 关键文件

- `pyproject.toml` — hatchling 构建配置 + `[tool.vibe]` 自定义段
- `Dockerfile` — Ubuntu 24.04 + Node.js 22.x + uv + Claude Code
- `docker-compose.yml` — vibe（主服务 + 端口 8080）+ test（测试容器）
- `templates/CLAUDE.md` — 注入目标项目的 agent 指令模板
- `templates/PROGRESS.md` — 进度日志模板
- `scripts/init.sh` — 一键初始化目标项目

### 调用链路

```
__main__.run / __main__.serve
  → loop.run_loop(config)
      → TaskQueue(task_dir, done_dir, fail_dir)
      → [多 worker + git repo] worktree.create_worktree() per worker
      → worker_loop("w{i}", config, queue, worktree?)  × max_workers
          → worker.build_prompt(task_content)
          → [plan_mode + auto_approve]  manager.run_plan() → generate_plan() → execute_plan()
          → [plan_mode + !auto_approve] generate_plan() → approval.wait() → execute_plan()
          → [normal]    manager.run_task(prompt, cwd, timeout)
              → subprocess: claude -p ... --output-format stream-json
              → _parse_stream_json → TaskResult
          → queue.complete(task) | queue.fail(task, error)
      → [worktree] worktree.commit_and_merge() + remove_worktree()

__main__.serve
  → server.start_server(config, host, port)
      → ApprovalStore()             # 共享审批实例
      → threading.Thread(run_loop(approval_store=...))  # 后台任务循环
      → uvicorn.run(FastAPI app)    # Web 管理界面 + 审批 API
```

## 经验教训

### 构建与打包
- `src/` layout 必须在 `pyproject.toml` 中配置 `[build-system]` + hatchling，否则 `uv` 无法识别包结构

### 循环导入
- `loop.py` 和 `worker.py` 之间曾出现循环 import；通过将 `build_prompt()` 移入 `worker.py` 解决，保持单向依赖：`loop → worker → manager`

### 分布式锁
- 文件 rename（`.md` → `.md.running.{worker_id}`）作为原子认领标记，简单可靠
- crash 后通过 `recover_running()` 扫描 `.running.*` 文件即可恢复，无需外部存储

### 并行策略
- ThreadPoolExecutor 适合此场景：worker 主要等待 subprocess I/O，GIL 无实际影响
- 单 worker 时走快速路径（直接调用，不创建线程池），减少不必要开销

### subprocess 管理
- 用双线程分别读 stdout/stderr，避免管道满导致死锁
- Claude Code `--output-format stream-json` 提供结构化输出，可提取 tool_calls 和 files_changed

## 已完成任务

### Phase 1: 闭环执行 + 经验沉淀
- **loop.py**: 主调度循环，扫描任务目录 → 认领 → 执行 → 归档
- **manager.py**: Claude Code 进程管理，stream-json 解析，TaskResult 封装
- **templates/**: CLAUDE.md（agent 行为规范）+ PROGRESS.md（进度模板）
- **scripts/init.sh**: 一键初始化目标项目

### Phase 2: 配置系统 + 并行化 + 健壮性
- **config.py**: 分层配置（默认值 → .env → 环境变量），dataclass 实现，类型自动转换
- **task.py**: Task 模型 + TaskQueue 线程安全队列，retry 计数（HTML 注释），done/failed 归档
- **worker.py**: worker 执行循环 + prompt 构建，独立于 loop 避免循环导入
- **__main__.py**: CLI（run / list / add / recover），集中日志配置，参数覆盖
- **docker-compose.yml**: vibe 主服务 + test 测试容器，volume 分离脚手架与目标项目

### Phase 3A: Git Worktree 隔离
- **worktree.py**: Git worktree 生命周期管理（创建/移除/合并/清理），为每个 worker 提供独立工作树
- **loop.py**: 多 worker 时自动创建 worktree，任务完成后逐个 merge 回主分支并清理
- **worker.py**: 接收可选的 worktree 路径作为工作目录
- **config.py**: 新增 `use_worktree: bool = True` 配置项
- **__main__.py**: `run` 子命令新增 `--no-worktree` 选项
- 非 git 仓库自动降级为共享 workspace + 警告；单 worker 不创建 worktree
- 合并冲突时保留分支名供手动处理，中止失败的 merge 保持主分支干净

### Phase 3B: Web Manager
- **server.py**: FastAPI Web 服务，API 路由（任务列表/添加/重试/删除/配置/SSE 日志）
- **dashboard.html**: 单文件 HTML 管理界面（任务表格、状态统计、添加表单、实时日志滚动）
- **__main__.py**: 新增 `serve` 子命令（--host, --port），同时启动 web server + 后台任务循环
- **pyproject.toml**: 添加 fastapi>=0.115, uvicorn[standard]>=0.34 依赖
- **docker-compose.yml**: vibe 服务暴露端口 ${VIBE_PORT:-8080}:8080
- SSE 实时日志推送，5 秒轮询任务状态自动刷新

### Phase 3C: Plan Mode 集成
- **manager.py**: 新增 `run_plan()` — 两步执行：先不带权限生成计划，再带权限按计划执行
- **worker.py**: 根据 `config.plan_mode` 选择 `run_plan()` 或 `run_task()`
- **config.py**: 新增 `plan_mode: bool = False`, `plan_auto_approve: bool = True`
- **__main__.py**: `run` 子命令新增 `--plan-mode` 选项
- 计划阶段超时限制为总超时的 1/3 或 5 分钟（取较小值）
- 计划内容记录到任务输出中便于审计

### Phase 5: Plan Mode 人工审批流程
- **approval.py**: 新增模块 — `ApprovalDecision` 枚举、`PendingApproval` 数据类（含 `threading.Event` 同步）、`ApprovalStore` 线程安全存储（submit/get/list_pending/approve/reject/remove）
- **manager.py**: 拆分 `run_plan()` → `generate_plan()` + `execute_plan()`，原 `run_plan()` 保留为向后兼容包装
- **worker.py**: 新增 `_execute_with_approval()` 审批路由 — 当 `plan_auto_approve=False` 且有 `approval_store` 时走人工审批流程
- **loop.py**: `run_loop()` / `worker_loop()` 透传 `approval_store` 参数
- **server.py**: 3 个审批 API 端点 — `GET /api/approvals`、`POST /api/approvals/{id}/approve`、`POST /api/approvals/{id}/reject`；`start_server()` 创建共享 `ApprovalStore` 并传入 `run_loop`
- **dashboard.html**: Awaiting Approval 计数器 + Pending Approvals 卡片（显示计划文本、approve/reject 按钮）+ 3 秒轮询
- **__main__.py**: CLI 模式（`run` 子命令）自动覆盖 `plan_auto_approve=True` 并输出警告，因 CLI 无 web UI 无法审批

## 经验教训（Phase 3 新增）

### Git Worktree
- 使用 `-b branch_name` 创建命名分支（而非 `--detach`），便于 merge 时引用
- worktree 放在 `/tmp/vibe-{worker_id}-{timestamp}` 避免路径冲突
- merge 失败时先 `git merge --abort` 保持主分支干净，再保留分支供手动处理

### Web Manager
- FastAPI + 内嵌 HTML（单文件）避免前端构建流程
- SSE 比 WebSocket 更简单，浏览器原生支持 EventSource
- `serve` 子命令在后台 daemon 线程运行任务循环，uvicorn 在主线程

### Plan Mode
- 两步执行的关键：第一步不带 `--dangerously-skip-permissions` 确保计划阶段安全
- 超时分配策略：计划阶段占 1/3，执行阶段用剩余时间

### 人工审批（Phase 5 新增）
- `threading.Event` 作为 worker⇔FastAPI 线程间同步原语，简单高效：worker 阻塞等待 `event.wait()`，web handler 调用 `event.set()` 唤醒
- `ApprovalStore` 的 submit/wait/remove 生命周期需注意清理：无论 approve 还是 reject，worker 完成后应 `remove()` 避免内存泄漏
- CLI 模式无 web UI，强制 `plan_auto_approve=True` 是合理的降级策略

### Phase 6: Docker 隔离模式
- **config.py**: 新增 3 个配置字段 — `use_docker: bool = False`、`docker_image: str = "auto-claude-code"`、`docker_extra_args: str = ""`，通过 `VIBE_USE_DOCKER` / `VIBE_DOCKER_IMAGE` / `VIBE_DOCKER_EXTRA_ARGS` 环境变量加载
- **manager.py**: 核心重构 — 提取 `_run_claude()` 公共子进程管理函数（消除 `run_task` 和 `generate_plan` 中的重复代码）；新增 `_build_docker_cmd()` 将 claude 命令包装为 `docker run`；新增 `check_docker_available()` 和 `ensure_docker_image()` 预检函数；所有公开 API（`run_task`/`generate_plan`/`execute_plan`/`run_plan`）新增 `use_docker`/`docker_image`/`docker_extra_args` 关键字参数
- **worker.py**: 新增 `_docker_kwargs(config)` 辅助函数，`_execute_task()` 和 `_execute_with_approval()` 中所有 manager 调用透传 Docker 参数
- **loop.py**: `run_loop()` 开头增加 Docker 预检（`check_docker_available` + `ensure_docker_image`），失败则 `raise RuntimeError`
- **__main__.py**: `run` 和 `serve` 子命令新增 `--docker` 和 `--docker-image` CLI 参数
- Docker 模式下：工作目录通过 `-v {cwd}:/workspace -w /workspace` 挂载，`ANTHROPIC_API_KEY` 通过 `-e` 传递，容器 `--rm -i` 一次性使用
- 完全向后兼容：`use_docker=False`（默认）时行为与之前完全一致

## 经验教训（Phase 6 新增）

### Docker 隔离
- 子进程管理逻辑重复是重构的好时机：`_run_claude()` 统一了 Popen + 双线程读取 + 超时 + 解析流程，Docker 包装只在最外层切换命令
- Docker 模式下 `cwd` 参数设为 `None`（通过 `-w /workspace` 控制），避免宿主机路径泄露
- `ensure_docker_image()` 自动检测并构建，降低首次使用门槛
- 额外参数通过 `shlex.split()` 解析字符串，允许用户灵活传递 `--network=none --memory=4g` 等

## 待确认问题

- **权限安全门控**: 当前使用 `--dangerously-skip-permissions`，是否需要提供可选的交互式权限确认模式？
- **下一阶段优先级**: 测试覆盖 / 任务依赖图 / CI/CD 集成 — 哪个优先？
