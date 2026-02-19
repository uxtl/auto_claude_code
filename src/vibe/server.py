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
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse

from .approval import ApprovalStore
from .config import Config, load_config
from .loop import run_loop
from .task import TaskQueue

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
            loop.call_soon_threadsafe(event.set)


def _install_log_handler() -> None:
    handler = _SSELogHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S"))
    logging.getLogger("vibe").addHandler(handler)
    logging.getLogger("vibe").setLevel(logging.DEBUG)


def create_app(
    config: Config | None = None,
    approval_store: ApprovalStore | None = None,
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
        _loop = None
        _log_event = None

    app = FastAPI(title="Vibe Manager", version="0.2.0", lifespan=_lifespan)

    # ── 任务列表 ─────────────────────────────────────────────

    def _scan_tasks() -> list[dict]:
        """扫描文件系统，返回所有任务的状态."""
        task_dir = workspace / config.task_dir
        done_dir = workspace / config.done_dir
        fail_dir = workspace / config.fail_dir
        tasks = []

        # pending
        for f in sorted(task_dir.glob("*.md")):
            if ".running." not in f.name:
                tasks.append({"name": f.stem, "status": "pending", "file": f.name})

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
                # 文件名格式: 20240101_120000_taskname.md
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

        task_dir = workspace / config.task_dir
        task_dir.mkdir(parents=True, exist_ok=True)

        with _task_num_lock:
            # 自动编号
            existing = sorted(task_dir.glob("*.md"))
            max_num = 0
            for f in existing:
                parts = f.stem.split("_", 1)
                try:
                    max_num = max(max_num, int(parts[0]))
                except ValueError:
                    pass
            next_num = max_num + 1

            slug = description[:30].replace(" ", "_").replace("/", "_")
            filename = f"{next_num:03d}_{slug}.md"
            (task_dir / filename).write_text(description + "\n", encoding="utf-8")
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
    async def approve_plan(approval_id: str) -> JSONResponse:
        if approval_store is None:
            return JSONResponse({"error": "approval store not configured"}, status_code=404)
        if approval_store.approve(approval_id):
            return JSONResponse({"approved": approval_id})
        return JSONResponse({"error": f"未找到审批: {approval_id}"}, status_code=404)

    @app.post("/api/approvals/{approval_id}/reject")
    async def reject_plan(approval_id: str) -> JSONResponse:
        if approval_store is None:
            return JSONResponse({"error": "approval store not configured"}, status_code=404)
        if approval_store.reject(approval_id):
            return JSONResponse({"rejected": approval_id})
        return JSONResponse({"error": f"未找到审批: {approval_id}"}, status_code=404)

    # ── HTML Dashboard ────────────────────────────────────────

    @app.get("/", response_class=HTMLResponse)
    async def dashboard() -> HTMLResponse:
        html_path = Path(__file__).parent / "dashboard.html"
        if not html_path.is_file():
            return HTMLResponse(
                "<h1>Dashboard not found</h1><p>dashboard.html is missing.</p>",
                status_code=500,
            )
        return HTMLResponse(html_path.read_text(encoding="utf-8"))

    return app


def start_server(config: Config, host: str = "0.0.0.0", port: int = 8080) -> None:
    """启动 Web 服务器，同时在后台线程运行任务循环."""
    import uvicorn

    # 创建共享的审批存储
    store = ApprovalStore() if (config.plan_mode and not config.plan_auto_approve) else None

    # 后台线程运行任务循环
    loop_thread = threading.Thread(
        target=run_loop, args=(config,), kwargs={"approval_store": store},
        daemon=True, name="vibe-loop",
    )
    loop_thread.start()
    logger.info("任务循环已在后台启动")

    app = create_app(config, approval_store=store)
    logger.info("Web 管理界面启动: http://%s:%d", host, port)
    uvicorn.run(app, host=host, port=port, log_level="info")
