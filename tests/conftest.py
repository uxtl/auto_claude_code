"""共享 fixtures — 提供临时工作区、Config、TaskQueue."""

import pytest
from pathlib import Path

from vibe.config import Config
from vibe.task import TaskQueue


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """创建带 tasks/done/failed 目录结构的临时工作区."""
    (tmp_path / "tasks").mkdir()
    (tmp_path / "tasks" / "done").mkdir()
    (tmp_path / "tasks" / "failed").mkdir()
    return tmp_path


@pytest.fixture
def config(workspace: Path) -> Config:
    """返回指向 tmp workspace 的 Config."""
    return Config(workspace=str(workspace))


@pytest.fixture
def queue(config: Config, workspace: Path) -> TaskQueue:
    """返回初始化好的 TaskQueue."""
    return TaskQueue(config, workspace)
