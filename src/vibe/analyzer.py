"""执行诊断分析 — 从 stream-json 结构化数据中提取失败模式."""

from __future__ import annotations

import re
from collections import Counter

from .manager import TaskResult

MAX_DIAGNOSTICS_LEN = 2000

_PYTEST_FAILED_RE = re.compile(r"FAILED\s+(\S+)")


def analyze_execution(result: TaskResult) -> str:
    """分析 TaskResult 的 tool_calls/tool_results，生成诊断摘要.

    成功执行或无结构化数据时返回空字符串。

    Returns:
        诊断摘要文本，最长 MAX_DIAGNOSTICS_LEN 字符
    """
    if result.success:
        return ""
    if not result.tool_calls:
        return ""

    # ── 关联 tool_calls 和 tool_results ──────────────────────
    results_by_id: dict[str, dict] = {}
    for tr in result.tool_results:
        tr_id = tr.get("tool_use_id") or tr.get("id", "")
        if tr_id:
            results_by_id[tr_id] = tr

    paired: list[tuple[dict, dict | None]] = []
    for tc in result.tool_calls:
        tc_id = tc.get("id") or tc.get("tool_use_id", "")
        paired.append((tc, results_by_id.get(tc_id)))

    # ── 统计 ─────────────────────────────────────────────────
    total_calls = len(result.tool_calls)
    failed_pairs: list[tuple[dict, dict]] = []

    for tc, tr in paired:
        if tr is None:
            continue
        if _is_tool_error(tr):
            failed_pairs.append((tc, tr))

    fail_count = len(failed_pairs)

    # ── 检测失败模式 ─────────────────────────────────────────
    issues: list[str] = []

    # 高失败率
    if total_calls > 0 and fail_count / total_calls > 0.5:
        issues.append(f"高失败率: {fail_count}/{total_calls} 次工具调用失败 ({fail_count * 100 // total_calls}%)")

    # 重复失败检测
    fail_targets = Counter[str]()
    for tc, tr in failed_pairs:
        target = _tool_target(tc)
        fail_targets[target] += 1
    for target, count in fail_targets.items():
        if count >= 2:
            issues.append(f"重复失败: {target} 连续失败 {count} 次")

    # 测试失败检测
    test_failures: list[str] = []
    for tc, tr in failed_pairs:
        name = tc.get("name", "")
        if name == "Bash":
            content = _extract_content(tr)
            for m in _PYTEST_FAILED_RE.finditer(content):
                test_failures.append(m.group(1))
    if test_failures:
        tests_str = ", ".join(test_failures[:5])
        if len(test_failures) > 5:
            tests_str += f" ... 共 {len(test_failures)} 个"
        issues.append(f"测试失败: pytest 报告 {len(test_failures)} 个测试失败: {tests_str}")

    # ── 失败详情 ─────────────────────────────────────────────
    details: list[str] = []
    for i, (tc, tr) in enumerate(failed_pairs[:10], 1):
        name = tc.get("name", "?")
        target = _tool_target(tc)
        error_snippet = _extract_error_snippet(tr)
        line = f"{i}. [{name}] {target}"
        if error_snippet:
            line += f" → {error_snippet}"
        details.append(line)

    # ── 最后操作 ─────────────────────────────────────────────
    last_call = result.tool_calls[-1] if result.tool_calls else None
    last_info = ""
    if last_call:
        last_name = last_call.get("name", "?")
        last_target = _tool_target(last_call)
        last_tc_id = last_call.get("id") or last_call.get("tool_use_id", "")
        last_tr = results_by_id.get(last_tc_id)
        status = "失败" if last_tr and _is_tool_error(last_tr) else "成功"
        last_info = f"[{last_name}] {last_target}" if last_target else f"[{last_name}]"
        last_info = f"最后操作 ({status}): {last_info}"

    # ── 组装输出 ─────────────────────────────────────────────
    exit_info = f"退出码 {result.return_code}" if result.return_code is not None else "超时"
    sections: list[str] = [
        f"执行诊断（耗时 {result.duration_seconds:.1f}s，{exit_info}）:\n",
        f"执行摘要: 共 {total_calls} 次工具调用，{fail_count} 次失败，修改了 {len(result.files_changed)} 个文件",
    ]

    if details:
        sections.append("\n失败详情:\n" + "\n".join(details))

    if issues:
        sections.append("\n检测到的问题:\n" + "\n".join(f"- {iss}" for iss in issues))

    if last_info:
        sections.append("\n" + last_info)

    text = "\n".join(sections)

    # 截断
    if len(text) > MAX_DIAGNOSTICS_LEN:
        text = text[: MAX_DIAGNOSTICS_LEN - 3] + "..."

    return text


def _is_tool_error(tr: dict) -> bool:
    """判断 tool_result 是否表示错误."""
    if tr.get("is_error"):
        return True
    content = _extract_content(tr)
    # Bash 退出码非零
    if "exit code" in content.lower() or "error" in content.lower()[:200]:
        return True
    return False


def _extract_content(tr: dict) -> str:
    """从 tool_result 中提取文本内容."""
    content = tr.get("content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
            elif isinstance(block, str):
                parts.append(block)
        return "\n".join(parts)
    return str(content)


def _tool_target(tc: dict) -> str:
    """从工具调用中提取目标描述."""
    name = tc.get("name", "")
    inp = tc.get("input", {})
    if name in ("Read", "Write", "Edit"):
        return inp.get("file_path", "")
    if name == "Bash":
        cmd = inp.get("command", "")
        return cmd[:80] + ("..." if len(cmd) > 80 else "")
    if name in ("Grep", "Glob"):
        return inp.get("pattern", "")
    return ""


def _extract_error_snippet(tr: dict) -> str:
    """从失败的 tool_result 中提取简短错误信息."""
    content = _extract_content(tr)
    if not content:
        return ""
    # 取最后几行（通常包含错误信息）
    lines = content.strip().splitlines()
    # 找 FAILED 行
    for line in lines:
        if "FAILED" in line:
            return line.strip()[:120]
    # 否则取最后一行
    last = lines[-1].strip() if lines else ""
    return last[:120]
