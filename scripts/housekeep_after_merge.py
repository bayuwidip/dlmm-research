#!/usr/bin/env python3
"""
Repo-owner housekeeping helper for merged PRs.

This tool updates docs/task_queue.md and docs/project_checkpoint.md after one
queued PR has been manually merged:
- marks exactly one REVIEW task as DONE
- reports the first existing READY task as the next task
- appends one checkpoint entry
- validates task queue consistency before writing

This tool cannot add tasks. New docs/task_queue.md lines are added only by the
repo owner, directly, outside this tool.

It is documentation/tooling only. It does not run the DLMM pipeline, read or
write runtime storage, create positions, or perform any market action.
"""

from __future__ import annotations

import argparse
import difflib
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import List, Optional, Sequence, Tuple


VALID_STATUSES = {"READY", "REVIEW", "BLOCKED", "DONE"}
QUEUE_PREFIX = "# Task Queue"
NEXT_TASK_PREFIX = "**NEXT TASK ->**"
NO_NEXT_TASK_LINE = f"{NEXT_TASK_PREFIX} NONE — no READY task currently queued."


@dataclass(frozen=True)
class QueueTask:
    status: str
    task_id: str
    description: str
    line_index: int


class HousekeepingError(ValueError):
    """Raised when requested housekeeping would make docs inconsistent."""


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def split_lines(text: str) -> Tuple[List[str], bool]:
    return text.splitlines(), text.endswith("\n")


def join_lines(lines: Sequence[str], trailing_newline: bool = True) -> str:
    text = "\n".join(lines)
    if trailing_newline:
        text += "\n"
    return text


def parse_task_line(line: str, line_index: int) -> QueueTask:
    parts = [part.strip() for part in line.split("|", 2)]
    if len(parts) != 3:
        raise HousekeepingError(
            f"Malformed task queue line {line_index + 1}: expected 3 pipe-separated fields"
        )
    status, task_id, description = parts
    if status not in VALID_STATUSES:
        raise HousekeepingError(
            f"Invalid task status on line {line_index + 1}: {status!r}"
        )
    if not task_id:
        raise HousekeepingError(f"Missing task id on line {line_index + 1}")
    if not description:
        raise HousekeepingError(f"Missing task description on line {line_index + 1}")
    return QueueTask(status, task_id, description, line_index)


def parse_queue(text: str) -> List[QueueTask]:
    lines, _ = split_lines(text)
    tasks = []
    seen_ids = set()
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        task = parse_task_line(line, idx)
        if task.task_id in seen_ids:
            raise HousekeepingError(f"Duplicate task id in queue: {task.task_id}")
        seen_ids.add(task.task_id)
        tasks.append(task)
    return tasks


def validate_queue_text(text: str) -> List[QueueTask]:
    if not text.startswith(QUEUE_PREFIX):
        raise HousekeepingError("docs/task_queue.md does not start with the expected header")
    tasks = parse_queue(text)
    review_tasks = [task.task_id for task in tasks if task.status == "REVIEW"]
    if len(review_tasks) > 1:
        raise HousekeepingError(
            "Task queue may not contain more than one REVIEW task: "
            + ", ".join(review_tasks)
        )
    blocked_tasks = [task.task_id for task in tasks if task.status == "BLOCKED"]
    if blocked_tasks:
        raise HousekeepingError(
            "Task queue contains BLOCKED task(s); resolve manually first: "
            + ", ".join(blocked_tasks)
        )
    return tasks


def first_ready_task(tasks: Sequence[QueueTask]) -> Optional[QueueTask]:
    for task in tasks:
        if task.status == "READY":
            return task
    return None


def replace_next_task_line(checkpoint_text: str, next_task: Optional[QueueTask]) -> str:
    lines, trailing = split_lines(checkpoint_text)
    if not lines or not lines[0].startswith(NEXT_TASK_PREFIX):
        raise HousekeepingError(
            "docs/project_checkpoint.md must start with a NEXT TASK line"
        )
    if next_task is None:
        lines[0] = NO_NEXT_TASK_LINE
    else:
        lines[0] = (
            f"{NEXT_TASK_PREFIX} {next_task.task_id} — {next_task.description}"
        )
    return join_lines(lines, trailing_newline=trailing)


def build_checkpoint_entry(
    done_task: QueueTask,
    next_task: Optional[QueueTask],
    entry_title: str,
    entry_body: str,
    entry_date: str,
) -> str:
    lines = [
        "",
        f"## Checkpoint: {entry_title}",
        "",
        f"Status: housekeeping update on {entry_date}.",
        "",
        "Completed and merged:",
        f"- {done_task.task_id}",
        "",
        "Current next task:",
    ]
    if next_task is None:
        lines.append("- NONE")
    else:
        lines.append(f"- {next_task.task_id}")
    body = entry_body.strip()
    if body:
        lines.extend(["", "Notes:", body])
    lines.append("")
    return "\n".join(lines)


def append_checkpoint_entry(checkpoint_text: str, entry: str) -> str:
    base = checkpoint_text.rstrip()
    return f"{base}\n{entry}"


def update_queue(
    queue_text: str,
    done_task_id: str,
) -> Tuple[str, QueueTask, Optional[QueueTask]]:
    lines, trailing = split_lines(queue_text)
    original_line_count = len(lines)
    tasks = validate_queue_text(queue_text)
    matches = [task for task in tasks if task.task_id == done_task_id]
    if not matches:
        raise HousekeepingError(f"Task not found in queue: {done_task_id}")
    done_task = matches[0]
    if done_task.status != "REVIEW":
        raise HousekeepingError(
            f"Task {done_task_id} must be REVIEW before it can be marked DONE "
            f"(found {done_task.status})"
        )

    lines[done_task.line_index] = f"DONE | {done_task.task_id} | {done_task.description}"
    assert len(lines) <= original_line_count, "task queue line count must never increase"

    updated_text = join_lines(lines, trailing_newline=trailing)
    updated_lines, _ = split_lines(updated_text)
    assert (
        len(updated_lines) <= original_line_count
    ), "task queue line count must never increase"
    updated_tasks = validate_queue_text(updated_text)
    next_task = first_ready_task(updated_tasks)
    return updated_text, done_task, next_task


def update_checkpoint(
    checkpoint_text: str,
    done_task: QueueTask,
    next_task: Optional[QueueTask],
    entry_title: str,
    entry_body: str,
    entry_date: str,
) -> str:
    updated = replace_next_task_line(checkpoint_text, next_task)
    entry = build_checkpoint_entry(
        done_task=done_task,
        next_task=next_task,
        entry_title=entry_title,
        entry_body=entry_body,
        entry_date=entry_date,
    )
    return append_checkpoint_entry(updated, entry)


def unified_diff(path: Path, before: str, after: str) -> str:
    return "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=f"{path} (before)",
            tofile=f"{path} (after)",
        )
    )


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Update task_queue/checkpoint after one merged PR. This tool cannot "
            "add tasks; new queue lines are added only by the repo owner, "
            "directly, outside this tool."
        )
    )
    parser.add_argument("--done-task-id", required=True, help="REVIEW task to mark DONE")
    parser.add_argument(
        "--checkpoint-title",
        required=True,
        help="Title for the appended checkpoint entry",
    )
    parser.add_argument(
        "--checkpoint-body",
        default="",
        help="Optional note body for the appended checkpoint entry",
    )
    parser.add_argument(
        "--date",
        default=date.today().isoformat(),
        help="Entry date in YYYY-MM-DD form (default: today)",
    )
    parser.add_argument(
        "--task-queue",
        default="docs/task_queue.md",
        help="Path to task queue markdown",
    )
    parser.add_argument(
        "--checkpoint",
        default="docs/project_checkpoint.md",
        help="Path to project checkpoint markdown",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and print diffs without writing files",
    )
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    queue_path = Path(args.task_queue)
    checkpoint_path = Path(args.checkpoint)

    try:
        queue_before = read_text(queue_path)
        checkpoint_before = read_text(checkpoint_path)
        queue_after, done_task, next_task = update_queue(
            queue_before,
            done_task_id=args.done_task_id,
        )
        checkpoint_after = update_checkpoint(
            checkpoint_before,
            done_task=done_task,
            next_task=next_task,
            entry_title=args.checkpoint_title,
            entry_body=args.checkpoint_body,
            entry_date=args.date,
        )
    except (OSError, HousekeepingError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if args.dry_run:
        print(unified_diff(queue_path, queue_before, queue_after), end="")
        print(unified_diff(checkpoint_path, checkpoint_before, checkpoint_after), end="")
        return 0

    try:
        write_text(queue_path, queue_after)
        write_text(checkpoint_path, checkpoint_after)
    except OSError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    next_label = next_task.task_id if next_task else "NONE"
    print(f"Marked DONE: {done_task.task_id}")
    print(f"Next READY task: {next_label}")
    print(f"Updated: {queue_path}")
    print(f"Updated: {checkpoint_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
