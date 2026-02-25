"""测试 worktree.py — mock _run_git."""

import subprocess
import threading
from pathlib import Path
from unittest.mock import patch, call

from vibe.worktree import (
    MergeCoordinator,
    MergeResult,
    MergeStatus,
    _parse_conflict_files,
    cleanup_stale_worktrees,
    commit_and_merge,
    create_worktree,
    is_git_repo,
    remove_worktree,
)


def _cp(stdout="", stderr="", returncode=0):
    """创建 CompletedProcess 快捷方法."""
    return subprocess.CompletedProcess(
        args=["git"], stdout=stdout, stderr=stderr, returncode=returncode
    )


class TestIsGitRepo:
    def test_true(self, tmp_path: Path):
        with patch("vibe.worktree._run_git", return_value=_cp(stdout="true")):
            assert is_git_repo(tmp_path) is True

    def test_false(self, tmp_path: Path):
        with patch("vibe.worktree._run_git", return_value=_cp(returncode=1)):
            assert is_git_repo(tmp_path) is False

    def test_no_git(self, tmp_path: Path):
        with patch("vibe.worktree._run_git", side_effect=FileNotFoundError):
            assert is_git_repo(tmp_path) is False


class TestCreateWorktree:
    def test_success(self, tmp_path: Path):
        with patch("vibe.worktree._run_git", return_value=_cp()):
            path = create_worktree(tmp_path, "w0")
        assert "vibe-w0-" in str(path)

    def test_failure(self, tmp_path: Path):
        with patch("vibe.worktree._run_git", return_value=_cp(returncode=1, stderr="error")):
            try:
                create_worktree(tmp_path, "w0")
                assert False, "Should raise RuntimeError"
            except RuntimeError as e:
                assert "失败" in str(e)


class TestRemoveWorktree:
    def test_calls_correct_command(self, tmp_path: Path):
        wt = Path("/tmp/vibe-w0-12345")
        with patch("vibe.worktree._run_git", return_value=_cp()) as mock_git:
            remove_worktree(tmp_path, wt)
        mock_git.assert_called_once()
        args = mock_git.call_args[0][0]
        assert "worktree" in args
        assert "remove" in args


class TestCommitAndMerge:
    def test_no_changes(self, tmp_path: Path):
        """status 为空 → 返回 True，不 commit."""
        with patch("vibe.worktree._run_git", return_value=_cp(stdout="")):
            result = commit_and_merge(tmp_path, Path("/tmp/wt"), "msg")
        assert result is True

    def test_success(self, tmp_path: Path):
        """status→add→commit→branch→merge→branch -d 全链路."""
        responses = [
            _cp(stdout="M file.py"),     # status --porcelain
            _cp(),                        # add -A
            _cp(),                        # commit
            _cp(stdout="vibe/w0-123"),   # rev-parse branch
            _cp(),                        # merge
            _cp(),                        # branch -d
        ]
        with patch("vibe.worktree._run_git", side_effect=responses):
            result = commit_and_merge(tmp_path, Path("/tmp/wt"), "msg")
        assert result is True

    def test_merge_conflict(self, tmp_path: Path):
        """merge 失败 → abort + 返回 False."""
        responses = [
            _cp(stdout="M file.py"),     # status
            _cp(),                        # add
            _cp(),                        # commit
            _cp(stdout="vibe/w0-123"),   # branch
            _cp(returncode=1, stderr="conflict"),  # merge fails
            _cp(),                        # merge --abort
        ]
        with patch("vibe.worktree._run_git", side_effect=responses):
            result = commit_and_merge(tmp_path, Path("/tmp/wt"), "msg")
        assert result is False


class TestCleanupStale:
    def test_calls_prune(self, tmp_path: Path):
        with patch("vibe.worktree._run_git", return_value=_cp()) as mock_git:
            cleanup_stale_worktrees(tmp_path)
        args = mock_git.call_args[0][0]
        assert args == ["worktree", "prune"]


class TestParseConflictFiles:
    def test_extracts_files(self):
        stderr = (
            "CONFLICT (content): Merge conflict in src/foo.py\n"
            "CONFLICT (content): Merge conflict in src/bar.py\n"
            "error: could not apply abc1234\n"
        )
        assert _parse_conflict_files(stderr) == ["src/foo.py", "src/bar.py"]

    def test_empty_stderr(self):
        assert _parse_conflict_files("") == []

    def test_no_conflict_lines(self):
        assert _parse_conflict_files("error: something\nfatal: oops\n") == []


class TestMergeCoordinator:
    def test_merge_no_changes(self, tmp_path: Path):
        """status + log 都为空 → NO_CHANGES（Phase 1 终止，不进 Phase 2）."""
        coordinator = MergeCoordinator(tmp_path)
        responses = [
            _cp(stdout=""),   # status --porcelain
            _cp(stdout=""),   # log main..HEAD --oneline
        ]
        with patch("vibe.worktree._run_git", side_effect=responses):
            result = coordinator.merge_task(Path("/tmp/wt"), "task-1")
        assert result.status == MergeStatus.NO_CHANGES

    def test_merge_committed_changes(self, tmp_path: Path):
        """Claude 已 commit → Phase1: rebase → Phase2: re-rebase + ff-merge."""
        coordinator = MergeCoordinator(tmp_path)
        responses = [
            _cp(stdout=""),                     # Phase1: status --porcelain (clean)
            _cp(stdout="abc1234 some change"),  # Phase1: log main..HEAD (has commits)
            _cp(),                              # Phase1: rebase main
            _cp(),                              # Phase2: rebase main (re-rebase)
            _cp(stdout="vibe/w0-123"),          # Phase2: rev-parse --abbrev-ref HEAD
            _cp(),                              # Phase2: merge --ff-only
        ]
        with patch("vibe.worktree._run_git", side_effect=responses):
            result = coordinator.merge_task(Path("/tmp/wt"), "task-1")
        assert result.status == MergeStatus.SUCCESS

    def test_merge_uncommitted_changes(self, tmp_path: Path):
        """有未提交 → Phase1: add/commit/rebase → Phase2: re-rebase/ff-merge."""
        coordinator = MergeCoordinator(tmp_path)
        responses = [
            _cp(stdout="M file.py"),            # Phase1: status --porcelain
            _cp(stdout=""),                     # Phase1: log main..HEAD (no prior)
            _cp(),                              # Phase1: add -A
            _cp(),                              # Phase1: commit
            _cp(),                              # Phase1: rebase main
            _cp(),                              # Phase2: rebase main (re-rebase)
            _cp(stdout="vibe/w0-123"),          # Phase2: rev-parse --abbrev-ref HEAD
            _cp(),                              # Phase2: merge --ff-only
        ]
        with patch("vibe.worktree._run_git", side_effect=responses):
            result = coordinator.merge_task(Path("/tmp/wt"), "task-1")
        assert result.status == MergeStatus.SUCCESS

    def test_merge_conflict(self, tmp_path: Path):
        """Phase1 rebase 失败（resolve_conflicts=False）→ abort → CONFLICT."""
        coordinator = MergeCoordinator(tmp_path)
        conflict_stderr = "CONFLICT (content): Merge conflict in src/app.py\nerror: could not apply abc"
        responses = [
            _cp(stdout="M file.py"),            # status
            _cp(stdout=""),                     # log
            _cp(),                              # add -A
            _cp(),                              # commit
            _cp(returncode=1, stderr=conflict_stderr),  # rebase fails
            _cp(),                              # rebase --abort
        ]
        with patch("vibe.worktree._run_git", side_effect=responses):
            result = coordinator.merge_task(Path("/tmp/wt"), "task-1")
        assert result.status == MergeStatus.CONFLICT
        assert result.conflict_files == ["src/app.py"]

    def test_merge_ff_fails(self, tmp_path: Path):
        """Phase1 rebase OK → Phase2 ff-merge 失败 → ERROR."""
        coordinator = MergeCoordinator(tmp_path)
        responses = [
            _cp(stdout=""),                     # Phase1: status (clean)
            _cp(stdout="abc1234 change"),       # Phase1: log (has commits)
            _cp(),                              # Phase1: rebase main
            _cp(),                              # Phase2: rebase main (re-rebase)
            _cp(stdout="vibe/w0-123"),          # Phase2: branch name
            _cp(returncode=1, stderr="Not possible to fast-forward"),  # ff fails
        ]
        with patch("vibe.worktree._run_git", side_effect=responses):
            result = coordinator.merge_task(Path("/tmp/wt"), "task-1")
        assert result.status == MergeStatus.ERROR
        assert "ff-merge" in result.message

    def test_commit_fails(self, tmp_path: Path):
        """commit 失败（非 nothing-to-commit）→ ERROR（Phase 1 终止）."""
        coordinator = MergeCoordinator(tmp_path)
        responses = [
            _cp(stdout="M file.py"),            # status
            _cp(stdout=""),                     # log
            _cp(),                              # add -A
            _cp(returncode=1, stderr="author identity unknown"),  # commit fails
        ]
        with patch("vibe.worktree._run_git", side_effect=responses):
            result = coordinator.merge_task(Path("/tmp/wt"), "task-1")
        assert result.status == MergeStatus.ERROR
        assert "commit 失败" in result.message

    def test_nothing_to_commit_but_has_prior(self, tmp_path: Path):
        """commit 报 nothing 但有先前 commits → Phase1 rebase → Phase2 ff-merge."""
        coordinator = MergeCoordinator(tmp_path)
        responses = [
            _cp(stdout="M file.py"),            # Phase1: status (shows dirty)
            _cp(stdout="abc1234 prior change"), # Phase1: log (has prior)
            _cp(),                              # Phase1: add -A
            _cp(returncode=1, stdout="nothing to commit"),  # Phase1: commit "fails"
            _cp(),                              # Phase1: rebase main
            _cp(),                              # Phase2: rebase main (re-rebase)
            _cp(stdout="vibe/w0-123"),          # Phase2: branch name
            _cp(),                              # Phase2: merge --ff-only
        ]
        with patch("vibe.worktree._run_git", side_effect=responses):
            result = coordinator.merge_task(Path("/tmp/wt"), "task-1")
        assert result.status == MergeStatus.SUCCESS

    def test_nothing_to_commit_no_prior(self, tmp_path: Path):
        """commit 报 nothing 且无先前 commits → NO_CHANGES（Phase 1 终止）."""
        coordinator = MergeCoordinator(tmp_path)
        responses = [
            _cp(stdout="M file.py"),            # status (shows dirty but git add resolves)
            _cp(stdout=""),                     # log (no prior)
            _cp(),                              # add -A
            _cp(returncode=1, stdout="nothing to commit"),  # commit "fails"
        ]
        with patch("vibe.worktree._run_git", side_effect=responses):
            result = coordinator.merge_task(Path("/tmp/wt"), "task-1")
        assert result.status == MergeStatus.NO_CHANGES

    def test_refresh_worktree_success(self, tmp_path: Path):
        """reset --hard main 成功."""
        coordinator = MergeCoordinator(tmp_path)
        with patch("vibe.worktree._run_git", return_value=_cp()):
            assert coordinator.refresh_worktree(Path("/tmp/wt")) is True

    def test_refresh_worktree_failure(self, tmp_path: Path):
        """reset --hard main 失败."""
        coordinator = MergeCoordinator(tmp_path)
        with patch("vibe.worktree._run_git", return_value=_cp(returncode=1, stderr="error")):
            assert coordinator.refresh_worktree(Path("/tmp/wt")) is False

    def test_thread_safety(self, tmp_path: Path):
        """2 线程并发 → 都能完成."""
        coordinator = MergeCoordinator(tmp_path)
        call_order: list[str] = []
        order_lock = threading.Lock()

        def mock_run_git(args, cwd):
            cmd = args[0] if args else ""
            if cmd == "status":
                with order_lock:
                    call_order.append(f"status-{cwd}")
                return _cp(stdout="")
            if cmd == "log":
                return _cp(stdout="")
            return _cp()

        def merge_worker(name):
            with patch("vibe.worktree._run_git", side_effect=mock_run_git):
                coordinator.merge_task(Path(f"/tmp/{name}"), name)

        t1 = threading.Thread(target=merge_worker, args=("wt1",))
        t2 = threading.Thread(target=merge_worker, args=("wt2",))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        # Both threads completed
        assert len(call_order) == 2

    def test_conflict_resolved_by_claude(self, tmp_path: Path):
        """Phase 1 冲突 → Claude 解决成功 → Phase 2 ff-merge."""
        from vibe.manager import TaskResult

        coordinator = MergeCoordinator(
            tmp_path, resolve_conflicts=True, conflict_timeout=60,
        )
        conflict_stderr = "CONFLICT (content): Merge conflict in src/app.py"
        responses = [
            _cp(stdout=""),                     # Phase1: status (clean)
            _cp(stdout="abc1234 change"),       # Phase1: log (has commits)
            _cp(returncode=1, stderr=conflict_stderr),  # Phase1: rebase fails
            # After Claude resolves: _is_rebase_in_progress checks
            _cp(stdout="/tmp/wt/.git"),         # rev-parse --git-dir
            # Phase2: re-rebase + ff-merge
            _cp(),                              # Phase2: rebase main
            _cp(stdout="vibe/w0-123"),          # Phase2: rev-parse branch
            _cp(),                              # Phase2: merge --ff-only
        ]
        mock_resolve = TaskResult(success=True, output="resolved")
        with (
            patch("vibe.worktree._run_git", side_effect=responses),
            patch("vibe.manager.resolve_conflicts", return_value=mock_resolve),
        ):
            result = coordinator.merge_task(Path("/tmp/wt"), "task-1")
        assert result.status == MergeStatus.SUCCESS

    def test_conflict_resolution_fails(self, tmp_path: Path):
        """Claude 解决失败 → abort → CONFLICT."""
        from vibe.manager import TaskResult

        coordinator = MergeCoordinator(
            tmp_path, resolve_conflicts=True, conflict_timeout=60,
        )
        conflict_stderr = "CONFLICT (content): Merge conflict in src/app.py"
        responses = [
            _cp(stdout=""),                     # Phase1: status
            _cp(stdout="abc1234 change"),       # Phase1: log
            _cp(returncode=1, stderr=conflict_stderr),  # Phase1: rebase fails
            _cp(),                              # rebase --abort (after Claude fails)
        ]
        mock_resolve = TaskResult(success=False, error="could not resolve")
        with (
            patch("vibe.worktree._run_git", side_effect=responses),
            patch("vibe.manager.resolve_conflicts", return_value=mock_resolve),
        ):
            result = coordinator.merge_task(Path("/tmp/wt"), "task-1")
        assert result.status == MergeStatus.CONFLICT
        assert "Claude 解决失败" in result.message

    def test_conflict_resolution_disabled(self, tmp_path: Path):
        """resolve_conflicts=False → 直接 abort（不调 Claude）."""
        coordinator = MergeCoordinator(tmp_path, resolve_conflicts=False)
        conflict_stderr = "CONFLICT (content): Merge conflict in src/app.py"
        responses = [
            _cp(stdout=""),                     # status
            _cp(stdout="abc1234 change"),       # log
            _cp(returncode=1, stderr=conflict_stderr),  # rebase fails
            _cp(),                              # rebase --abort
        ]
        with (
            patch("vibe.worktree._run_git", side_effect=responses),
            patch("vibe.manager.resolve_conflicts") as mock_resolve,
        ):
            result = coordinator.merge_task(Path("/tmp/wt"), "task-1")
        assert result.status == MergeStatus.CONFLICT
        mock_resolve.assert_not_called()

    def test_phase2_rerebase_conflict(self, tmp_path: Path):
        """Phase 1 成功但 Phase 2 re-rebase 冲突 → CONFLICT（不调 Claude）."""
        coordinator = MergeCoordinator(
            tmp_path, resolve_conflicts=True, conflict_timeout=60,
        )
        conflict_stderr = "CONFLICT (content): Merge conflict in src/new.py"
        responses = [
            _cp(stdout=""),                     # Phase1: status
            _cp(stdout="abc1234 change"),       # Phase1: log
            _cp(),                              # Phase1: rebase main (OK)
            _cp(returncode=1, stderr=conflict_stderr),  # Phase2: re-rebase fails
            _cp(),                              # Phase2: rebase --abort
        ]
        with (
            patch("vibe.worktree._run_git", side_effect=responses),
            patch("vibe.manager.resolve_conflicts") as mock_resolve,
        ):
            result = coordinator.merge_task(Path("/tmp/wt"), "task-1")
        assert result.status == MergeStatus.CONFLICT
        assert "Phase 2" in result.message
        # Phase 2 不调用 Claude
        mock_resolve.assert_not_called()


class TestSyncWorktree:
    def test_sync_worktree_clean(self, tmp_path: Path):
        """rebase 成功 → 返回 True."""
        coordinator = MergeCoordinator(tmp_path)
        with patch("vibe.worktree._run_git", return_value=_cp()):
            assert coordinator.sync_worktree(Path("/tmp/wt")) is True

    def test_sync_worktree_conflict_resets(self, tmp_path: Path):
        """rebase 冲突 → abort + reset --hard main → 返回 True."""
        coordinator = MergeCoordinator(tmp_path)
        responses = [
            _cp(returncode=1, stderr="CONFLICT"),  # rebase main (fails)
            _cp(),                                  # rebase --abort
            _cp(),                                  # reset --hard main
        ]
        with patch("vibe.worktree._run_git", side_effect=responses) as mock_git:
            assert coordinator.sync_worktree(Path("/tmp/wt")) is True

        # 验证调用了 abort 和 reset
        calls = [c[0][0] for c in mock_git.call_args_list]
        assert calls[0] == ["rebase", "main"]
        assert calls[1] == ["rebase", "--abort"]
        assert calls[2] == ["reset", "--hard", "main"]
