"""Worker 循环 — 从队列认领任务并执行."""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Callable
from pathlib import Path

from . import manager
from .approval import ApprovalStore
from .config import Config
from .manager import TaskResult
from .task import Task, TaskQueue, extract_error_context

PROMPT_PREFIX = (
    "## 执行前准备\n"
    "1. 阅读 CLAUDE.md 了解项目架构和开发约定\n"
    "2. 阅读 PROGRESS.md 了解项目历史、已知问题和经验教训\n"
    "3. 注意：可能有其他 agent 在并行工作，只修改与本任务相关的文件\n\n"
    "## 任务内容\n\n"
)

PROMPT_SUFFIX = (
    "\n\n## 完成后要求\n"
    "1. 确保代码能运行，通过相关测试\n"
    "2. git add 并 commit 变更（message 格式见 CLAUDE.md）\n"
    "3. 更新 PROGRESS.md：\n"
    "   - 在「已完成任务」顶部追加本次记录（含改动文件、测试结果）\n"
    "   - 在「经验教训」中记录有价值的发现\n"
    "   - 在「已知问题」中记录发现但未处理的问题\n"
)

# 模块级关闭事件，供信号处理器通知所有 worker 退出
shutdown_event = threading.Event()


def build_prompt(task: Task | str) -> str:
    """构建完整的 prompt：注入读取 PROGRESS.md 和更新 PROGRESS.md 的指令.

    重试时注入错误上下文，帮助 Claude Code 避免重复同样的错误。
    接受 Task 对象或纯字符串（向后兼容）。
    """
    if isinstance(task, str):
        return PROMPT_PREFIX + task + PROMPT_SUFFIX

    if task.retries > 0:
        errors, clean_content = extract_error_context(task.content)
        if errors:
            error_block = "\n".join(f"- {e}" for e in errors)
            return (
                PROMPT_PREFIX
                + clean_content
                + f"\n\n## 上次执行失败信息\n\n"
                f"这是第 {task.retries + 1} 次尝试。之前失败的原因：\n{error_block}\n"
                f"请特别注意避免同样的错误。\n"
                + PROMPT_SUFFIX
            )
    return PROMPT_PREFIX + task.content + PROMPT_SUFFIX

logger = logging.getLogger(__name__)


def _docker_kwargs(config: Config) -> dict:
    """从 config 提取 Docker 相关参数为 dict，用于传递给 manager 函数."""
    return {
        "use_docker": config.use_docker,
        "docker_image": config.docker_image,
        "docker_extra_args": config.docker_extra_args,
    }


def _format_tool_detail(tool_name: str, tool_input: dict) -> str:
    """从工具调用中提取关键细节用于日志显示."""
    if tool_name in ("Read", "Write", "Edit"):
        return tool_input.get("file_path", "")
    if tool_name == "Bash":
        cmd = tool_input.get("command", "")
        return cmd[:80] + ("..." if len(cmd) > 80 else "")
    if tool_name in ("Grep", "Glob"):
        return tool_input.get("pattern", "")
    if tool_name == "Task":
        return tool_input.get("description", "")
    if tool_name == "WebFetch":
        return tool_input.get("url", "")
    return ""


def _make_verbose_callback(worker_id: str) -> Callable[[str], None]:
    """创建 verbose 回调闭包，解析 stream-json 事件并记录日志."""

    def _on_output(line: str) -> None:
        line = line.strip()
        if not line:
            return
        try:
            event = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            return

        event_type = event.get("type", "")

        if event_type == "assistant" and "message" in event:
            message = event["message"]
            if not isinstance(message, dict):
                return
            for block in message.get("content", []):
                if not isinstance(block, dict):
                    continue
                block_type = block.get("type", "")
                if block_type == "text":
                    text = block["text"].strip()
                    preview = text[:120] + ("..." if len(text) > 120 else "")
                    logger.info("[%s] 💬 %s", worker_id, preview)
                elif block_type == "tool_use":
                    name = block.get("name", "?")
                    detail = _format_tool_detail(name, block.get("input", {}))
                    if detail:
                        logger.info("[%s] 🔧 %s → %s", worker_id, name, detail)
                    else:
                        logger.info("[%s] 🔧 %s", worker_id, name)

        elif event_type == "result":
            result_data = event.get("result", "")
            if isinstance(result_data, str) and result_data.strip():
                preview = result_data.strip()[:120]
                if len(result_data.strip()) > 120:
                    preview += "..."
                logger.info("[%s] ✅ 结果: %s", worker_id, preview)

    return _on_output


def worker_loop(
    worker_id: str,
    config: Config,
    queue: TaskQueue,
    worktree: Path | None = None,
    approval_store: ApprovalStore | None = None,
) -> None:
    """单个 worker 的执行循环: 不断认领任务直到队列为空.

    Args:
        worker_id: Worker 标识（如 "w0", "w1"）
        config: 全局配置
        queue: 线程安全的任务队列
        worktree: 可选的 git worktree 路径，为 None 时使用 config.workspace
        approval_store: 可选的审批存储，plan_mode + 非 auto_approve 时使用
    """
    cwd = str(worktree) if worktree else config.workspace
    logger.info("[%s] Worker 启动, cwd=%s", worker_id, cwd)

    while not shutdown_event.is_set():
        task = queue.claim_next(worker_id)
        if task is None:
            logger.info("[%s] 队列为空，Worker 退出", worker_id)
            return

        logger.info("[%s] 认领任务: %s", worker_id, task.name)
        _execute_task(worker_id, config, queue, task, cwd, approval_store)

    logger.info("[%s] 收到关闭信号，Worker 退出", worker_id)


def _execute_task(
    worker_id: str,
    config: Config,
    queue: TaskQueue,
    task: Task,
    cwd: str,
    approval_store: ApprovalStore | None = None,
) -> None:
    """执行单个任务并处理结果."""
    prompt = build_prompt(task)
    docker_kw = _docker_kwargs(config)
    on_output = _make_verbose_callback(worker_id) if config.verbose else None

    if (
        config.plan_mode
        and not config.plan_auto_approve
        and approval_store is not None
    ):
        result = _execute_with_approval(
            worker_id, prompt, cwd, config.timeout, task.name, approval_store,
            shutdown_event=shutdown_event,
            on_output=on_output,
            **docker_kw,
        )
    elif config.plan_mode:
        result = manager.run_plan(
            prompt, cwd=cwd, timeout=config.timeout,
            shutdown_event=shutdown_event, on_output=on_output, **docker_kw,
        )
    else:
        result = manager.run_task(
            prompt, cwd=cwd, timeout=config.timeout,
            shutdown_event=shutdown_event, on_output=on_output, **docker_kw,
        )

    # 优先检查关闭信号：释放任务回队列而不是归档
    if shutdown_event.is_set():
        logger.info("[%s] 收到关闭信号，释放任务回队列: %s", worker_id, task.name)
        queue.release(task)
        return

    if result.success:
        logger.info(
            "[%s] 任务成功: %s (%.1fs, %d 文件变更)",
            worker_id,
            task.name,
            result.duration_seconds,
            len(result.files_changed),
        )
        queue.complete(task)
    else:
        logger.error(
            "[%s] 任务失败: %s — %s",
            worker_id,
            task.name,
            result.error,
        )
        queue.fail(task, result.error)


def _execute_with_approval(
    worker_id: str,
    prompt: str,
    cwd: str,
    timeout: int,
    task_name: str,
    approval_store: ApprovalStore,
    *,
    shutdown_event: threading.Event | None = None,
    on_output: Callable[[str], None] | None = None,
    use_docker: bool = False,
    docker_image: str = "auto-claude-code",
    docker_extra_args: str = "",
) -> TaskResult:
    """Plan 模式 + 人工审批: 生成计划 → 等待审批 → 执行."""
    import time

    docker_kw = {
        "use_docker": use_docker,
        "docker_image": docker_image,
        "docker_extra_args": docker_extra_args,
    }

    start_time = time.monotonic()

    # Step 1: 生成计划
    plan_result = manager.generate_plan(
        prompt, cwd=cwd, timeout=timeout,
        shutdown_event=shutdown_event, on_output=on_output, **docker_kw,
    )
    if not plan_result.success:
        return plan_result

    plan_text = plan_result.output

    # Step 2: 提交审批并等待
    logger.info("[%s] 计划已生成，等待人工审批: %s", worker_id, task_name)
    approval = approval_store.submit(task_name, worker_id, plan_text)

    remaining_timeout = timeout - int(time.monotonic() - start_time)
    if remaining_timeout < 60:
        remaining_timeout = 60

    approved = approval.wait(timeout=remaining_timeout)

    # 清理
    approval_store.remove(approval.approval_id)

    if not approved:
        logger.warning("[%s] 审批等待超时: %s", worker_id, task_name)
        return TaskResult(success=False, error="审批等待超时")

    from .approval import ApprovalDecision

    if approval.decision == ApprovalDecision.REJECTED:
        logger.info("[%s] 计划被拒绝: %s", worker_id, task_name)
        return TaskResult(success=False, error="用户拒绝计划")

    # Step 3: 执行计划
    logger.info("[%s] 计划已批准，开始执行: %s", worker_id, task_name)
    remaining_timeout = timeout - int(time.monotonic() - start_time)
    if remaining_timeout < 60:
        remaining_timeout = 60

    exec_result = manager.execute_plan(
        plan_text, cwd=cwd, timeout=remaining_timeout,
        shutdown_event=shutdown_event, on_output=on_output, **docker_kw,
    )
    exec_result.duration_seconds = time.monotonic() - start_time
    return exec_result
