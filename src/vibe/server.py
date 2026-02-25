"""FastAPI Web 管理界面 — 任务查看、添加、重试 + SSE 实时日志."""

import asyncio
import itertools
import logging
import re
import threading
from collections import deque
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .approval import ApprovalStore
from .config import Config, load_config
from .history import ExecutionHistory
from .loop import run_loop
from .task import (
    TaskQueue,
    _make_slug,
    extract_dependencies,
    extract_error_context,
    extract_retry_count,
    first_content_line,
    next_task_number,
)
from .worker import get_all_worker_status

logger = logging.getLogger(__name__)

# 全局日志缓冲（供 SSE 推送），存储 (seq, msg) 元组
_log_seq = itertools.count()
_log_buffer: deque[tuple[int, str]] = deque(maxlen=500)
_log_event: asyncio.Event | None = None
_loop: asyncio.AbstractEventLoop | None = None


class _SSELogHandler(logging.Handler):
    """将日志写入内存缓冲并通知 SSE 订阅者."""

    def emit(self, record: logging.LogRecord) -> None:
        msg = self.format(record)
        _log_buffer.append((next(_log_seq), msg))
        loop = _loop
        event = _log_event
        if loop is not None and event is not None:
            try:
                loop.call_soon_threadsafe(event.set)
            except RuntimeError:
                pass  # Event loop 已关闭（进程退出期间）


def _install_log_handler() -> None:
    handler = _SSELogHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S"))
    logging.getLogger("vibe").addHandler(handler)
    logging.getLogger("vibe").setLevel(logging.DEBUG)


def create_app(
    config: Config | None = None,
    approval_store: ApprovalStore | None = None,
    history: ExecutionHistory | None = None,
) -> FastAPI:
    """创建 FastAPI 应用实例."""
    if config is None:
        config = load_config()

    workspace = Path(config.workspace).resolve()
    config.workspace = str(workspace)

    _task_num_lock = threading.Lock()

    _install_log_handler()

    @asynccontextmanager
    async def _lifespan(app: FastAPI):
        global _loop, _log_event
        _loop = asyncio.get_running_loop()
        _log_event = asyncio.Event()
        yield
        # Uvicorn 正在关闭 — 通知 worker 线程停止
        from .worker import shutdown_event as _se
        _se.set()
        _loop = None
        _log_event = None

    app = FastAPI(title="Vibe Manager", version="0.3.0", lifespan=_lifespan)

    # ── 任务列表 ─────────────────────────────────────────────

    def _scan_tasks() -> list[dict]:
        """扫描文件系统，返回所有任务的状态（含描述、依赖信息）."""
        task_dir = workspace / config.task_dir
        done_dir = workspace / config.done_dir
        fail_dir = workspace / config.fail_dir
        tasks = []

        # 预先收集 done 编号，用于判断依赖是否满足
        done_nums: set[int] = set()
        if done_dir.is_dir():
            for f in done_dir.glob("*.md"):
                name = re.sub(r"^\d{8}_\d{6}(_\d{6})?_", "", f.stem)
                m = re.match(r"^(\d+)", name)
                if m:
                    done_nums.add(int(m.group(1)))

        failed_nums: set[int] = set()
        if fail_dir.is_dir():
            for f in fail_dir.glob("*.md"):
                name = re.sub(r"^\d{8}_\d{6}(_\d{6})?_", "", f.stem)
                m = re.match(r"^(\d+)", name)
                if m:
                    failed_nums.add(int(m.group(1)))

        # pending
        for f in sorted(task_dir.glob("*.md")):
            if ".running." not in f.name:
                content = f.read_text(encoding="utf-8")
                deps = extract_dependencies(content)
                desc = first_content_line(content)
                unmet = [d for d in deps if d not in done_nums] if deps else []
                entry: dict = {
                    "name": f.stem, "status": "pending", "file": f.name,
                    "description": desc,
                }
                if deps:
                    entry["depends"] = deps
                    entry["blocked"] = bool(unmet)
                    entry["unmet_deps"] = unmet
                tasks.append(entry)

        # running
        for f in sorted(task_dir.glob("*.md.running.*")):
            parts = f.name.split(".running.")
            worker = parts[1] if len(parts) > 1 else "?"
            base_name = parts[0].replace(".md", "") if parts else f.stem
            tasks.append({
                "name": base_name, "status": "running",
                "worker": worker, "file": f.name,
            })

        # done
        if done_dir.is_dir():
            for f in sorted(done_dir.glob("*.md")):
                name = re.sub(r"^\d{8}_\d{6}(_\d{6})?_", "", f.stem)
                tasks.append({"name": name, "status": "done", "file": f.name})

        # failed
        if fail_dir.is_dir():
            for f in sorted(fail_dir.glob("*.md")):
                name = re.sub(r"^\d{8}_\d{6}(_\d{6})?_", "", f.stem)
                tasks.append({"name": name, "status": "failed", "file": f.name})

        return tasks

    @app.get("/api/tasks")
    async def list_tasks() -> list[dict]:
        return _scan_tasks()

    # ── 添加任务 ─────────────────────────────────────────────

    @app.post("/api/tasks")
    async def add_task(request: Request) -> JSONResponse:
        body = await request.json()
        description = body.get("description", "").strip()
        if not description:
            return JSONResponse({"error": "description 不能为空"}, status_code=400)

        depends: list[int] = body.get("depends", [])

        task_dir = workspace / config.task_dir
        done_dir = workspace / config.done_dir
        fail_dir = workspace / config.fail_dir
        task_dir.mkdir(parents=True, exist_ok=True)

        with _task_num_lock:
            next_num = next_task_number(task_dir, done_dir, fail_dir)
            slug = _make_slug(description)
            filename = f"{next_num:03d}_{slug}.md"

            content = ""
            if depends:
                dep_strs = [str(d).zfill(3) for d in depends]
                content += f"<!-- DEPENDS: {', '.join(dep_strs)} -->\n"
            content += description + "\n"

            (task_dir / filename).write_text(content, encoding="utf-8")
        logger.info("通过 Web 添加任务: %s", filename)
        return JSONResponse({"filename": filename, "number": next_num}, status_code=201)

    # ── 重试任务 ─────────────────────────────────────────────

    @app.post("/api/tasks/{name}/retry")
    async def retry_task(name: str) -> JSONResponse:
        fail_dir = workspace / config.fail_dir
        task_dir = workspace / config.task_dir

        retried = TaskQueue.retry_failed(task_dir, fail_dir, name=name)
        if not retried:
            return JSONResponse({"error": f"未找到失败任务: {name}"}, status_code=404)
        return JSONResponse({"retried": retried[0]})

    # ── 强制运行（移除依赖限制）─────────────────────────────

    @app.post("/api/tasks/{name}/force-run")
    async def force_run_task(name: str) -> JSONResponse:
        """移除任务的 DEPENDS 注释，使其可被立即认领."""
        task_dir = workspace / config.task_dir
        for f in sorted(task_dir.glob("*.md")):
            if ".running." in f.name:
                continue
            if f.stem == name:
                content = f.read_text(encoding="utf-8")
                from .task import _DEPENDS_PATTERN
                new_content = _DEPENDS_PATTERN.sub("", content).lstrip("\n")
                if not new_content.endswith("\n"):
                    new_content += "\n"
                f.write_text(new_content, encoding="utf-8")
                logger.info("强制运行任务（移除依赖）: %s", f.name)
                return JSONResponse({"forced": f.name})
        return JSONResponse({"error": f"未找到 pending 任务: {name}"}, status_code=404)

    # ── 删除任务 ─────────────────────────────────────────────

    @app.delete("/api/tasks/{name}")
    async def delete_task(name: str) -> JSONResponse:
        task_dir = workspace / config.task_dir
        # 搜索 pending 和 failed
        for search_dir in [task_dir, workspace / config.fail_dir]:
            matches = [
                f for f in search_dir.glob("*.md")
                if f.stem == name or re.sub(r"^\d{8}_\d{6}(_\d{6})?_", "", f.stem) == name
            ]
            if matches:
                matches[0].unlink()
                logger.info("删除任务: %s", matches[0].name)
                return JSONResponse({"deleted": matches[0].name})
        return JSONResponse({"error": f"未找到任务: {name}"}, status_code=404)

    # ── 任务内容详情 ──────────────────────────────────────────

    @app.get("/api/tasks/{name}/content")
    async def get_task_content(name: str) -> JSONResponse:
        """读取任务文件内容 + 解析元数据."""
        task_dir = workspace / config.task_dir
        done_dir = workspace / config.done_dir
        fail_dir = workspace / config.fail_dir
        _ts_re = re.compile(r"^\d{8}_\d{6}(_\d{6})?_")

        # 搜索所有目录
        search = [
            (task_dir, "*.md", "pending"),
            (task_dir, "*.md.running.*", "running"),
            (done_dir, "*.md", "done"),
            (fail_dir, "*.md", "failed"),
        ]
        for search_dir, pattern, status in search:
            if not search_dir.is_dir():
                continue
            for f in search_dir.glob(pattern):
                # 提取基本名称
                fname = f.name.split(".running.")[0].replace(".md", "") if ".running." in f.name else f.stem
                clean_name = _ts_re.sub("", fname)
                if fname == name or clean_name == name:
                    content = f.read_text(encoding="utf-8")
                    errors, diagnostics, clean_content = extract_error_context(content)
                    retry_count = extract_retry_count(content)
                    try:
                        modified_at = f.stat().st_mtime
                    except OSError:
                        modified_at = 0.0
                    return JSONResponse({
                        "name": name,
                        "status": status,
                        "raw_content": content,
                        "clean_content": clean_content,
                        "errors": errors,
                        "diagnostics": diagnostics,
                        "retry_count": retry_count,
                        "file": f.name,
                        "modified_at": modified_at,
                    })

        return JSONResponse({"error": f"未找到任务: {name}"}, status_code=404)

    # ── 编辑任务内容 ──────────────────────────────────────────

    @app.put("/api/tasks/{name}/content")
    async def update_task_content(name: str, request: Request) -> JSONResponse:
        """编辑 pending 任务的内容."""
        task_dir = workspace / config.task_dir
        for f in sorted(task_dir.glob("*.md")):
            if ".running." in f.name:
                continue
            if f.stem == name:
                body = await request.json()
                new_content = body.get("content", "").strip()
                if not new_content:
                    return JSONResponse({"error": "content 不能为空"}, status_code=400)
                f.write_text(new_content + "\n", encoding="utf-8")
                logger.info("编辑任务内容: %s", f.name)
                return JSONResponse({"updated": f.name})
        return JSONResponse({"error": f"未找到可编辑的 pending 任务: {name}"}, status_code=404)

    # ── 批量操作 ──────────────────────────────────────────────

    @app.post("/api/tasks/batch/{action}")
    async def batch_action(action: str) -> JSONResponse:
        task_dir = workspace / config.task_dir
        fail_dir = workspace / config.fail_dir
        done_dir = workspace / config.done_dir

        if action == "retry-all-failed":
            retried = TaskQueue.retry_failed(task_dir, fail_dir)
            return JSONResponse({"retried": retried, "count": len(retried)})

        elif action == "clear-done":
            count = 0
            if done_dir.is_dir():
                for f in done_dir.glob("*.md"):
                    f.unlink()
                    count += 1
            logger.info("批量清理已完成任务: %d", count)
            return JSONResponse({"cleared": count})

        elif action == "recover":
            count = TaskQueue.recover_running(task_dir)
            logger.info("批量恢复 running 任务: %d", count)
            return JSONResponse({"recovered": count})

        return JSONResponse({"error": f"未知操作: {action}"}, status_code=400)

    # ── 配置 ─────────────────────────────────────────────────

    @app.get("/api/config")
    async def get_config() -> dict:
        from dataclasses import asdict
        return asdict(config)

    # ── SSE 实时日志 ──────────────────────────────────────────

    @app.get("/api/logs")
    async def stream_logs() -> StreamingResponse:
        async def _generator():
            last_seq = -1
            # 先发送已有日志
            for seq, msg in list(_log_buffer):
                yield f"data: {msg}\n\n"
                last_seq = seq
            while True:
                event = _log_event
                if event is None:
                    await asyncio.sleep(1)
                    continue
                event.clear()
                try:
                    await asyncio.wait_for(event.wait(), timeout=15)
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
                    continue
                for seq, msg in list(_log_buffer):
                    if seq > last_seq:
                        yield f"data: {msg}\n\n"
                        last_seq = seq

        return StreamingResponse(_generator(), media_type="text/event-stream")

    # ── 审批端点 ───────────────────────────────────────────────

    @app.get("/api/approvals")
    async def list_approvals() -> list[dict]:
        if approval_store is None:
            return []
        return [
            {
                "approval_id": item.approval_id,
                "task_name": item.task_name,
                "worker_id": item.worker_id,
                "plan_text": item.plan_text,
                "created_at": item.created_at.isoformat(),
            }
            for item in approval_store.list_pending()
        ]

    @app.post("/api/approvals/{approval_id}/approve")
    async def approve_plan(approval_id: str, request: Request) -> JSONResponse:
        if approval_store is None:
            return JSONResponse({"error": "approval store not configured"}, status_code=404)
        # 解析可选的 JSON body（feedback / selections）
        feedback = ""
        selections: dict = {}
        try:
            body = await request.json()
            feedback = body.get("feedback", "")
            selections = body.get("selections", {})
        except Exception:
            pass  # 无 body 时忽略
        if approval_store.approve(approval_id, feedback=feedback, selections=selections):
            return JSONResponse({"approved": approval_id})
        return JSONResponse({"error": f"未找到审批: {approval_id}"}, status_code=404)

    @app.post("/api/approvals/{approval_id}/reject")
    async def reject_plan(approval_id: str) -> JSONResponse:
        if approval_store is None:
            return JSONResponse({"error": "approval store not configured"}, status_code=404)
        if approval_store.reject(approval_id):
            return JSONResponse({"rejected": approval_id})
        return JSONResponse({"error": f"未找到审批: {approval_id}"}, status_code=404)

    # ── 执行历史 ──────────────────────────────────────────────

    @app.get("/api/executions")
    async def list_executions(limit: int = 50) -> list[dict]:
        if history is None:
            return []
        return history.list_recent(limit=limit)

    @app.get("/api/executions/detail/{execution_id}")
    async def get_execution_detail(execution_id: int) -> JSONResponse:
        if history is None:
            return JSONResponse({"error": "history not configured"}, status_code=404)
        record = history.get_by_id(execution_id)
        if record is None:
            return JSONResponse({"error": f"未找到执行记录: {execution_id}"}, status_code=404)
        return JSONResponse(record)

    @app.get("/api/executions/{task_name}")
    async def get_task_executions(task_name: str) -> list[dict]:
        if history is None:
            return []
        return history.get_by_task(task_name)

    # ── Worker 状态 ───────────────────────────────────────────

    @app.get("/api/workers")
    async def list_workers() -> dict:
        return get_all_worker_status()

    # ── 静态文件服务 (Vue 构建产物) ────────────────────────────

    static_dir = Path(__file__).parent / "static"
    if static_dir.is_dir():
        app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")

    return app


def start_server(config: Config, host: str = "0.0.0.0", port: int = 8080) -> None:
    """启动 Web 服务器，同时在后台线程运行任务循环."""
    import signal

    import uvicorn

    from .worker import shutdown_event

    # 创建共享的审批存储
    store = ApprovalStore() if (config.plan_mode and not config.plan_auto_approve) else None

    # 初始化执行历史
    workspace = Path(config.workspace).resolve()
    db_path = workspace / config.task_dir / ".vibe_history.db"
    history = ExecutionHistory(db_path)

    # 在主线程注册信号处理器，确保 shutdown_event 被设置
    # （run_loop 在后台线程中无法注册信号处理器）
    # 注意：uvicorn 启动后会覆盖此 handler，但在其 capture_signals
    # 退出时会 re-raise 信号，此时本 handler 被恢复并调用。
    def _shutdown_handler(signum, frame):
        shutdown_event.set()
        # 恢复默认处理器：再次 Ctrl+C 可强制退出
        signal.signal(signum, signal.SIG_DFL)

    signal.signal(signal.SIGINT, _shutdown_handler)

    # 后台线程运行任务循环
    loop_thread = threading.Thread(
        target=run_loop, args=(config,),
        kwargs={
            "approval_store": store,
            "continuous": True,
            "on_task_complete": history.record,
            "history": history,
        },
        daemon=True, name="vibe-loop",
    )
    loop_thread.start()
    logger.info("任务循环已在后台启动")

    app = create_app(config, approval_store=store, history=history)
    logger.info("Web 管理界面启动: http://%s:%d", host, port)
    uvicorn.run(app, host=host, port=port, log_level="info")
