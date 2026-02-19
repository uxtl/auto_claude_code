"""Plan 审批流程 — 同步原语 + 内存存储."""

import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class ApprovalDecision(Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


@dataclass
class PendingApproval:
    """一次待审批的计划."""

    approval_id: str
    task_name: str
    worker_id: str
    plan_text: str
    created_at: datetime = field(default_factory=datetime.now)
    decision: ApprovalDecision = ApprovalDecision.PENDING
    _event: threading.Event = field(default_factory=threading.Event, repr=False)

    def wait(self, timeout: float | None = None) -> bool:
        """阻塞直到被 approve/reject，返回 event 是否被 set."""
        return self._event.wait(timeout=timeout)

    def approve(self) -> None:
        self.decision = ApprovalDecision.APPROVED
        self._event.set()

    def reject(self) -> None:
        self.decision = ApprovalDecision.REJECTED
        self._event.set()


class ApprovalStore:
    """线程安全的审批存储."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._items: dict[str, PendingApproval] = {}

    def submit(self, task_name: str, worker_id: str, plan_text: str) -> PendingApproval:
        approval_id = uuid.uuid4().hex[:12]
        item = PendingApproval(
            approval_id=approval_id,
            task_name=task_name,
            worker_id=worker_id,
            plan_text=plan_text,
        )
        with self._lock:
            self._items[approval_id] = item
        return item

    def get(self, approval_id: str) -> PendingApproval | None:
        with self._lock:
            return self._items.get(approval_id)

    def list_pending(self) -> list[PendingApproval]:
        with self._lock:
            return [
                item for item in self._items.values()
                if item.decision == ApprovalDecision.PENDING
            ]

    def approve(self, approval_id: str) -> bool:
        with self._lock:
            item = self._items.get(approval_id)
            if item is None:
                return False
            item.approve()
            return True

    def reject(self, approval_id: str) -> bool:
        with self._lock:
            item = self._items.get(approval_id)
            if item is None:
                return False
            item.reject()
            return True

    def remove(self, approval_id: str) -> None:
        with self._lock:
            self._items.pop(approval_id, None)
