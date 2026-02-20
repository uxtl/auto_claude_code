"""Claude Code 进程管理 — 启动、监控、解析结果."""

import json
import logging
import os
import shlex
import subprocess
import threading
import time
from collections.abc import Callable
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


def _read_stream(
    stream,
    lines: list[str],
    on_line: Callable[[str], None] | None = None,
) -> None:
    """在线程中读取子进程的输出流."""
    try:
        for raw_line in stream:
            line = raw_line.decode("utf-8", errors="replace").rstrip("\n")
            lines.append(line)
            if on_line is not None:
                try:
                    on_line(line)
                except Exception:
                    pass  # never crash the reader thread
    finally:
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


# ── Docker 支持 ─────────────────────────────────────────────


def _build_docker_cmd(
    claude_cmd: list[str],
    cwd: Path,
    docker_image: str,
    docker_extra_args: str = "",
) -> list[str]:
    """将 claude 命令包装为 docker run 命令.

    Args:
        claude_cmd: 原始 claude CLI 命令列表
        cwd: 宿主机工作目录（挂载到 /workspace）
        docker_image: Docker 镜像名称
        docker_extra_args: 额外 docker run 参数字符串
    """
    home = Path.home()
    cmd = [
        "docker", "run",
        "--rm", "-i",
        "-v", f"{cwd}:/workspace",
        "-v", f"{home / '.claude'}:/home/user/.claude:ro",
        "-w", "/workspace",
        "-e", "ANTHROPIC_API_KEY",
    ]
    # UID=0 时跳过 --user（Claude CLI 拒绝 root + --dangerously-skip-permissions）
    uid = os.getuid()
    if uid != 0:
        gid = os.getgid()
        cmd.extend(["--user", f"{uid}:{gid}"])
    # 挂载 ~/.claude.json（如果存在）
    claude_json = home / ".claude.json"
    if claude_json.is_file():
        cmd.extend(["-v", f"{claude_json}:/home/user/.claude.json:ro"])
    if docker_extra_args:
        cmd.extend(shlex.split(docker_extra_args))
    cmd.append(docker_image)
    cmd.extend(claude_cmd)
    return cmd


def check_docker_available() -> tuple[bool, str]:
    """检查 Docker 是否可用.

    Returns:
        (可用, 消息) 元组
    """
    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            timeout=10,
        )
        if result.returncode == 0:
            return True, "Docker 可用"
        stderr = result.stderr.decode("utf-8", errors="replace").strip()
        return False, f"Docker 不可用: {stderr}"
    except FileNotFoundError:
        return False, "docker 命令未找到，请安装 Docker"
    except subprocess.TimeoutExpired:
        return False, "docker info 超时"
    except (OSError, PermissionError) as e:
        return False, f"Docker 检查失败: {e}"


def ensure_docker_image(image: str, dockerfile_dir: str | Path = ".") -> tuple[bool, str]:
    """检查镜像是否存在，不存在时尝试自动构建.

    Args:
        image: 镜像名称
        dockerfile_dir: Dockerfile 所在目录

    Returns:
        (成功, 消息) 元组
    """
    # 检查镜像是否已存在
    try:
        result = subprocess.run(
            ["docker", "image", "inspect", image],
            capture_output=True,
            timeout=10,
        )
        if result.returncode == 0:
            return True, f"镜像 {image} 已存在"
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False, "docker 命令不可用"

    # 镜像不存在，尝试构建
    dockerfile_path = Path(dockerfile_dir) / "Dockerfile"
    if not dockerfile_path.is_file():
        return False, f"镜像 {image} 不存在且未找到 Dockerfile: {dockerfile_path}"

    logger.info("镜像 %s 不存在，开始自动构建...", image)
    try:
        result = subprocess.run(
            ["docker", "build", "-t", image, str(dockerfile_dir)],
            capture_output=True,
            timeout=600,
        )
        if result.returncode == 0:
            return True, f"镜像 {image} 构建成功"
        stderr = result.stderr.decode("utf-8", errors="replace").strip()
        return False, f"镜像 {image} 构建失败: {stderr}"
    except subprocess.TimeoutExpired:
        return False, f"镜像 {image} 构建超时"
    except (OSError, PermissionError) as e:
        return False, f"镜像构建失败: {e}"


# ── 公共子进程管理 ──────────────────────────────────────────


def _run_claude(
    cmd: list[str],
    cwd: Path,
    timeout: int,
    *,
    use_docker: bool = False,
    docker_image: str = "auto-claude-code",
    docker_extra_args: str = "",
    shutdown_event: threading.Event | None = None,
    on_output: Callable[[str], None] | None = None,
) -> TaskResult:
    """执行 claude 命令的公共子进程管理逻辑.

    处理 Popen 启动、双线程读取 stdout/stderr、超时、结果解析。
    当 use_docker=True 时自动将命令包装为 docker run。

    Args:
        cmd: claude CLI 命令列表
        cwd: 工作目录
        timeout: 超时秒数
        use_docker: 是否使用 Docker 包装
        docker_image: Docker 镜像名
        docker_extra_args: 额外 docker run 参数
    """
    if use_docker:
        actual_cmd = _build_docker_cmd(cmd, cwd, docker_image, docker_extra_args)
        proc_cwd = None  # Docker 模式下 cwd 通过 -w /workspace 指定
    else:
        actual_cmd = cmd
        proc_cwd = str(cwd)

    start_time = time.monotonic()

    # 清除 CLAUDECODE 环境变量，允许嵌套调用（从 Claude Code 会话内启动子进程）
    env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}

    try:
        proc = subprocess.Popen(
            actual_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=proc_cwd,
            env=env,
        )
    except FileNotFoundError:
        bin_name = "docker" if use_docker else "claude"
        logger.error("%s 命令未找到", bin_name)
        return TaskResult(success=False, error=f"{bin_name} 命令未找到")
    except (OSError, PermissionError) as e:
        logger.error("启动失败: %s", e)
        return TaskResult(success=False, error=f"启动失败: {e}")

    # 使用线程读取 stdout 和 stderr，避免死锁
    stdout_lines: list[str] = []
    stderr_lines: list[str] = []

    stdout_thread = threading.Thread(
        target=_read_stream, args=(proc.stdout, stdout_lines, on_output), daemon=True,
    )
    stderr_thread = threading.Thread(
        target=_read_stream, args=(proc.stderr, stderr_lines), daemon=True,
    )
    stdout_thread.start()
    stderr_thread.start()

    # 轮询等待子进程结束，每 0.5s 检查一次 shutdown_event
    deadline = start_time + timeout
    poll_interval = 0.5

    while True:
        try:
            proc.wait(timeout=poll_interval)
            break  # 子进程已结束
        except subprocess.TimeoutExpired:
            pass

        # 检查关闭信号
        if shutdown_event is not None and shutdown_event.is_set():
            duration = time.monotonic() - start_time
            logger.warning("收到关闭信号，终止子进程")
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
            stdout_thread.join(timeout=5)
            stderr_thread.join(timeout=5)
            interrupted = True
            return TaskResult(
                success=False,
                error="中断: 收到关闭信号",
                output="\n".join(stdout_lines),
                duration_seconds=duration,
                return_code=proc.returncode,
            )

        # 检查超时
        if time.monotonic() >= deadline:
            duration = time.monotonic() - start_time
            logger.warning("执行超时（%d 秒），终止进程", timeout)
            proc.kill()
            proc.wait()
            stdout_thread.join(timeout=5)
            if stdout_thread.is_alive():
                logger.warning("stdout 读取线程在 join 超时后仍在运行")
            stderr_thread.join(timeout=5)
            if stderr_thread.is_alive():
                logger.warning("stderr 读取线程在 join 超时后仍在运行")
            return TaskResult(
                success=False,
                error=f"执行超时（{timeout} 秒）",
                output="\n".join(stdout_lines),
                duration_seconds=duration,
                return_code=None,
            )

    duration = time.monotonic() - start_time
    stdout_thread.join(timeout=10)
    if stdout_thread.is_alive():
        logger.warning("stdout 读取线程在 join 超时后仍在运行")
    stderr_thread.join(timeout=10)
    if stderr_thread.is_alive():
        logger.warning("stderr 读取线程在 join 超时后仍在运行")

    stderr_text = "\n".join(stderr_lines)
    if proc.returncode != 0:
        logger.error("退出码 %d, stderr: %s", proc.returncode, stderr_text)
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
    return result


# ── 公开 API ────────────────────────────────────────────────


def run_task(
    prompt: str,
    cwd: str | Path,
    timeout: int = DEFAULT_TIMEOUT,
    *,
    use_docker: bool = False,
    docker_image: str = "auto-claude-code",
    docker_extra_args: str = "",
    shutdown_event: threading.Event | None = None,
    on_output: Callable[[str], None] | None = None,
) -> TaskResult:
    """启动 Claude Code 执行任务，等待完成并返回结构化结果.

    Args:
        prompt: 发送给 Claude Code 的任务提示词
        cwd: 工作目录（目标项目根目录）
        timeout: 超时秒数，默认 600（10 分钟）
        use_docker: 是否在 Docker 容器中执行
        docker_image: Docker 镜像名
        docker_extra_args: 额外 docker run 参数
        on_output: 可选回调，每读到一行 stdout 时调用
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

    result = _run_claude(
        cmd, cwd, timeout,
        use_docker=use_docker,
        docker_image=docker_image,
        docker_extra_args=docker_extra_args,
        shutdown_event=shutdown_event,
        on_output=on_output,
    )

    if result.success:
        logger.info(
            "任务完成: 修改了 %d 个文件, 调用了 %d 次工具, 耗时 %.1fs",
            len(result.files_changed),
            len(result.tool_calls),
            result.duration_seconds,
        )
    return result


def generate_plan(
    prompt: str,
    cwd: str | Path,
    timeout: int = DEFAULT_TIMEOUT,
    *,
    use_docker: bool = False,
    docker_image: str = "auto-claude-code",
    docker_extra_args: str = "",
    shutdown_event: threading.Event | None = None,
    on_output: Callable[[str], None] | None = None,
) -> TaskResult:
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

    plan_timeout = min(timeout // 3, 300)
    result = _run_claude(
        plan_cmd, cwd, plan_timeout,
        use_docker=use_docker,
        docker_image=docker_image,
        docker_extra_args=docker_extra_args,
        shutdown_event=shutdown_event,
        on_output=on_output,
    )

    if not result.success and "超时" in result.error:
        result.error = f"计划生成超时（{plan_timeout} 秒）"
    elif not result.success and "退出码" in result.error:
        result.error = f"计划生成失败（{result.error}）"

    if result.success:
        logger.info("[Plan Mode] 计划生成完成:\n%s", result.output[:500])
    return result


def execute_plan(
    plan_text: str,
    cwd: str | Path,
    timeout: int = DEFAULT_TIMEOUT,
    *,
    use_docker: bool = False,
    docker_image: str = "auto-claude-code",
    docker_extra_args: str = "",
    shutdown_event: threading.Event | None = None,
    on_output: Callable[[str], None] | None = None,
) -> TaskResult:
    """按计划执行（带 --dangerously-skip-permissions），自动前缀 [计划]/[执行结果].

    Args:
        plan_text: generate_plan() 返回的计划文本
        cwd: 工作目录
        timeout: 执行超时秒数
        use_docker: 是否在 Docker 容器中执行
        docker_image: Docker 镜像名
        docker_extra_args: 额外 docker run 参数
        on_output: 可选回调，每读到一行 stdout 时调用
    """
    logger.info("[Plan Mode] 第二步：按计划执行")
    exec_prompt = (
        "请严格按照以下计划执行，不要偏离计划内容：\n\n"
        f"=== 执行计划 ===\n{plan_text}\n=== 计划结束 ===\n\n"
        "现在开始执行上述计划。"
    )

    exec_result = run_task(
        exec_prompt, cwd=cwd, timeout=timeout,
        use_docker=use_docker,
        docker_image=docker_image,
        docker_extra_args=docker_extra_args,
        shutdown_event=shutdown_event,
        on_output=on_output,
    )

    # 将计划内容附加到输出前面
    if exec_result.output:
        exec_result.output = f"[计划]\n{plan_text}\n\n[执行结果]\n{exec_result.output}"
    else:
        exec_result.output = f"[计划]\n{plan_text}"

    return exec_result


def run_plan(
    prompt: str,
    cwd: str | Path,
    timeout: int = DEFAULT_TIMEOUT,
    *,
    use_docker: bool = False,
    docker_image: str = "auto-claude-code",
    docker_extra_args: str = "",
    shutdown_event: threading.Event | None = None,
    on_output: Callable[[str], None] | None = None,
) -> TaskResult:
    """Plan 模式：先生成计划，再按计划执行（向后兼容包装）."""
    start_time = time.monotonic()

    plan_result = generate_plan(
        prompt, cwd=cwd, timeout=timeout,
        use_docker=use_docker,
        docker_image=docker_image,
        docker_extra_args=docker_extra_args,
        shutdown_event=shutdown_event,
        on_output=on_output,
    )
    if not plan_result.success:
        return plan_result

    remaining_timeout = timeout - int(time.monotonic() - start_time)
    if remaining_timeout < 60:
        remaining_timeout = 60

    exec_result = execute_plan(
        plan_result.output, cwd=cwd, timeout=remaining_timeout,
        use_docker=use_docker,
        docker_image=docker_image,
        docker_extra_args=docker_extra_args,
        shutdown_event=shutdown_event,
        on_output=on_output,
    )
    exec_result.duration_seconds = time.monotonic() - start_time
    return exec_result
