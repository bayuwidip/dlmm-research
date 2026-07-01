#!/usr/bin/env python3
"""
Host-side commit and PR wrapper for run_dev_loop outputs.

Codex may run with a sandbox that can edit the working tree but cannot write
Git metadata. This tool is intended to run on the host after a successful
agent run, where branch creation, commit, push, and PR creation are available.
"""

from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Callable, Iterable, List, Optional, Sequence


DEFAULT_BASE_BRANCH = "main"
DEFAULT_BRANCH_PREFIX = "feature"
DEFAULT_COMMIT_PREFIX = "feat"
DEFAULT_VALIDATION_COMMANDS = (
    ("python3", "-m", "unittest", "discover", "tests"),
    ("python3", "scripts/validate_watchlist.py"),
)


class CommitWrapperError(ValueError):
    """Raised when the wrapper refuses to create a commit or PR."""


@dataclass(frozen=True)
class CommandResult:
    argv: Sequence[str]
    returncode: int
    stdout: str
    stderr: str


def run_command(argv: Sequence[str]) -> CommandResult:
    proc = subprocess.run(
        list(argv),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    return CommandResult(argv=argv, returncode=proc.returncode, stdout=proc.stdout, stderr=proc.stderr)


Runner = Callable[[Sequence[str]], CommandResult]


@dataclass(frozen=True)
class ChangedFile:
    status: str
    path: str


def normalize_repo_path(path: str) -> str:
    normalized = PurePosixPath(path.replace("\\", "/"))
    if normalized.is_absolute() or ".." in normalized.parts:
        raise CommitWrapperError(f"Refusing unsafe path from git status: {path}")
    return normalized.as_posix()


def generated_artifact_reason(path: str) -> Optional[str]:
    p = PurePosixPath(normalize_repo_path(path))
    text = p.as_posix()
    if text == "runtime" or text.startswith("runtime/"):
        return "runtime artifact"
    if text == "reports" or text.startswith("reports/"):
        return "report artifact"
    if len(p.parts) == 2 and p.parts[0] == "data" and p.suffix == ".csv":
        return "generated data CSV"
    if text.startswith("data/observations/"):
        return "generated observation artifact"
    return None


def parse_porcelain_z(output: str) -> List[ChangedFile]:
    entries = output.split("\0")
    if entries and entries[-1] == "":
        entries.pop()
    changes: List[ChangedFile] = []
    i = 0
    while i < len(entries):
        entry = entries[i]
        if len(entry) < 4 or entry[2] != " ":
            raise CommitWrapperError(f"Could not parse git status entry: {entry!r}")
        status = entry[:2]
        if "U" in status or status in {"DD", "AA"}:
            raise CommitWrapperError(f"Refusing unresolved merge status {status!r}")
        path = entry[3:]
        if status[0] in {"R", "C"}:
            i += 1
            if i >= len(entries):
                raise CommitWrapperError("Could not parse rename/copy target from git status")
            path = entries[i]
        changes.append(ChangedFile(status=status, path=normalize_repo_path(path)))
        i += 1
    return changes


def changed_files(runner: Runner) -> List[ChangedFile]:
    result = runner(("git", "status", "--porcelain=v1", "-z"))
    if result.returncode != 0:
        raise CommitWrapperError(command_error("git status", result))
    return parse_porcelain_z(result.stdout)


def command_error(label: str, result: CommandResult) -> str:
    detail = (result.stderr or result.stdout).strip()
    if detail:
        return f"{label} failed with exit code {result.returncode}: {detail}"
    return f"{label} failed with exit code {result.returncode}"


def disallowed_artifacts(changes: Iterable[ChangedFile]) -> List[str]:
    refused = []
    for change in changes:
        reason = generated_artifact_reason(change.path)
        if reason:
            refused.append(f"{change.path} ({reason})")
    return refused


def run_checked(runner: Runner, argv: Sequence[str], label: str) -> CommandResult:
    result = runner(argv)
    if result.returncode != 0:
        raise CommitWrapperError(command_error(label, result))
    return result


def run_validations(runner: Runner, commands: Sequence[Sequence[str]]) -> List[str]:
    summaries = []
    for command in commands:
        label = " ".join(command)
        result = run_checked(runner, command, label)
        output = (result.stdout or result.stderr).strip().splitlines()
        tail = output[-1] if output else "passed"
        summaries.append(f"- `{label}`: PASS ({tail})")
    return summaries


def read_agent_log_tail(path: Optional[str], max_lines: int = 30) -> str:
    if not path:
        return ""
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise CommitWrapperError(f"Could not read agent log {path}: {exc}") from exc
    tail = lines[-max_lines:]
    return "\n".join(tail)


def build_pr_body(
    task_id: str,
    changed_paths: Sequence[str],
    validation_lines: Sequence[str],
    agent_log_tail: str = "",
) -> str:
    lines = [
        "Summary",
        f"- Host-side wrapper committed outputs for `{task_id}`.",
        "- Staged only files accepted by the generated-artifact guard.",
        "",
        "Changed files",
    ]
    lines.extend(f"- `{path}`" for path in changed_paths)
    lines.extend(["", "Validation"])
    lines.extend(validation_lines or ["- Validation was not run by this wrapper."])
    lines.extend(
        [
            "",
            "Acceptance criteria",
            "- Detects changed files after a successful agent run.",
            "- Creates a feature branch, commits, pushes, and opens this PR from the host.",
            "- Refuses generated runtime/report/data artifacts unless explicitly allowed.",
            "- Adds no runtime trading behavior.",
        ]
    )
    if agent_log_tail:
        lines.extend(["", "Agent log tail", "```text", agent_log_tail, "```"])
    return "\n".join(lines)


def parse_validation_command(raw: str) -> Sequence[str]:
    parts = shlex.split(raw)
    if not parts:
        raise CommitWrapperError("Validation command cannot be empty")
    return tuple(parts)


def commit_and_open_pr(
    *,
    task_id: str,
    runner: Runner = run_command,
    base_branch: str = DEFAULT_BASE_BRANCH,
    branch_prefix: str = DEFAULT_BRANCH_PREFIX,
    commit_prefix: str = DEFAULT_COMMIT_PREFIX,
    allow_generated_artifacts: bool = False,
    validation_commands: Sequence[Sequence[str]] = DEFAULT_VALIDATION_COMMANDS,
    agent_log: Optional[str] = None,
    dry_run: bool = False,
) -> str:
    changes = changed_files(runner)
    if not changes:
        raise CommitWrapperError("No changed files detected; refusing to create an empty PR")

    refused = disallowed_artifacts(changes)
    if refused and not allow_generated_artifacts:
        joined = "\n".join(f"- {path}" for path in refused)
        raise CommitWrapperError(
            "Generated artifacts are present and must be removed or explicitly allowed:\n"
            + joined
        )

    changed_paths = [change.path for change in changes]
    branch = f"{branch_prefix}/{task_id}"
    commit_message = f"{commit_prefix}: {task_id}"
    validation_lines = run_validations(runner, validation_commands)
    agent_log_tail = read_agent_log_tail(agent_log)
    pr_body = build_pr_body(task_id, changed_paths, validation_lines, agent_log_tail)

    if dry_run:
        return "\n".join(
            [
                f"DRY RUN: would create branch {branch} from {base_branch}",
                f"DRY RUN: would stage {len(changed_paths)} file(s)",
                f"DRY RUN: would commit with message: {commit_message}",
                f"DRY RUN: would open PR titled: {task_id}",
                "",
                pr_body,
            ]
        )

    run_checked(runner, ("git", "checkout", "-B", branch), "git checkout")
    run_checked(runner, ("git", "add", "--", *changed_paths), "git add")
    run_checked(runner, ("git", "commit", "-m", commit_message), "git commit")
    run_checked(runner, ("git", "push", "-u", "origin", branch), "git push")
    run_checked(
        runner,
        ("gh", "pr", "create", "--title", task_id, "--body", pr_body, "--base", base_branch),
        "gh pr create",
    )
    return f"Opened PR for {task_id} on {branch}"


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Commit successful run_dev_loop outputs from the host and open a PR."
    )
    parser.add_argument("--task-id", required=True, help="Task id from docs/task_queue.md")
    parser.add_argument("--base-branch", default=DEFAULT_BASE_BRANCH)
    parser.add_argument("--branch-prefix", default=DEFAULT_BRANCH_PREFIX)
    parser.add_argument("--commit-prefix", default=DEFAULT_COMMIT_PREFIX)
    parser.add_argument(
        "--allow-generated-artifacts",
        action="store_true",
        help="Allow generated data/report/runtime artifacts to be staged.",
    )
    parser.add_argument(
        "--validation-command",
        action="append",
        help="Validation command to run before committing. May be repeated.",
    )
    parser.add_argument("--agent-log", help="Agent log file to summarize in the PR body")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    try:
        args = parse_args(argv)
        validation_commands = (
            tuple(parse_validation_command(raw) for raw in args.validation_command)
            if args.validation_command
            else DEFAULT_VALIDATION_COMMANDS
        )
        message = commit_and_open_pr(
            task_id=args.task_id,
            base_branch=args.base_branch,
            branch_prefix=args.branch_prefix,
            commit_prefix=args.commit_prefix,
            allow_generated_artifacts=args.allow_generated_artifacts,
            validation_commands=validation_commands,
            agent_log=args.agent_log,
            dry_run=args.dry_run,
        )
        print(message)
        return 0
    except CommitWrapperError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
