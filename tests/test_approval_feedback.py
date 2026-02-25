"""测试 approval.py — 审批反馈支持."""

from vibe.approval import ApprovalDecision, ApprovalStore, PendingApproval


class TestPendingApprovalFeedback:
    def test_approve_with_feedback(self):
        item = PendingApproval(
            approval_id="abc",
            task_name="task1",
            worker_id="w0",
            plan_text="plan",
        )
        item.approve(feedback="do X instead", selections={"q1": "optB"})

        assert item.decision == ApprovalDecision.APPROVED
        assert item.feedback == "do X instead"
        assert item.selections == {"q1": "optB"}
        assert item._event.is_set()

    def test_approve_without_feedback(self):
        item = PendingApproval(
            approval_id="def",
            task_name="task2",
            worker_id="w0",
            plan_text="plan",
        )
        item.approve()

        assert item.decision == ApprovalDecision.APPROVED
        assert item.feedback == ""
        assert item.selections == {}

    def test_default_fields(self):
        item = PendingApproval(
            approval_id="ghi",
            task_name="task3",
            worker_id="w0",
            plan_text="plan",
        )
        assert item.feedback == ""
        assert item.selections == {}
        assert item.decision == ApprovalDecision.PENDING


class TestApprovalStoreFeedback:
    def test_store_approve_with_feedback(self):
        store = ApprovalStore()
        item = store.submit("task1", "w0", "plan text")
        ok = store.approve(item.approval_id, feedback="notes", selections={"k": "v"})
        assert ok is True
        assert item.feedback == "notes"
        assert item.selections == {"k": "v"}
        assert item.decision == ApprovalDecision.APPROVED

    def test_store_approve_without_feedback(self):
        store = ApprovalStore()
        item = store.submit("task2", "w0", "plan")
        ok = store.approve(item.approval_id)
        assert ok is True
        assert item.feedback == ""
        assert item.selections == {}

    def test_store_approve_not_found(self):
        store = ApprovalStore()
        ok = store.approve("nonexistent", feedback="x")
        assert ok is False
