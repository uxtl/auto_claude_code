"""Worker 循环 — 从队列认领任务并执行."""

from __future__ import annotations

import logging
from pathlib import Path

from . import manager
from .approval import ApprovalStore
from .config import Config
from .manager import TaskResult
from .task import Task, TaskQueue

PROMPT_PREFIX = "先阅读 PROGRESS.md 了解项目历史和经验，然后执行以下任务：\n\n"
PROMPT_SUFFIX = "\n\n完成后，将本次经验教训更新到 PROGRESS.md。"


def build_prompt(task_content: str) -> str:
    """构建完整的 prompt：注入读取 PROGRESS.md 和更新 PROGRESS.md 的指令."""
    return PROMPT_PREFIX + task_content + PROMPT_SUFFIX

logger = logging.getLogger(__name__)


def _docker_kwargs(config: Config) -> dict:
    """从 config 提取 Docker 相关参数为 dict，用于传递给 manager 函数."""
    return {
        "use_docker": config.use_docker,
        "docker_image": config.docker_image,
        "docker_extra_args": config.docker_extra_args,
    }


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

    while True:
        task = queue.claim_next(worker_id)
        if task is None:
            logger.info("[%s] 队列为空，Worker 退出", worker_id)
            return

        logger.info("[%s] 认领任务: %s", worker_id, task.name)
        _execute_task(worker_id, config, queue, task, cwd, approval_store)


def _execute_task(
    worker_id: str,
    config: Config,
    queue: TaskQueue,
    task: Task,
    cwd: str,
    approval_store: ApprovalStore | None = None,
) -> None:
    """执行单个任务并处理结果."""
    prompt = build_prompt(task.content)
    docker_kw = _docker_kwargs(config)

    if (
        config.plan_mode
        and not config.plan_auto_approve
        and approval_store is not None
    ):
        result = _execute_with_approval(
            worker_id, prompt, cwd, config.timeout, task.name, approval_store,
            **docker_kw,
        )
    elif config.plan_mode:
        result = manager.run_plan(prompt, cwd=cwd, timeout=config.timeout, **docker_kw)
    else:
        result = manager.run_task(prompt, cwd=cwd, timeout=config.timeout, **docker_kw)

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
    plan_result = manager.generate_plan(prompt, cwd=cwd, timeout=timeout, **docker_kw)
    if not plan_result.success:
        return plan_result

    plan_text = plan_result.output

    # Step 2: 提交审批并等待
    logger.info("[%s] 计划已生成，等待人工审批: %s", worker_id, task_name)
    approval = approval_store.submit(task_name, worker_id, plan_text)

    approval.wait()  # 阻塞直到 approve/reject

    # 清理
    approval_store.remove(approval.approval_id)

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
        plan_text, cwd=cwd, timeout=remaining_timeout, **docker_kw,
    )
    exec_result.duration_seconds = time.monotonic() - start_time
    return exec_result
