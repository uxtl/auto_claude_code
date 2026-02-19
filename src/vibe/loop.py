"""任务调度 — 扫描 tasks/ 目录，单/多 worker 并行执行."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from .approval import ApprovalStore
from .config import Config
from .task import TaskQueue
from .worker import worker_loop
from .worktree import (
    cleanup_stale_worktrees,
    commit_and_merge,
    create_worktree,
    is_git_repo,
    remove_worktree,
)

logger = logging.getLogger(__name__)


def run_loop(config: Config, approval_store: ApprovalStore | None = None) -> None:
    """主调度循环: 创建任务队列，启动 worker.

    当 max_workers > 1 且 workspace 是 git 仓库时，为每个 worker 创建独立的
    git worktree 实现文件系统隔离。
    """
    workspace = Path(config.workspace).resolve()
    config.workspace = str(workspace)

    logger.info("Vibe Loop 启动，工作目录: %s", workspace)
    logger.info("任务目录: %s", workspace / config.task_dir)
    logger.info("Worker 数量: %d", config.max_workers)

    queue = TaskQueue(config, workspace)

    # 检查是否有待执行任务
    task_dir = workspace / config.task_dir
    pending = sorted(task_dir.glob("*.md"))
    if not pending:
        logger.info("没有待执行的任务，退出")
        return

    logger.info("发现 %d 个待执行任务", len(pending))

    use_wt = (
        config.max_workers > 1
        and config.use_worktree
        and is_git_repo(workspace)
    )

    if use_wt:
        logger.info("Git worktree 模式启用，为每个 worker 创建隔离工作树")
        cleanup_stale_worktrees(workspace)
    elif config.max_workers > 1 and config.use_worktree and not is_git_repo(workspace):
        logger.warning(
            "工作目录不是 git 仓库，无法使用 worktree 隔离。"
            "多 worker 将共享同一目录，可能产生冲突！"
        )

    if config.max_workers == 1:
        # 单 worker 快速路径，无线程开销，无需 worktree
        worker_loop("w0", config, queue, approval_store=approval_store)
    elif use_wt:
        _run_with_worktrees(config, queue, workspace, approval_store=approval_store)
    else:
        _run_shared(config, queue, approval_store=approval_store)

    logger.info("=" * 60)
    logger.info("Vibe Loop 完成，所有任务已处理")


def _run_with_worktrees(
    config: Config,
    queue: TaskQueue,
    workspace: Path,
    approval_store: ApprovalStore | None = None,
) -> None:
    """多 worker + git worktree 隔离模式."""
    worktrees: dict[str, Path] = {}

    # 为每个 worker 创建 worktree
    for i in range(config.max_workers):
        wid = f"w{i}"
        try:
            wt_path = create_worktree(workspace, wid)
            worktrees[wid] = wt_path
        except RuntimeError as e:
            logger.error("为 %s 创建 worktree 失败: %s", wid, e)
            # 清理已创建的 worktree 并降级
            for created_wid, created_path in worktrees.items():
                remove_worktree(workspace, created_path)
            logger.warning("降级为共享 workspace 模式")
            _run_shared(config, queue)
            return

    # 启动 workers
    with ThreadPoolExecutor(max_workers=config.max_workers) as pool:
        futures = {
            pool.submit(
                worker_loop, wid, config, queue, wt_path,
                approval_store=approval_store,
            ): wid
            for wid, wt_path in worktrees.items()
        }
        for f in as_completed(futures):
            f.result()  # 传播异常

    # 逐个 merge worktree 的更改回主分支
    for wid, wt_path in worktrees.items():
        commit_and_merge(workspace, wt_path, f"vibe: {wid} 任务完成")
        remove_worktree(workspace, wt_path)


def _run_shared(
    config: Config,
    queue: TaskQueue,
    approval_store: ApprovalStore | None = None,
) -> None:
    """多 worker 共享 workspace 模式（非 git repo 降级）."""
    with ThreadPoolExecutor(max_workers=config.max_workers) as pool:
        futures = [
            pool.submit(
                worker_loop, f"w{i}", config, queue,
                approval_store=approval_store,
            )
            for i in range(config.max_workers)
        ]
        for f in as_completed(futures):
            f.result()  # 传播异常
