"""Claude Code 进程管理 — 启动、监控、解析结果."""

import json
import logging
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 600  # 10 分钟


@dataclass
class TaskResult:
    """Claude Code 单次执行的结构化结果."""

    success: bool
    output: str = ""
    error: str = ""
    files_changed: list[str] = field(default_factory=list)
    tool_calls: list[dict] = field(default_factory=list)
    duration_seconds: float = 0.0
    return_code: int | None = None


def _read_stream(stream, lines: list[str]) -> None:
    """在线程中读取子进程的输出流."""
    for raw_line in stream:
        line = raw_line.decode("utf-8", errors="replace").rstrip("\n")
        lines.append(line)
    stream.close()


def _parse_stream_json(lines: list[str]) -> TaskResult:
    """解析 Claude Code stream-json 输出，提取结构化信息."""
    output_parts: list[str] = []
    files_changed: list[str] = []
    tool_calls: list[dict] = []

    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            # 非 JSON 行，当作普通输出
            output_parts.append(line)
            continue

        event_type = event.get("type", "")

        # 提取助手文本输出
        if event_type == "assistant" and "message" in event:
            message = event["message"]
            if isinstance(message, dict):
                for block in message.get("content", []):
                    if isinstance(block, dict) and block.get("type") == "text":
                        output_parts.append(block["text"])

        # 提取工具调用信息
        if event_type == "tool_use":
            tool_calls.append(event)
        elif event_type == "assistant" and "message" in event:
            message = event["message"]
            if isinstance(message, dict):
                for block in message.get("content", []):
                    if isinstance(block, dict) and block.get("type") == "tool_use":
                        tool_calls.append(block)

        # 提取文件变更
        if event_type == "result":
            result_data = event.get("result", "")
            if isinstance(result_data, str):
                output_parts.append(result_data)

    # 从工具调用中提取文件变更
    for tc in tool_calls:
        tool_name = tc.get("name", "")
        tool_input = tc.get("input", {})
        if tool_name in ("Write", "Edit", "write", "edit") and "file_path" in tool_input:
            fpath = tool_input["file_path"]
            if fpath not in files_changed:
                files_changed.append(fpath)

    output = "\n".join(output_parts)
    return TaskResult(
        success=True,
        output=output,
        files_changed=files_changed,
        tool_calls=tool_calls,
    )


def run_task(prompt: str, cwd: str | Path, timeout: int = DEFAULT_TIMEOUT) -> TaskResult:
    """启动 Claude Code 执行任务，等待完成并返回结构化结果.

    Args:
        prompt: 发送给 Claude Code 的任务提示词
        cwd: 工作目录（目标项目根目录）
        timeout: 超时秒数，默认 600（10 分钟）

    Returns:
        TaskResult 包含执行结果
    """
    cwd = Path(cwd).resolve()
    logger.info("启动 Claude Code 任务，工作目录: %s", cwd)
    logger.debug("Prompt:\n%s", prompt)

    cmd = [
        "claude",
        "-p", prompt,
        "--dangerously-skip-permissions",
        "--output-format", "stream-json",
        "--verbose",
    ]

    start_time = time.monotonic()

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(cwd),
        )
    except FileNotFoundError:
        logger.error("claude 命令未找到，请确认 Claude Code 已安装")
        return TaskResult(success=False, error="claude 命令未找到")
    except (OSError, PermissionError) as e:
        logger.error("启动 Claude Code 失败: %s", e)
        return TaskResult(success=False, error=f"启动失败: {e}")

    # 使用线程读取 stdout 和 stderr，避免死锁
    stdout_lines: list[str] = []
    stderr_lines: list[str] = []

    stdout_thread = threading.Thread(target=_read_stream, args=(proc.stdout, stdout_lines))
    stderr_thread = threading.Thread(target=_read_stream, args=(proc.stderr, stderr_lines))
    stdout_thread.start()
    stderr_thread.start()

    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        duration = time.monotonic() - start_time
        logger.warning("Claude Code 执行超时（%d 秒），终止进程", timeout)
        proc.kill()
        proc.wait()
        stdout_thread.join(timeout=5)
        stderr_thread.join(timeout=5)
        return TaskResult(
            success=False,
            error=f"执行超时（{timeout} 秒）",
            output="\n".join(stdout_lines),
            duration_seconds=duration,
            return_code=None,
        )

    duration = time.monotonic() - start_time
    stdout_thread.join(timeout=10)
    stderr_thread.join(timeout=10)

    stderr_text = "\n".join(stderr_lines)
    if proc.returncode != 0:
        logger.error("Claude Code 退出码 %d, stderr: %s", proc.returncode, stderr_text)
        return TaskResult(
            success=False,
            error=f"退出码 {proc.returncode}: {stderr_text}",
            output="\n".join(stdout_lines),
            duration_seconds=duration,
            return_code=proc.returncode,
        )

    # 解析 stream-json 输出
    result = _parse_stream_json(stdout_lines)
    result.duration_seconds = duration
    result.return_code = proc.returncode
    logger.info(
        "任务完成: 修改了 %d 个文件, 调用了 %d 次工具, 耗时 %.1fs",
        len(result.files_changed),
        len(result.tool_calls),
        duration,
    )
    return result


def generate_plan(prompt: str, cwd: str | Path, timeout: int = DEFAULT_TIMEOUT) -> TaskResult:
    """生成执行计划（不带 --dangerously-skip-permissions）.

    Returns:
        TaskResult，output 为计划文本
    """
    cwd = Path(cwd).resolve()
    logger.info("[Plan Mode] 第一步：生成执行计划, cwd=%s", cwd)

    plan_prompt = (
        "请为以下任务生成详细的执行计划，列出所有需要修改的文件和具体步骤。"
        "不要实际执行任何修改，只输出计划。\n\n" + prompt
    )

    plan_cmd = [
        "claude",
        "-p", plan_prompt,
        "--output-format", "stream-json",
        "--verbose",
    ]

    start_time = time.monotonic()

    try:
        proc = subprocess.Popen(
            plan_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=str(cwd),
        )
    except FileNotFoundError:
        return TaskResult(success=False, error="claude 命令未找到")
    except (OSError, PermissionError) as e:
        return TaskResult(success=False, error=f"启动失败: {e}")

    stdout_lines: list[str] = []
    stderr_lines: list[str] = []
    stdout_thread = threading.Thread(target=_read_stream, args=(proc.stdout, stdout_lines))
    stderr_thread = threading.Thread(target=_read_stream, args=(proc.stderr, stderr_lines))
    stdout_thread.start()
    stderr_thread.start()

    plan_timeout = min(timeout // 3, 300)  # 计划阶段最多用 1/3 时间或 5 分钟
    try:
        proc.wait(timeout=plan_timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        stdout_thread.join(timeout=5)
        stderr_thread.join(timeout=5)
        return TaskResult(
            success=False,
            error=f"计划生成超时（{plan_timeout} 秒）",
            duration_seconds=time.monotonic() - start_time,
        )

    stdout_thread.join(timeout=10)
    stderr_thread.join(timeout=10)

    if proc.returncode != 0:
        return TaskResult(
            success=False,
            error=f"计划生成失败（退出码 {proc.returncode}）",
            output="\n".join(stdout_lines),
            duration_seconds=time.monotonic() - start_time,
            return_code=proc.returncode,
        )

    plan_result = _parse_stream_json(stdout_lines)
    plan_result.duration_seconds = time.monotonic() - start_time
    logger.info("[Plan Mode] 计划生成完成:\n%s", plan_result.output[:500])
    return plan_result


def execute_plan(
    plan_text: str, cwd: str | Path, timeout: int = DEFAULT_TIMEOUT
) -> TaskResult:
    """按计划执行（带 --dangerously-skip-permissions），自动前缀 [计划]/[执行结果].

    Args:
        plan_text: generate_plan() 返回的计划文本
        cwd: 工作目录
        timeout: 执行超时秒数
    """
    logger.info("[Plan Mode] 第二步：按计划执行")
    exec_prompt = (
        "请严格按照以下计划执行，不要偏离计划内容：\n\n"
        f"=== 执行计划 ===\n{plan_text}\n=== 计划结束 ===\n\n"
        "现在开始执行上述计划。"
    )

    exec_result = run_task(exec_prompt, cwd=cwd, timeout=timeout)

    # 将计划内容附加到输出前面
    if exec_result.output:
        exec_result.output = f"[计划]\n{plan_text}\n\n[执行结果]\n{exec_result.output}"
    else:
        exec_result.output = f"[计划]\n{plan_text}"

    return exec_result


def run_plan(prompt: str, cwd: str | Path, timeout: int = DEFAULT_TIMEOUT) -> TaskResult:
    """Plan 模式：先生成计划，再按计划执行（向后兼容包装）."""
    start_time = time.monotonic()

    plan_result = generate_plan(prompt, cwd=cwd, timeout=timeout)
    if not plan_result.success:
        return plan_result

    remaining_timeout = timeout - int(time.monotonic() - start_time)
    if remaining_timeout < 60:
        remaining_timeout = 60

    exec_result = execute_plan(plan_result.output, cwd=cwd, timeout=remaining_timeout)
    exec_result.duration_seconds = time.monotonic() - start_time
    return exec_result
