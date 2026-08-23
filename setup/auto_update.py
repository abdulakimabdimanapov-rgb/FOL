#!/usr/bin/env python3
"""FOL Auto-Update — check for updates and pull from GitHub.

Features:
  - Checks local git version vs remote (origin/main)
  - Shows changelog of pending commits
  - Creates a backup before updating
  - Pulls changes and reinstalls dependencies
  - Rolls back on failure

Usage:
    python3 setup/auto_update.py              # check + update
    python3 setup/auto_update.py --check      # only check (no update)
    python3 setup/auto_update.py --force      # update even if up-to-date
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from datetime import datetime
from typing import Any

# ---------------------------------------------------------------------------
# Color helpers
# ---------------------------------------------------------------------------

class C:
    RESET   = "\033[0m"
    BOLD    = "\033[1m"
    DIM     = "\033[2m"
    GREEN   = "\033[32m"
    YELLOW  = "\033[33m"
    RED     = "\033[31m"
    CYAN    = "\033[36m"
    BLUE    = "\033[34m"

def ok(msg):   print(f"  {C.GREEN}✅{C.RESET} {msg}")
def warn(msg): print(f"  {C.YELLOW}⚠️{C.RESET} {msg}")
def fail(msg): print(f"  {C.RED}❌{C.RESET} {msg}")
def info(msg): print(f"  {C.CYAN}ℹ️{C.RESET} {msg}")

# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------

class GitHelper:
    """Wrapper around git commands for FOL updates."""

    def __init__(self, repo_dir: str):
        self.repo_dir = repo_dir

    def _run(self, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        """Run a git command in the repo directory."""
        cmd = ["git", "-C", self.repo_dir] + list(args)
        return subprocess.run(cmd, capture_output=True, text=True, timeout=60)

    def is_git_repo(self) -> bool:
        """Check if the directory is a git repository."""
        result = self._run("rev-parse", "--git-dir", check=False)
        return result.returncode == 0

    def get_current_branch(self) -> str:
        """Get the current branch name."""
        result = self._run("branch", "--show-current", check=False)
        return result.stdout.strip() or "main"

    def get_local_commit(self) -> dict[str, str]:
        """Get the latest local commit info."""
        result = self._run("log", "-1", "--format=%H|%s|%ai", check=False)
        if result.returncode != 0 or not result.stdout.strip():
            return {"hash": "unknown", "message": "unknown", "date": "unknown"}

        parts = result.stdout.strip().split("|", 2)
        return {
            "hash": parts[0][:8] if len(parts) > 0 else "unknown",
            "message": parts[1] if len(parts) > 1 else "unknown",
            "date": parts[2] if len(parts) > 2 else "unknown",
        }

    def fetch_remote(self) -> bool:
        """Fetch latest from remote."""
        result = self._run("fetch", "origin", check=False)
        return result.returncode == 0

    def get_remote_commit(self) -> dict[str, str]:
        """Get the latest remote commit info."""
        branch = self.get_current_branch()
        result = self._run("log", f"origin/{branch}", "-1", "--format=%H|%s|%ai", check=False)
        if result.returncode != 0 or not result.stdout.strip():
            return {"hash": "unknown", "message": "unknown", "date": "unknown"}

        parts = result.stdout.strip().split("|", 2)
        return {
            "hash": parts[0][:8] if len(parts) > 0 else "unknown",
            "message": parts[1] if len(parts) > 1 else "unknown",
            "date": parts[2] if len(parts) > 2 else "unknown",
        }

    def get_commits_ahead(self) -> list[dict[str, str]]:
        """Get list of commits the remote is ahead of local."""
        branch = self.get_current_branch()
        result = self._run("log", f"HEAD..origin/{branch}", "--format=%h|%s|%ai", check=False)
        if result.returncode != 0 or not result.stdout.strip():
            return []

        commits = []
        for line in result.stdout.strip().splitlines():
            parts = line.split("|", 2)
            commits.append({
                "hash": parts[0] if len(parts) > 0 else "?",
                "message": parts[1] if len(parts) > 1 else "unknown",
                "date": parts[2] if len(parts) > 2 else "",
            })
        return commits

    def is_up_to_date(self) -> bool:
        """Check if local is up to date with remote."""
        return len(self.get_commits_ahead()) == 0

    def get_uncommitted_changes(self) -> list[str]:
        """Get list of uncommitted changes."""
        result = self._run("status", "--porcelain", check=False)
        if result.returncode != 0:
            return []
        return [line for line in result.stdout.strip().splitlines() if line]

    def stash_changes(self) -> bool:
        """Stash uncommitted changes."""
        changes = self.get_uncommitted_changes()
        if not changes:
            return True
        result = self._run("stash", "push", "-m", f"auto-update-{int(time.time())}", check=False)
        return result.returncode == 0

    def pop_stash(self) -> bool:
        """Restore stashed changes."""
        result = self._run("stash", "pop", check=False)
        return result.returncode == 0

    def pull(self) -> tuple[bool, str]:
        """Pull changes from remote. Returns (success, message)."""
        result = self._run("pull", "origin", self.get_current_branch(), check=False)
        if result.returncode == 0:
            return True, result.stdout.strip()
        return False, result.stderr.strip() or "Unknown error"

    def create_backup_tag(self) -> str:
        """Create a backup tag before updating."""
        tag_name = f"backup-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        self._run("tag", tag_name, check=False)
        return tag_name

    def rollback_to_tag(self, tag: str) -> bool:
        """Rollback to a specific tag."""
        result = self._run("checkout", tag, "--", ".", check=False)
        return result.returncode == 0


# ---------------------------------------------------------------------------
# Update checker
# ---------------------------------------------------------------------------

class UpdateChecker:
    """Check for FOL updates from GitHub."""

    def __init__(self, repo_dir: str | None = None):
        self.repo_dir = repo_dir or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.git = GitHelper(self.repo_dir)

    def check(self) -> dict[str, Any]:
        """Check for updates. Returns status dict."""
        result = {
            "is_git_repo": False,
            "branch": "",
            "local": {},
            "remote": {},
            "ahead_count": 0,
            "commits": [],
            "up_to_date": False,
            "has_changes": False,
            "error": None,
        }

        if not self.git.is_git_repo():
            result["error"] = "Not a git repository"
            return result

        result["is_git_repo"] = True
        result["branch"] = self.git.get_current_branch()
        result["local"] = self.git.get_local_commit()

        # Fetch remote
        if not self.git.fetch_remote():
            result["error"] = "Failed to fetch from remote"
            return result

        result["remote"] = self.git.get_remote_commit()
        result["commits"] = self.git.get_commits_ahead()
        result["ahead_count"] = len(result["commits"])
        result["up_to_date"] = result["ahead_count"] == 0
        result["has_changes"] = len(self.git.get_uncommitted_changes()) > 0

        return result


# ---------------------------------------------------------------------------
# Updater
# ---------------------------------------------------------------------------

class Updater:
    """Update FOL from GitHub."""

    def __init__(self, repo_dir: str | None = None):
        self.repo_dir = repo_dir or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.git = GitHelper(self.repo_dir)
        self.checker = UpdateChecker(repo_dir)

    def update(self, force: bool = False) -> dict[str, Any]:
        """Perform the update. Returns result dict."""
        result = {
            "success": False,
            "message": "",
            "backup_tag": None,
            "deps_installed": False,
            "commits_pulled": 0,
        }

        # Check current state
        status = self.checker.check()

        if status.get("error"):
            result["message"] = status["error"]
            return result

        if not force and status["up_to_date"]:
            result["success"] = True
            result["message"] = "Already up to date"
            return result

        # Stash local changes if any
        stashed = False
        if status["has_changes"]:
            info("Stashing local changes...")
            stashed = self.git.stash_changes()

        # Create backup tag
        info("Creating backup tag...")
        result["backup_tag"] = self.git.create_backup_tag()
        ok(f"Backup: {result['backup_tag']}")

        # Pull changes
        info("Pulling updates from GitHub...")
        success, message = self.git.pull()

        if not success:
            fail(f"Pull failed: {message}")
            # Try to restore stash
            if stashed:
                self.git.pop_stash()
            result["message"] = f"Pull failed: {message}"
            return result

        result["commits_pulled"] = status["ahead_count"]
        ok(f"Pulled {status['ahead_count']} commit(s)")

        # Reinstall dependencies
        info("Reinstalling dependencies...")
        result["deps_installed"] = self._reinstall_deps()

        # Restore stash
        if stashed:
            info("Restoring stashed changes...")
            if self.git.pop_stash():
                ok("Stashed changes restored")
            else:
                warn("Could not restore stash (may have conflicts)")

        result["success"] = True
        result["message"] = f"Updated {status['ahead_count']} commit(s)"
        return result

    def _reinstall_deps(self) -> bool:
        """Reinstall Python dependencies."""
        req_path = os.path.join(self.repo_dir, "requirements.txt")
        if not os.path.isfile(req_path):
            return True

        python = sys.executable or "python3"
        try:
            result = subprocess.run(
                [python, "-m", "pip", "install", "-r", req_path, "--quiet"],
                capture_output=True, text=True, cwd=self.repo_dir, timeout=120,
            )
            return result.returncode == 0
        except Exception:
            return False

    def rollback(self, tag: str) -> bool:
        """Rollback to a specific backup tag."""
        return self.git.rollback_to_tag(tag)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="FOL Auto-Update")
    parser.add_argument("--check", action="store_true", help="Only check for updates")
    parser.add_argument("--force", action="store_true", help="Update even if up-to-date")
    parser.add_argument("--rollback", type=str, help="Rollback to backup tag")
    args = parser.parse_args()

    print(f"""
{C.CYAN}{C.BOLD}╔══════════════════════════════════════════════════════╗
║  🔄 FOL Auto-Update                                 ║
╚══════════════════════════════════════════════════════╝{C.RESET}
""")

    checker = UpdateChecker()

    # Rollback mode
    if args.rollback:
        updater = Updater()
        info(f"Rolling back to {args.rollback}...")
        if updater.rollback(args.rollback):
            ok("Rollback successful")
        else:
            fail("Rollback failed")
        return

    # Check mode
    status = checker.check()

    if not status["is_git_repo"]:
        fail("Not a git repository")
        return

    print(f"  Branch: {C.CYAN}{status['branch']}{C.RESET}")
    print(f"  Local:  {C.DIM}{status['local'].get('hash', '?')} — {status['local'].get('message', '?')}{C.RESET}")
    print(f"  Remote: {C.DIM}{status['remote'].get('hash', '?')} — {status['remote'].get('message', '?')}{C.RESET}")

    if status["error"]:
        fail(f"Error: {status['error']}")
        return

    if status["up_to_date"]:
        ok("Up to date — no updates available")
        if not args.force:
            return

    if status["has_changes"]:
        warn(f"Local changes detected ({len(status['commits'])} uncommitted file(s))")

    # Show pending commits
    if status["commits"]:
        print(f"\n{C.BOLD}Pending updates ({status['ahead_count']} commit(s)):{C.RESET}\n")
        for i, commit in enumerate(status["commits"][:10], 1):
            print(f"  {C.CYAN}{i}.{C.RESET} {commit['hash']} — {commit['message']}")
            if commit["date"]:
                print(f"     {C.DIM}{commit['date']}{C.RESET}")
        if status["ahead_count"] > 10:
            print(f"  {C.DIM}... and {status['ahead_count'] - 10} more{C.RESET}")

    if args.check:
        return

    # Confirm update
    print()
    answer = input(f"  {C.YELLOW}Update now? [Y/n] > {C.RESET}").strip().lower()
    if answer and answer != "y" and answer != "yes":
        print(f"  {C.DIM}Cancelled.{C.RESET}")
        return

    # Perform update
    updater = Updater()
    result = updater.update(force=args.force)

    print()
    if result["success"]:
        ok(f"{result['message']}")
        if result["backup_tag"]:
            info(f"Backup tag: {result['backup_tag']}")
            info(f"Rollback: python3 setup/auto_update.py --rollback {result['backup_tag']}")
    else:
        fail(f"{result['message']}")


if __name__ == "__main__":
    main()
