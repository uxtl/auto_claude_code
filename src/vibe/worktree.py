"""Git worktree 生命周期管理 — 为每个 worker 提供隔离的工作树."""

import logging
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
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
    wt_dir = workspace / ".vibe-worktrees"
    wt_dir.mkdir(parents=True, exist_ok=True)
    wt_path = wt_dir / wt_name

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
    # 删除已合并的分支，防止 vibe/* 分支堆积
    del_result = _run_git(["branch", "-d", branch], workspace)
    if del_result.returncode != 0:
        logger.warning("删除已合并分支 %s 失败: %s", branch, del_result.stderr.strip())
    else:
        logger.debug("已删除已合并分支: %s", branch)
    return True


def cleanup_stale_worktrees(workspace: Path) -> None:
    """清理已失效的 worktree 引用."""
    result = _run_git(["worktree", "prune"], workspace)
    if result.returncode == 0:
        logger.debug("已清理过时的 worktree 引用")
    else:
        logger.warning("worktree prune 失败: %s", result.stderr.strip())


# ── Per-task rebase-merge coordinator ─────────────────────────


class MergeStatus(Enum):
    """合并操作的结果状态."""

    SUCCESS = "success"
    NO_CHANGES = "no_changes"
    CONFLICT = "conflict"
    ERROR = "error"


@dataclass
class MergeResult:
    """合并操作的结果."""

    status: MergeStatus
    message: str = ""
    conflict_files: list[str] | None = None


def _parse_conflict_files(stderr: str) -> list[str]:
    """从 rebase stderr 中提取冲突文件列表."""
    files: list[str] = []
    for line in stderr.splitlines():
        line = line.strip()
        if line.startswith("CONFLICT") and ":" in line:
            # e.g. "CONFLICT (content): Merge conflict in src/foo.py"
            parts = line.rsplit(" in ", 1)
            if len(parts) == 2:
                files.append(parts[1].strip())
    return files


class MergeCoordinator:
    """线程安全的 per-task rebase + ff-merge 协调器.

    每个任务完成后立即调用 merge_task() 将变更合入 main，
    而不是等所有 worker 完成后批量合并。

    两阶段合并:
    - Phase 1（无锁）: commit + rebase main + 冲突解决（只改 worktree 分支）
    - Phase 2（持锁）: re-rebase main + ff-merge（改 main）
    """

    def __init__(
        self,
        workspace: Path,
        *,
        resolve_conflicts: bool = False,
        conflict_timeout: int = 120,
        use_docker: bool = False,
        docker_image: str = "auto-claude-code",
        docker_extra_args: str = "",
        shutdown_event: threading.Event | None = None,
    ) -> None:
        self._workspace = workspace
        self._lock = threading.Lock()
        self._resolve_conflicts = resolve_conflicts
        self._conflict_timeout = conflict_timeout
        self._use_docker = use_docker
        self._docker_image = docker_image
        self._docker_extra_args = docker_extra_args
        self._shutdown_event = shutdown_event

    def merge_task(self, worktree_path: Path, task_name: str) -> MergeResult:
        """两阶段合并: 先无锁 commit+rebase，再持锁 re-rebase+ff-merge.

        Args:
            worktree_path: worktree 的路径
            task_name: 任务名称（用于 commit message）

        Returns:
            MergeResult 描述合并结果
        """
        # Phase 1（无锁）: commit + rebase + 冲突解决
        phase1 = self._commit_and_rebase(worktree_path, task_name)
        if phase1.status != MergeStatus.SUCCESS:
            return phase1  # NO_CHANGES / CONFLICT / ERROR

        # Phase 2（持锁）: re-rebase + ff-merge
        with self._lock:
            return self._rebase_and_merge_locked(worktree_path, task_name)

    def _commit_and_rebase(self, worktree_path: Path, task_name: str) -> MergeResult:
        """Phase 1（无锁）: 检测变更 → commit → rebase main → 冲突解决."""
        # 1. 检测未提交的变更
        status = _run_git(["status", "--porcelain"], worktree_path)
        has_uncommitted = bool(status.stdout.strip())

        # 2. 检测已提交但未合并到 main 的 commits
        log_result = _run_git(["log", "main..HEAD", "--oneline"], worktree_path)
        has_prior_commits = bool(log_result.stdout.strip())

        # 3. 都为空 → 无变更
        if not has_uncommitted and not has_prior_commits:
            return MergeResult(status=MergeStatus.NO_CHANGES, message="无变更")

        # 4. 若有未提交变更 → add + commit
        if has_uncommitted:
            _run_git(["add", "-A"], worktree_path)
            commit_result = _run_git(
                ["commit", "-m", f"vibe: {task_name}"],
                worktree_path,
            )
            if commit_result.returncode != 0:
                # "nothing to commit" 不算错误 — 可能 Claude 已经 commit 了
                if "nothing to commit" in commit_result.stdout:
                    if not has_prior_commits:
                        return MergeResult(
                            status=MergeStatus.NO_CHANGES,
                            message="nothing to commit",
                        )
                    # 有先前 commits，继续 rebase
                else:
                    return MergeResult(
                        status=MergeStatus.ERROR,
                        message=f"commit 失败: {commit_result.stderr.strip()}",
                    )

        # 5. rebase main
        rebase_result = _run_git(["rebase", "main"], worktree_path)
        if rebase_result.returncode != 0:
            conflict_files = _parse_conflict_files(rebase_result.stderr)

            # 尝试 Claude 冲突解决
            if self._resolve_conflicts:
                logger.info(
                    "任务 %s rebase 冲突，调用 Claude 解决: %s",
                    task_name, conflict_files,
                )
                from .manager import resolve_conflicts as _resolve

                resolve_result = _resolve(
                    worktree_path,
                    timeout=self._conflict_timeout,
                    use_docker=self._use_docker,
                    docker_image=self._docker_image,
                    docker_extra_args=self._docker_extra_args,
                    shutdown_event=self._shutdown_event,
                )

                if resolve_result.success and not self._is_rebase_in_progress(worktree_path):
                    logger.info("任务 %s 冲突已由 Claude 解决", task_name)
                    return MergeResult(status=MergeStatus.SUCCESS, message="冲突已解决")

                # Claude 解决失败 → abort
                logger.warning("任务 %s Claude 冲突解决失败，abort rebase", task_name)
                _run_git(["rebase", "--abort"], worktree_path)
                return MergeResult(
                    status=MergeStatus.CONFLICT,
                    message=f"rebase 冲突（Claude 解决失败）: {rebase_result.stderr.strip()}",
                    conflict_files=conflict_files,
                )

            # resolve_conflicts=False → 直接 abort
            _run_git(["rebase", "--abort"], worktree_path)
            return MergeResult(
                status=MergeStatus.CONFLICT,
                message=f"rebase 冲突: {rebase_result.stderr.strip()}",
                conflict_files=conflict_files,
            )

        return MergeResult(status=MergeStatus.SUCCESS, message="Phase 1 完成")

    def _rebase_and_merge_locked(self, worktree_path: Path, task_name: str) -> MergeResult:
        """Phase 2（持锁）: re-rebase main + ff-merge."""
        # 1. re-rebase main（追上 Phase 1 期间其他 worker 的合入）
        rebase_result = _run_git(["rebase", "main"], worktree_path)
        if rebase_result.returncode != 0:
            # Phase 2 冲突不调用 Claude，避免死循环
            conflict_files = _parse_conflict_files(rebase_result.stderr)
            _run_git(["rebase", "--abort"], worktree_path)
            return MergeResult(
                status=MergeStatus.CONFLICT,
                message=f"Phase 2 re-rebase 冲突: {rebase_result.stderr.strip()}",
                conflict_files=conflict_files,
            )

        # 2. 获取 worktree 分支名
        branch = _get_worktree_branch(worktree_path)
        if not branch:
            return MergeResult(
                status=MergeStatus.ERROR,
                message="无法获取 worktree 分支名",
            )

        # 3. ff-merge 到 main
        merge_result = _run_git(
            ["merge", "--ff-only", branch], self._workspace
        )
        if merge_result.returncode != 0:
            return MergeResult(
                status=MergeStatus.ERROR,
                message=f"ff-merge 失败: {merge_result.stderr.strip()}",
            )

        logger.info("已合并任务 %s 到 main (分支: %s)", task_name, branch)
        return MergeResult(status=MergeStatus.SUCCESS, message=f"已合并 {branch}")

    @staticmethod
    def _is_rebase_in_progress(worktree_path: Path) -> bool:
        """检查 rebase 是否仍在进行中."""
        # 检查 .git/rebase-merge 或 .git/rebase-apply 目录
        # 对于 worktree，git dir 通常在 .git 文件指向的位置
        result = _run_git(["rev-parse", "--git-dir"], worktree_path)
        if result.returncode != 0:
            return True  # 保守估计
        git_dir = Path(result.stdout.strip())
        if not git_dir.is_absolute():
            git_dir = worktree_path / git_dir
        return (git_dir / "rebase-merge").exists() or (git_dir / "rebase-apply").exists()

    def sync_worktree(self, worktree_path: Path) -> bool:
        """任务开始前同步到最新 main（无锁）.

        Args:
            worktree_path: worktree 的路径

        Returns:
            True 表示同步成功
        """
        result = _run_git(["rebase", "main"], worktree_path)
        if result.returncode != 0:
            logger.warning(
                "sync_worktree rebase 冲突，重置到 main: %s",
                worktree_path,
            )
            _run_git(["rebase", "--abort"], worktree_path)
            _run_git(["reset", "--hard", "main"], worktree_path)
        return True

    def refresh_worktree(self, worktree_path: Path) -> bool:
        """冲突后重置 worktree 到最新 main.

        Args:
            worktree_path: worktree 的路径

        Returns:
            True 表示成功重置
        """
        result = _run_git(["reset", "--hard", "main"], worktree_path)
        if result.returncode != 0:
            logger.error(
                "重置 worktree %s 失败: %s",
                worktree_path,
                result.stderr.strip(),
            )
            return False
        logger.info("已重置 worktree %s 到 main", worktree_path)
        return True
