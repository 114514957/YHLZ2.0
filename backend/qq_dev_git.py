"""Git helpers for QQ dev jobs (P3): baseline snapshots, scope commits, push.

Never uses ``git add -A``; commits only the recorded file list and checks
every git return code before reporting success.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import subprocess


def git(workspace, *args: str) -> tuple[int, str]:
    """Raw git call. Output is NOT stripped: porcelain's leading status
    column is significant. quotepath off so CJK paths stay readable."""
    p = subprocess.run(["git", "-c", "core.quotepath=false", *args],
                       cwd=str(workspace), capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def changed_files(workspace) -> list[str]:
    """Porcelain v1 with -z: no quoting/escaping, safe for CJK filenames."""
    rc, out = git(workspace, "status", "--porcelain", "-z")
    if rc != 0:
        return []
    parts = out.split("\0")
    files: list[str] = []
    i = 0
    while i < len(parts):
        entry = parts[i]
        i += 1
        if len(entry) < 4:
            continue
        status = entry[:2]
        path = entry[3:]
        if "R" in status or "C" in status:
            # rename/copy: the source path follows as its own NUL entry
            i += 1
        if path:
            files.append(path)
    return sorted(set(files))


def head_of(workspace) -> str:
    rc, out = git(workspace, "rev-parse", "HEAD")
    return out.strip() if rc == 0 else ""


def branch_of(workspace) -> str:
    rc, out = git(workspace, "rev-parse", "--abbrev-ref", "HEAD")
    return out.strip() if rc == 0 else ""


def diffstat(workspace, base_head: str) -> str:
    if not base_head:
        return ""
    rc, out = git(workspace, "diff", "--stat", base_head)
    return out if rc == 0 else ""


def snapshot(workspace, base_head: str) -> dict:
    data = {
        "head": head_of(workspace),
        "files": changed_files(workspace),
        "diffstat": diffstat(workspace, base_head),
    }
    payload = json.dumps(data, ensure_ascii=False, sort_keys=True)
    data["hash"] = "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
    return data


def external_changes(job: dict, snap: dict | None = None) -> list[str]:
    """Files present now that the job never recorded (other agents/editors)."""
    snap = snap or snapshot(job.get("workspace", ""), job.get("base_head", ""))
    recorded = set(job.get("changed_files") or [])
    return sorted(set(snap.get("files") or []) - recorded)


def add_and_commit(workspace, files: list[str], message: str) -> dict:
    if not files:
        return {"ok": False, "out": "文件清单为空，拒绝提交", "hash": ""}
    rc, out = git(workspace, "add", "--", *files)
    if rc != 0:
        return {"ok": False, "out": f"git add 失败(rc={rc}): {out.strip()}", "hash": ""}
    rc, out = git(workspace, "commit", "-m", message)
    if rc != 0:
        return {"ok": False, "out": f"git commit 失败(rc={rc}): {out.strip()}", "hash": ""}
    rc2, head = git(workspace, "rev-parse", "HEAD")
    return {"ok": rc2 == 0, "out": out.strip(), "hash": head.strip()}


def push(workspace, branch: str) -> dict:
    if not branch or branch == "HEAD":
        return {"ok": False, "out": "目标分支不明确，拒绝推送"}
    rc, out = git(workspace, "push", "-u", "origin", branch)
    if rc != 0:
        return {"ok": False, "out": f"git push 失败(rc={rc}): {out.strip()}"}
    return {"ok": True, "out": out.strip() or f"已推送 {branch}"}


def worktree_add(target: str, workspace: pathlib.Path, branch: str,
                 base_commit: str = "HEAD") -> tuple[bool, str]:
    workspace = pathlib.Path(workspace)
    if workspace.exists():
        return False, f"工作树目录已存在: {workspace}"
    rc, out = git(target, "worktree", "add", "-b", branch, str(workspace),
                  base_commit)
    if rc != 0:
        return False, f"worktree add 失败(rc={rc}): {out.strip()}"
    return True, out.strip()


def worktree_remove(target: str, workspace: pathlib.Path) -> None:
    git(target, "worktree", "remove", "--force", str(workspace))
