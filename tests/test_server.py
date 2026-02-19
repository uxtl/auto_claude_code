"""测试 server.py — FastAPI HTTP 路由（TestClient）."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from vibe.approval import ApprovalStore
from vibe.config import Config
from vibe.server import create_app


@pytest.fixture
def client(config: Config, workspace: Path) -> TestClient:
    """创建 TestClient，指向 tmp workspace."""
    app = create_app(config)
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


class TestDashboard:
    def test_html(self, client: TestClient):
        resp = client.get("/")
        assert resp.status_code == 200
        assert "html" in resp.text.lower()


class TestApprovalEndpoints:
    @pytest.fixture
    def approval_client(self, config: Config) -> tuple[TestClient, ApprovalStore]:
        store = ApprovalStore()
        app = create_app(config, approval_store=store)
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
