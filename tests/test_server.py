"""测试 server.py — FastAPI HTTP 路由（TestClient）."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from vibe.approval import ApprovalStore
from vibe.config import Config
from vibe.history import ExecutionHistory
from vibe.manager import TaskResult
from vibe.server import create_app


@pytest.fixture
def history(workspace: Path) -> ExecutionHistory:
    db_path = workspace / "tasks" / ".vibe_history.db"
    return ExecutionHistory(db_path)


@pytest.fixture
def client(config: Config, workspace: Path, history: ExecutionHistory) -> TestClient:
    """创建 TestClient，指向 tmp workspace."""
    app = create_app(config, history=history)
    return TestClient(app)


class TestGetTasks:
    def test_empty(self, client: TestClient):
        resp = client.get("/api/tasks")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_mixed(self, client: TestClient, workspace: Path):
        # pending
        (workspace / "tasks" / "001_todo.md").write_text("todo", encoding="utf-8")
        # running
        (workspace / "tasks" / "002_run.md.running.w0").write_text("run", encoding="utf-8")
        # done
        (workspace / "tasks" / "done" / "20240101_120000_003_done.md").write_text("done", encoding="utf-8")
        # failed
        (workspace / "tasks" / "failed" / "20240101_120000_004_fail.md").write_text("fail", encoding="utf-8")

        resp = client.get("/api/tasks")
        data = resp.json()
        statuses = {t["status"] for t in data}
        assert "pending" in statuses
        assert "running" in statuses
        assert "done" in statuses
        assert "failed" in statuses
        # running task should include worker info
        running = [t for t in data if t["status"] == "running"]
        assert running[0]["worker"] == "w0"


class TestPostTask:
    def test_add(self, client: TestClient, workspace: Path):
        resp = client.post("/api/tasks", json={"description": "new task"})
        assert resp.status_code == 201
        data = resp.json()
        assert "filename" in data
        # 文件已创建
        task_dir = workspace / "tasks"
        md_files = list(task_dir.glob("*.md"))
        assert len(md_files) == 1

    def test_empty_description(self, client: TestClient):
        resp = client.post("/api/tasks", json={"description": ""})
        assert resp.status_code == 400

    def test_auto_number(self, client: TestClient):
        resp1 = client.post("/api/tasks", json={"description": "first"})
        resp2 = client.post("/api/tasks", json={"description": "second"})
        assert resp1.json()["number"] < resp2.json()["number"]

    def test_auto_number_with_non_numeric(self, client: TestClient, workspace: Path):
        """非数字前缀文件不影响编号."""
        (workspace / "tasks" / "readme.md").write_text("info", encoding="utf-8")
        resp = client.post("/api/tasks", json={"description": "test"})
        assert resp.status_code == 201
        assert resp.json()["number"] == 1

    def test_auto_number_scans_done(self, client: TestClient, workspace: Path):
        """编号扫描包含 done/ 目录."""
        (workspace / "tasks" / "done" / "20240101_120000_000000_005_old.md").write_text(
            "done", encoding="utf-8",
        )
        resp = client.post("/api/tasks", json={"description": "after done"})
        assert resp.status_code == 201
        assert resp.json()["number"] == 6


class TestPostTaskDependencies:
    def test_add_with_depends(self, client: TestClient, workspace: Path):
        """添加任务时传入依赖."""
        resp = client.post("/api/tasks", json={"description": "task A"})
        assert resp.status_code == 201

        resp2 = client.post("/api/tasks", json={"description": "task B", "depends": [1]})
        assert resp2.status_code == 201
        # 验证文件内容包含 DEPENDS 注释
        task_dir = workspace / "tasks"
        files = sorted(task_dir.glob("002_*.md"))
        assert len(files) == 1
        content = files[0].read_text(encoding="utf-8")
        assert "<!-- DEPENDS: 001 -->" in content

    def test_scan_tasks_enriched(self, client: TestClient, workspace: Path):
        """pending 任务返回描述和依赖信息."""
        (workspace / "tasks" / "001_hello.md").write_text(
            "<!-- DEPENDS: 999 -->\nDo something important\n", encoding="utf-8",
        )
        resp = client.get("/api/tasks")
        data = resp.json()
        pending = [t for t in data if t["status"] == "pending"]
        assert len(pending) == 1
        assert pending[0]["description"] == "Do something important"
        assert pending[0]["depends"] == [999]
        assert pending[0]["blocked"] is True
        assert 999 in pending[0]["unmet_deps"]

    def test_scan_tasks_not_blocked_when_done(self, client: TestClient, workspace: Path):
        """依赖已完成时 blocked=False."""
        (workspace / "tasks" / "done" / "20240101_120000_000000_001_dep.md").write_text(
            "done", encoding="utf-8",
        )
        (workspace / "tasks" / "002_task.md").write_text(
            "<!-- DEPENDS: 001 -->\nTask with met dep\n", encoding="utf-8",
        )
        resp = client.get("/api/tasks")
        data = resp.json()
        pending = [t for t in data if t["status"] == "pending"]
        assert len(pending) == 1
        assert pending[0]["blocked"] is False
        assert pending[0]["unmet_deps"] == []


class TestForceRun:
    def test_force_run(self, client: TestClient, workspace: Path):
        """force-run 移除 DEPENDS 注释."""
        (workspace / "tasks" / "001_blocked.md").write_text(
            "<!-- DEPENDS: 999 -->\nDo stuff\n", encoding="utf-8",
        )
        resp = client.post("/api/tasks/001_blocked/force-run")
        assert resp.status_code == 200
        content = (workspace / "tasks" / "001_blocked.md").read_text(encoding="utf-8")
        assert "DEPENDS" not in content
        assert "Do stuff" in content

    def test_force_run_not_found(self, client: TestClient):
        resp = client.post("/api/tasks/nonexistent/force-run")
        assert resp.status_code == 404


class TestRetryTask:
    def test_retry(self, client: TestClient, workspace: Path):
        fail_file = workspace / "tasks" / "failed" / "20240101_120000_001_broken.md"
        fail_file.write_text(
            "<!-- RETRY: 1 -->\n<!-- FAILED at 2024 -->\n<!-- Error: x -->\nreal content\n",
            encoding="utf-8",
        )

        resp = client.post("/api/tasks/001_broken/retry")
        assert resp.status_code == 200
        # 失败文件已删除
        assert not fail_file.exists()
        # 新文件出现在 tasks/
        restored = list((workspace / "tasks").glob("*.md"))
        assert len(restored) == 1
        content = restored[0].read_text(encoding="utf-8")
        assert "<!-- RETRY:" not in content

    def test_not_found(self, client: TestClient):
        resp = client.post("/api/tasks/nonexistent/retry")
        assert resp.status_code == 404


class TestDeleteTask:
    def test_delete(self, client: TestClient, workspace: Path):
        (workspace / "tasks" / "001_del.md").write_text("x", encoding="utf-8")
        resp = client.delete("/api/tasks/001_del")
        assert resp.status_code == 200
        assert not (workspace / "tasks" / "001_del.md").exists()

    def test_delete_failed(self, client: TestClient, workspace: Path):
        """可以删除 failed/ 中的任务."""
        (workspace / "tasks" / "failed" / "20240101_120000_bad.md").write_text("x", encoding="utf-8")
        resp = client.delete("/api/tasks/bad")
        assert resp.status_code == 200

    def test_not_found(self, client: TestClient):
        resp = client.delete("/api/tasks/nope")
        assert resp.status_code == 404


class TestGetConfig:
    def test_returns_dict(self, client: TestClient):
        resp = client.get("/api/config")
        assert resp.status_code == 200
        data = resp.json()
        assert "task_dir" in data
        assert "max_workers" in data


class TestTaskContent:
    def test_get_pending_content(self, client: TestClient, workspace: Path):
        (workspace / "tasks" / "001_test.md").write_text(
            "task content here\n", encoding="utf-8",
        )
        resp = client.get("/api/tasks/001_test/content")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "001_test"
        assert data["status"] == "pending"
        assert "task content here" in data["raw_content"]
        assert data["retry_count"] == 0

    def test_get_failed_content_with_errors(self, client: TestClient, workspace: Path):
        (workspace / "tasks" / "failed" / "20240101_120000_002_bad.md").write_text(
            "<!-- RETRY: 2 -->\n<!-- Error: something broke -->\noriginal task\n",
            encoding="utf-8",
        )
        resp = client.get("/api/tasks/002_bad/content")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "failed"
        assert data["retry_count"] == 2
        assert "something broke" in data["errors"]
        assert "original task" in data["clean_content"]

    def test_not_found(self, client: TestClient):
        resp = client.get("/api/tasks/nonexistent/content")
        assert resp.status_code == 404

    def test_edit_pending(self, client: TestClient, workspace: Path):
        (workspace / "tasks" / "001_edit.md").write_text("old\n", encoding="utf-8")
        resp = client.put(
            "/api/tasks/001_edit/content",
            json={"content": "new content"},
        )
        assert resp.status_code == 200
        content = (workspace / "tasks" / "001_edit.md").read_text(encoding="utf-8")
        assert "new content" in content

    def test_edit_empty(self, client: TestClient, workspace: Path):
        (workspace / "tasks" / "001_edit.md").write_text("old\n", encoding="utf-8")
        resp = client.put(
            "/api/tasks/001_edit/content",
            json={"content": ""},
        )
        assert resp.status_code == 400

    def test_edit_not_found(self, client: TestClient):
        resp = client.put(
            "/api/tasks/nonexistent/content",
            json={"content": "x"},
        )
        assert resp.status_code == 404


class TestBatchActions:
    def test_retry_all_failed(self, client: TestClient, workspace: Path):
        fail_dir = workspace / "tasks" / "failed"
        (fail_dir / "20240101_120000_a.md").write_text(
            "<!-- Error: x -->\ncontent a\n", encoding="utf-8",
        )
        (fail_dir / "20240101_120000_b.md").write_text(
            "<!-- Error: y -->\ncontent b\n", encoding="utf-8",
        )
        resp = client.post("/api/tasks/batch/retry-all-failed")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 2

    def test_clear_done(self, client: TestClient, workspace: Path):
        done_dir = workspace / "tasks" / "done"
        (done_dir / "20240101_120000_x.md").write_text("done", encoding="utf-8")
        (done_dir / "20240101_120000_y.md").write_text("done", encoding="utf-8")
        resp = client.post("/api/tasks/batch/clear-done")
        assert resp.status_code == 200
        assert resp.json()["cleared"] == 2
        assert list(done_dir.glob("*.md")) == []

    def test_recover(self, client: TestClient, workspace: Path):
        (workspace / "tasks" / "001_r.md.running.w0").write_text("x", encoding="utf-8")
        resp = client.post("/api/tasks/batch/recover")
        assert resp.status_code == 200
        assert resp.json()["recovered"] == 1

    def test_unknown_action(self, client: TestClient):
        resp = client.post("/api/tasks/batch/unknown")
        assert resp.status_code == 400


class TestExecutions:
    def test_list_empty(self, client: TestClient):
        resp = client.get("/api/executions")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_with_records(self, client: TestClient, history: ExecutionHistory):
        result = TaskResult(
            success=True, output="out", files_changed=["a.py"],
            tool_calls=[], duration_seconds=5.0, return_code=0,
        )
        history.record("task1", "w0", result)
        resp = client.get("/api/executions")
        data = resp.json()
        assert len(data) == 1
        assert data[0]["task_name"] == "task1"

    def test_get_by_task(self, client: TestClient, history: ExecutionHistory):
        r = TaskResult(success=True, output="ok", duration_seconds=1.0)
        history.record("alpha", "w0", r)
        history.record("beta", "w1", r)
        resp = client.get("/api/executions/alpha")
        data = resp.json()
        assert len(data) == 1
        assert data[0]["task_name"] == "alpha"

    def test_get_detail_by_id(self, client: TestClient, history: ExecutionHistory):
        r = TaskResult(
            success=True, output="detail out", duration_seconds=3.0,
            result_text="final result",
        )
        history.record("detail_task", "w0", r)
        rows = history.list_recent()
        exec_id = rows[0]["id"]
        resp = client.get(f"/api/executions/detail/{exec_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["task_name"] == "detail_task"
        assert data["result_text"] == "final result"

    def test_get_detail_not_found(self, client: TestClient):
        resp = client.get("/api/executions/detail/99999")
        assert resp.status_code == 404


class TestWorkers:
    def test_list_workers(self, client: TestClient):
        resp = client.get("/api/workers")
        assert resp.status_code == 200
        assert isinstance(resp.json(), dict)


class TestApprovalEndpoints:
    @pytest.fixture
    def approval_client(self, config: Config, history: ExecutionHistory) -> tuple[TestClient, ApprovalStore]:
        store = ApprovalStore()
        app = create_app(config, approval_store=store, history=history)
        return TestClient(app), store

    def test_list_approvals_empty(self, approval_client):
        client, store = approval_client
        resp = client.get("/api/approvals")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_approvals_with_pending(self, approval_client):
        client, store = approval_client
        store.submit("task1", "w0", "plan text here")
        resp = client.get("/api/approvals")
        data = resp.json()
        assert len(data) == 1
        assert data[0]["task_name"] == "task1"
        assert data[0]["plan_text"] == "plan text here"

    def test_approve_endpoint(self, approval_client):
        client, store = approval_client
        item = store.submit("task1", "w0", "plan")
        resp = client.post(f"/api/approvals/{item.approval_id}/approve")
        assert resp.status_code == 200
        assert "approved" in resp.json()

    def test_approve_with_feedback(self, approval_client):
        client, store = approval_client
        item = store.submit("task_fb", "w0", "plan text")
        resp = client.post(
            f"/api/approvals/{item.approval_id}/approve",
            json={"feedback": "Please also fix tests", "selections": {"q1": "option_a"}},
        )
        assert resp.status_code == 200
        assert "approved" in resp.json()
        # 验证 feedback 已存储在 item 上
        assert item.feedback == "Please also fix tests"
        assert item.selections == {"q1": "option_a"}

    def test_reject_endpoint(self, approval_client):
        client, store = approval_client
        item = store.submit("task1", "w0", "plan")
        resp = client.post(f"/api/approvals/{item.approval_id}/reject")
        assert resp.status_code == 200
        assert "rejected" in resp.json()

    def test_approve_not_found(self, approval_client):
        client, store = approval_client
        resp = client.post("/api/approvals/nonexistent/approve")
        assert resp.status_code == 404

    def test_reject_not_found(self, approval_client):
        client, store = approval_client
        resp = client.post("/api/approvals/nonexistent/reject")
        assert resp.status_code == 404

    def test_list_without_store(self, client: TestClient):
        """无 approval_store 时返回空列表."""
        resp = client.get("/api/approvals")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_approve_without_store(self, client: TestClient):
        """无 approval_store 时返回 404."""
        resp = client.post("/api/approvals/any/approve")
        assert resp.status_code == 404
