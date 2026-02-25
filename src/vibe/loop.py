"""任务调度 — 扫描 tasks/ 目录，单/多 worker 并行执行."""

from __future__ import annotations

import atexit
import logging
import signal
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from .approval import ApprovalStore
from .config import Config
from .manager import check_docker_available, ensure_docker_image
from .task import TaskQueue
from .worker import shutdown_event, worker_loop
from .worker import update_worker_status
from .worktree import (
    MergeCoordinator,
    MergeStatus,
    cleanup_stale_worktrees,
    create_worktree,
    is_git_repo,
    remove_worktree,
)

logger = logging.getLogger(__name__)


def run_loop(
    config: Config,
    approval_store: ApprovalStore | None = None,
    *,
    continuous: bool = False,
    on_task_complete: Callable | None = None,
    history: object | None = None,
) -> None:
    """主调度循环: 创建任务队列，启动 worker.

    当 max_workers > 1 且 workspace 是 git 仓库时，为每个 worker 创建独立的
    git worktree 实现文件系统隔离。

    Args:
        continuous: 若为 True，处理完当前批次后不退出，等待 poll_interval 秒
                    后重新扫描新任务。适用于 serve 模式下持续运行。
        on_task_complete: 可选回调，任务完成后调用 (task_name, worker_id, result)
    """
    workspace = Path(config.workspace).resolve()
    config.workspace = str(workspace)

    # Docker 预检
    if config.use_docker:
        ok, msg = check_docker_available()
        if not ok:
            raise RuntimeError(f"Docker 隔离模式启用但 Docker 不可用: {msg}")
        scaffold_dir = Path(__file__).resolve().parent.parent.parent  # src/vibe -> src -> project root
        ok, msg = ensure_docker_image(config.docker_image, scaffold_dir)
        if not ok:
            raise RuntimeError(f"Docker 镜像准备失败: {msg}")
        logger.info("Docker 隔离模式已启用，镜像: %s", config.docker_image)

    # 注册信号处理器，优雅关闭
    def _signal_handler(signum, frame):
        sig_name = signal.Signals(signum).name
        logger.info("收到信号 %s，正在优雅关闭...", sig_name)
        shutdown_event.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(sig, _signal_handler)
        except (OSError, ValueError):
            pass  # 非主线程中无法注册信号处理器

    task_dir = workspace / config.task_dir

    # 注册 atexit 清理: 恢复孤立的 .running 任务
    def _atexit_recover():
        if task_dir.is_dir():
            count = TaskQueue.recover_running(task_dir)
            if count:
                logger.info("atexit: 已恢复 %d 个孤立的 .running 任务", count)

    atexit.register(_atexit_recover)

    logger.info("Vibe Loop 启动，工作目录: %s", workspace)
    logger.info("任务目录: %s", task_dir)
    logger.info("Worker 数量: %d", config.max_workers)
    if continuous:
        logger.info("持续轮询模式已启用，间隔: %d 秒", config.poll_interval)

    queue = TaskQueue(config, workspace)

    while True:
        # 检查是否收到关闭信号
        if shutdown_event.is_set():
            break

        # 检查是否有待执行任务
        pending = sorted(task_dir.glob("*.md"))
        if not pending:
            if not continuous:
                logger.info("没有待执行的任务，退出")
                return
            # continuous 模式: 等待后重新扫描
            if shutdown_event.wait(timeout=config.poll_interval):
                break  # 收到关闭信号
            continue

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
            worker_loop(
                "w0", config, queue,
                approval_store=approval_store,
                on_task_complete=on_task_complete,
                history=history,
            )
        elif use_wt:
            _run_with_worktrees(
                config, queue, workspace,
                approval_store=approval_store,
                on_task_complete=on_task_complete,
                history=history,
            )
        else:
            _run_shared(
                config, queue,
                approval_store=approval_store,
                on_task_complete=on_task_complete,
                history=history,
            )

        logger.info("=" * 60)
        logger.info("Vibe Loop 完成，所有任务已处理")

        if not continuous:
            return

        # continuous 模式: 等待后重新扫描
        if shutdown_event.wait(timeout=config.poll_interval):
            break  # 收到关闭信号

    logger.info("Vibe Loop 收到关闭信号，退出")


def _run_with_worktrees(
    config: Config,
    queue: TaskQueue,
    workspace: Path,
    approval_store: ApprovalStore | None = None,
    on_task_complete: Callable | None = None,
    history: object | None = None,
) -> None:
    """多 worker + git worktree 隔离模式.

    每个任务完成后立即 rebase + ff-merge（per-task merge），
    而非等所有 worker 完成后批量合并。
    """
    worktrees: dict[str, Path] = {}

    # 1. 为每个 worker 创建 worktree
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
            _run_shared(config, queue, approval_store=approval_store, on_task_complete=on_task_complete, history=history)
            return

    # 2. 创建合并协调器（传入冲突解决配置）
    coordinator = MergeCoordinator(
        workspace,
        resolve_conflicts=config.resolve_conflicts,
        conflict_timeout=config.conflict_timeout,
        use_docker=config.use_docker,
        docker_image=config.docker_image,
        docker_extra_args=config.docker_extra_args,
        shutdown_event=shutdown_event,
    )

    # 3. 构建每个 worker 的合并回调
    def _make_merge_cb(wid: str, wt_path: Path) -> Callable[[str, str], bool]:
        def cb(task_name: str, worker_id: str) -> bool:
            update_worker_status(worker_id, phase="merging", task=task_name)
            result = coordinator.merge_task(wt_path, task_name)
            if result.status in (MergeStatus.SUCCESS, MergeStatus.NO_CHANGES):
                return True
            if result.status == MergeStatus.CONFLICT:
                logger.warning(
                    "[%s] 任务 %s 合并冲突，重置 worktree: %s",
                    worker_id, task_name,
                    result.conflict_files or "unknown files",
                )
                coordinator.refresh_worktree(wt_path)
                return False
            # ERROR
            logger.error("[%s] 任务 %s 合并错误: %s", worker_id, task_name, result.message)
            return False
        return cb

    # 4. 构建每个 worker 的 pre-task sync 回调
    def _make_sync_cb(wt_path: Path) -> Callable[[str], None]:
        def cb(worker_id: str) -> None:
            coordinator.sync_worktree(wt_path)
        return cb

    # 5. 启动 workers（传入 on_task_success + on_before_task）
    try:
        with ThreadPoolExecutor(max_workers=config.max_workers) as pool:
            futures = {
                pool.submit(
                    worker_loop, wid, config, queue, wt_path,
                    approval_store=approval_store,
                    on_task_complete=on_task_complete,
                    on_task_success=_make_merge_cb(wid, wt_path),
                    on_before_task=_make_sync_cb(wt_path),
                    history=history,
                ): wid
                for wid, wt_path in worktrees.items()
            }
            for f in as_completed(futures):
                f.result()  # 传播异常
    finally:
        # 6. 无条件清理所有 worktrees（合并已在 per-task 回调中完成）
        for wid, wt_path in worktrees.items():
            remove_worktree(workspace, wt_path)


def _run_shared(
    config: Config,
    queue: TaskQueue,
    approval_store: ApprovalStore | None = None,
    on_task_complete: Callable | None = None,
    history: object | None = None,
) -> None:
    """多 worker 共享 workspace 模式（非 git repo 降级）."""
    with ThreadPoolExecutor(max_workers=config.max_workers) as pool:
        futures = [
            pool.submit(
                worker_loop, f"w{i}", config, queue,
                approval_store=approval_store,
                on_task_complete=on_task_complete,
                history=history,
            )
            for i in range(config.max_workers)
        ]
        for f in as_completed(futures):
            f.result()  # 传播异常
