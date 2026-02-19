"""测试 approval.py — ApprovalDecision, PendingApproval, ApprovalStore."""

import threading

from vibe.approval import ApprovalDecision, ApprovalStore, PendingApproval


class TestPendingApproval:
    def test_approve_sets_event(self):
        store = ApprovalStore()
        item = store.submit("task1", "w0", "plan text")
        assert item.decision == ApprovalDecision.PENDING
        item.approve()
        assert item.decision == ApprovalDecision.APPROVED
        assert item._event.is_set()

    def test_reject_sets_event(self):
        store = ApprovalStore()
        item = store.submit("task1", "w0", "plan text")
        item.reject()
        assert item.decision == ApprovalDecision.REJECTED
        assert item._event.is_set()

    def test_wait_blocks_then_resumes(self):
        store = ApprovalStore()
        item = store.submit("task1", "w0", "plan text")
        result = []

        def waiter():
            item.wait()
            result.append(item.decision)

        t = threading.Thread(target=waiter)
        t.start()
        # 确保线程阻塞了
        t.join(timeout=0.05)
        assert t.is_alive()  # 仍在等待

        item.approve()
        t.join(timeout=2)
        assert not t.is_alive()
        assert result == [ApprovalDecision.APPROVED]


class TestApprovalStore:
    def test_submit_and_list_pending(self):
        store = ApprovalStore()
        item = store.submit("task1", "w0", "plan A")
        pending = store.list_pending()
        assert len(pending) == 1
        assert pending[0].approval_id == item.approval_id

    def test_approve_removes_from_pending(self):
        store = ApprovalStore()
        item = store.submit("task1", "w0", "plan A")
        store.approve(item.approval_id)
        pending = store.list_pending()
        assert len(pending) == 0

    def test_reject(self):
        store = ApprovalStore()
        item = store.submit("task1", "w0", "plan A")
        store.reject(item.approval_id)
        assert item.decision == ApprovalDecision.REJECTED

    def test_approve_not_found(self):
        store = ApprovalStore()
        assert store.approve("nonexistent") is False

    def test_reject_not_found(self):
        store = ApprovalStore()
        assert store.reject("nonexistent") is False

    def test_remove(self):
        store = ApprovalStore()
        item = store.submit("task1", "w0", "plan A")
        store.remove(item.approval_id)
        assert store.get(item.approval_id) is None

    def test_get(self):
        store = ApprovalStore()
        item = store.submit("task1", "w0", "plan A")
        got = store.get(item.approval_id)
        assert got is item
        assert store.get("nonexistent") is None
