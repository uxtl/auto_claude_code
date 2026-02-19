"""任务模型 + 线程安全队列 — 文件级锁保证并行安全."""

import logging
import os
import re
import tempfile
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .config import Config

logger = logging.getLogger(__name__)

_RETRY_PATTERN = re.compile(r"<!--\s*RETRY:\s*(\d+)\s*-->")


@dataclass
class Task:
    """单个任务."""

    path: Path
    name: str
    content: str
    retries: int = 0


class TaskQueue:
    """线程安全的文件系统任务队列.

    使用文件重命名（.running.{worker_id}）作为认领标记，
    threading.Lock 保护扫描 + 重命名的原子性。
    """

    def __init__(self, config: Config, workspace: Path) -> None:
        self._lock = threading.Lock()
        self._config = config
        self._workspace = workspace
        self._task_dir = workspace / config.task_dir
        self._done_dir = workspace / config.done_dir
        self._fail_dir = workspace / config.fail_dir
        # 确保目录存在
        self._done_dir.mkdir(parents=True, exist_ok=True)
        self._fail_dir.mkdir(parents=True, exist_ok=True)

    def claim_next(self, worker_id: str) -> Task | None:
        """原子性地认领下一个任务: rename task.md → task.md.running.{worker_id}."""
        with self._lock:
            pending = sorted(self._task_dir.glob("*.md"))
            if not pending:
                return None

            task_file = pending[0]
            running_name = f"{task_file.name}.running.{worker_id}"
            running_path = self._task_dir / running_name

            try:
                task_file.rename(running_path)
            except OSError as e:
                logger.warning("认领任务 %s 失败: %s", task_file.name, e)
                return None

        # 读取内容（在锁外完成，减少持锁时间）
        try:
            file_size = running_path.stat().st_size
        except OSError:
            file_size = 0
        if file_size > _MAX_TASK_FILE_SIZE:
            logger.error(
                "任务文件 %s 过大 (%d bytes > %d)，跳过",
                running_path.name, file_size, _MAX_TASK_FILE_SIZE,
            )
            return None
        content = running_path.read_text(encoding="utf-8")
        retries = _extract_retry_count(content)

        return Task(
            path=running_path,
            name=task_file.stem,
            content=content,
            retries=retries,
        )

    def complete(self, task: Task) -> None:
        """将完成的任务移到 done/ 目录（带时间戳）."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        dest = self._done_dir / f"{timestamp}_{task.name}.md"
        try:
            task.path.rename(dest)
            logger.info("任务已归档: %s → %s", task.name, dest.name)
        except OSError as e:
            logger.error("归档任务 %s 失败: %s", task.name, e)

    def fail(self, task: Task, error: str) -> None:
        """处理失败任务: 重试次数未达上限则重新排队，否则移到 failed/.

        使用 tempfile + os.replace() 原子写入模式，确保崩溃时不会丢失任务数据。
        """
        new_retries = task.retries + 1

        if new_retries < self._config.max_retries:
            # 更新重试计数，改名回 .md 重新排队
            content = _set_retry_count(task.content, new_retries)
            fail_header = (
                f"<!-- FAILED at {datetime.now().isoformat()} -->\n"
                f"<!-- Error: {error} -->\n"
            )
            content = fail_header + content
            dest = self._task_dir / f"{task.name}.md"
            _atomic_write(dest, content)
            try:
                task.path.unlink()
            except OSError:
                pass
            logger.info(
                "任务 %s 将重试 (%d/%d)",
                task.name,
                new_retries,
                self._config.max_retries,
            )
        else:
            # 超过重试次数，移到 failed/
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            dest = self._fail_dir / f"{timestamp}_{task.name}.md"
            fail_header = (
                f"<!-- FINAL FAILURE at {datetime.now().isoformat()} -->\n"
                f"<!-- Error: {error} -->\n"
                f"<!-- Retries exhausted: {new_retries}/{self._config.max_retries} -->\n"
            )
            content = fail_header + task.content
            _atomic_write(dest, content)
            try:
                task.path.unlink()
            except OSError:
                pass
            logger.info(
                "任务 %s 重试次数耗尽，已移至 failed/: %s",
                task.name,
                dest.name,
            )

    @staticmethod
    def retry_failed(task_dir: Path, fail_dir: Path, name: str | None = None) -> list[str]:
        """将失败任务清理后移回待执行队列。

        清除错误注释头（RETRY/FAILED/Error），去除时间戳文件名前缀。
        name=None 时重试所有失败任务。

        Returns:
            重试的文件名列表
        """
        if not fail_dir.is_dir():
            return []

        _ts_prefix = re.compile(r"^\d{8}_\d{6}(_\d{6})?_")
        _comment_prefixes = (
            "<!-- RETRY:",
            "<!-- FAILED",
            "<!-- FINAL FAILURE",
            "<!-- Error:",
            "<!-- Retries exhausted",
        )

        # 查找匹配的失败任务
        if name is not None:
            matches = [
                f for f in fail_dir.glob("*.md")
                if f.stem == name or _ts_prefix.sub("", f.stem) == name
            ]
        else:
            matches = sorted(fail_dir.glob("*.md"))

        retried: list[str] = []
        for src in matches:
            content = src.read_text(encoding="utf-8")
            clean_lines = [
                line for line in content.splitlines()
                if not any(line.strip().startswith(p) for p in _comment_prefixes)
            ]
            clean_content = "\n".join(clean_lines).strip() + "\n"

            dest_name = _ts_prefix.sub("", src.name)
            dest = task_dir / dest_name
            dest.write_text(clean_content, encoding="utf-8")
            src.unlink()
            retried.append(dest_name)
            logger.info("重试任务: %s → %s", src.name, dest_name)

        return retried

    @staticmethod
    def recover_running(task_dir: Path) -> int:
        """恢复所有 .running.* 文件为 .md（用于 crash 恢复）.

        Returns:
            恢复的任务数量
        """
        count = 0
        for running_file in sorted(task_dir.glob("*.md.running.*")):
            # 提取原始文件名: xxx.md.running.w0 → xxx.md
            original_name = running_file.name.split(".running.")[0]
            restored = task_dir / original_name
            if restored.exists():
                logger.warning("恢复冲突: %s 已存在，删除多余的 .running 文件", original_name)
                try:
                    running_file.unlink()
                except OSError as e:
                    logger.error("删除冲突 .running 文件失败: %s: %s", running_file.name, e)
                count += 1
                continue
            try:
                running_file.rename(restored)
                logger.info("已恢复: %s → %s", running_file.name, original_name)
                count += 1
            except OSError as e:
                logger.error("恢复失败: %s: %s", running_file.name, e)
        return count


_MAX_TASK_FILE_SIZE = 1024 * 1024  # 1 MB


def _atomic_write(dest: Path, content: str) -> None:
    """原子写入文件: 先写到临时文件，再 os.replace() 到目标路径."""
    fd, tmp_path = tempfile.mkstemp(dir=str(dest.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp_path, str(dest))
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _extract_retry_count(content: str) -> int:
    """从任务内容中提取重试次数."""
    match = _RETRY_PATTERN.search(content)
    return int(match.group(1)) if match else 0


def _set_retry_count(content: str, count: int) -> str:
    """设置或更新任务内容中的重试次数标记."""
    marker = f"<!-- RETRY: {count} -->"
    if _RETRY_PATTERN.search(content):
        return _RETRY_PATTERN.sub(marker, content)
    # 添加到内容开头
    return marker + "\n" + content
