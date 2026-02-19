"""Git worktree 生命周期管理 — 为每个 worker 提供隔离的工作树."""

import logging
import subprocess
import time
import uuid
from pathlib import Path

logger = logging.getLogger(__name__)


def _run_git(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    """执行 git 命令并返回结果."""
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=60,
    )


def is_git_repo(workspace: Path) -> bool:
    """检查目录是否为 git 仓库."""
    try:
        result = _run_git(["rev-parse", "--is-inside-work-tree"], workspace)
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def create_worktree(workspace: Path, worker_id: str) -> Path:
    """为 worker 创建独立的 git worktree.

    使用 --detach 避免分支命名冲突。worktree 创建在 /tmp 下以避免路径争用。
    返回 worktree 路径。
    """
    timestamp = int(time.time())
    uid = uuid.uuid4().hex[:6]
    wt_name = f"vibe-{worker_id}-{timestamp}-{uid}"
    wt_path = Path(f"/tmp/{wt_name}")

    # 创建 detached worktree（基于 HEAD）
    branch_name = f"vibe/{worker_id}-{timestamp}-{uid}"
    result = _run_git(
        ["worktree", "add", "-b", branch_name, str(wt_path), "HEAD"],
        workspace,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"创建 worktree 失败 ({worker_id}): {result.stderr.strip()}"
        )

    logger.info("[%s] 创建 worktree: %s (branch: %s)", worker_id, wt_path, branch_name)
    return wt_path


def remove_worktree(workspace: Path, worktree_path: Path) -> None:
    """移除指定的 worktree."""
    result = _run_git(["worktree", "remove", str(worktree_path), "--force"], workspace)
    if result.returncode != 0:
        logger.warning("移除 worktree %s 失败: %s", worktree_path, result.stderr.strip())
    else:
        logger.info("已移除 worktree: %s", worktree_path)


def _get_worktree_branch(worktree_path: Path) -> str | None:
    """获取 worktree 所在的分支名."""
    result = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], worktree_path)
    if result.returncode != 0:
        return None
    branch = result.stdout.strip()
    return branch if branch != "HEAD" else None


def commit_and_merge(
    workspace: Path, worktree_path: Path, message: str
) -> bool:
    """在 worktree 中提交更改，然后合并回主分支.

    Returns:
        True 表示合并成功，False 表示有冲突（保留分支供手动处理）。
    """
    # Step 1: 在 worktree 中检查是否有更改
    status = _run_git(["status", "--porcelain"], worktree_path)
    if not status.stdout.strip():
        logger.info("worktree %s 无更改，跳过提交", worktree_path)
        return True

    # Step 2: 在 worktree 中 add + commit
    _run_git(["add", "-A"], worktree_path)
    commit_result = _run_git(["commit", "-m", message], worktree_path)
    if commit_result.returncode != 0:
        logger.warning("worktree %s 提交失败: %s", worktree_path, commit_result.stderr.strip())
        return False

    # Step 3: 获取 worktree 分支名
    branch = _get_worktree_branch(worktree_path)
    if not branch:
        logger.warning("无法获取 worktree %s 的分支名", worktree_path)
        return False

    # Step 4: 在主 workspace 中 merge
    merge_result = _run_git(["merge", "--no-ff", branch, "-m", f"Merge {branch}: {message}"], workspace)
    if merge_result.returncode != 0:
        logger.error(
            "合并分支 %s 失败（可能有冲突）。请手动处理:\n"
            "  cd %s && git merge %s",
            branch, workspace, branch,
        )
        # 中止失败的 merge 以保持主 workspace 干净
        _run_git(["merge", "--abort"], workspace)
        return False

    logger.info("已合并分支 %s 到主分支", branch)
    return True


def cleanup_stale_worktrees(workspace: Path) -> None:
    """清理已失效的 worktree 引用."""
    result = _run_git(["worktree", "prune"], workspace)
    if result.returncode == 0:
        logger.debug("已清理过时的 worktree 引用")
    else:
        logger.warning("worktree prune 失败: %s", result.stderr.strip())
