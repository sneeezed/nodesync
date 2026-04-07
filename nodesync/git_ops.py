"""
Git interface layer — wraps subprocess calls to the git CLI.
No external dependencies, pure stdlib.
"""

import subprocess
import os
import shutil


class GitError(Exception):
    pass


class GitNotFoundError(GitError):
    pass


class GitRepo:
    def __init__(self, root: str):
        self.root = root
        self._git = self._find_git()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _find_git(self) -> str:
        exe = shutil.which('git')
        if exe is None:
            raise GitNotFoundError(
                "Git executable not found in PATH. "
                "Install Git and make sure it is on your system PATH."
            )
        return exe

    def _run(self, *args, check=True) -> subprocess.CompletedProcess:
        try:
            result = subprocess.run(
                [self._git] + list(args),
                cwd=self.root,
                capture_output=True,
                text=True,
                timeout=30,
            )
        except FileNotFoundError:
            raise GitNotFoundError("Git executable disappeared from PATH")
        except subprocess.TimeoutExpired:
            raise GitError("Git command timed out after 30 seconds")

        if check and result.returncode != 0:
            msg = (result.stderr.strip() or result.stdout.strip()
                   or f"git {args[0]} exited with code {result.returncode}")
            raise GitError(msg)

        return result

    # ------------------------------------------------------------------
    # Repository state
    # ------------------------------------------------------------------

    def is_repo(self) -> bool:
        r = self._run('rev-parse', '--git-dir', check=False)
        return r.returncode == 0

    def init(self):
        self._run('init')
        # Ensure a usable identity exists (needed for first commit in CI / headless)
        try:
            r = self._run('config', 'user.email', check=False)
            if r.returncode != 0 or not r.stdout.strip():
                self._run('config', 'user.email', 'nodesync@localhost')
                self._run('config', 'user.name', 'NodeSync')
        except Exception:
            pass

    def current_commit_hash(self, short=True) -> str:
        r = self._run('rev-parse', 'HEAD', check=False)
        if r.returncode != 0 or not r.stdout.strip():
            return ''
        h = r.stdout.strip()
        return h[:8] if short else h

    def has_commits(self) -> bool:
        r = self._run('rev-parse', 'HEAD', check=False)
        return r.returncode == 0

    def status_porcelain(self) -> str:
        r = self._run('status', '--porcelain', check=False)
        return r.stdout.strip()

    # ------------------------------------------------------------------
    # Staging and committing
    # ------------------------------------------------------------------

    def add(self, path: str = '.'):
        self._run('add', path)

    def commit(self, message: str) -> str:
        """Commit and return the short hash."""
        self._run('commit', '-m', message)
        return self.current_commit_hash()

    # ------------------------------------------------------------------
    # History
    # ------------------------------------------------------------------

    def log(self, n: int = 30) -> list:
        """
        Return up to n commits as a list of dicts:
            { hash, full_hash, subject, author, date }
        """
        fmt = '%H\x1f%s\x1f%an\x1f%ai'
        r = self._run('log', f'-{n}', f'--pretty=format:{fmt}', check=False)
        if r.returncode != 0 or not r.stdout.strip():
            return []
        entries = []
        for line in r.stdout.strip().split('\n'):
            parts = line.split('\x1f')
            if len(parts) == 4:
                entries.append({
                    'full_hash': parts[0],
                    'hash':      parts[0][:8],
                    'subject':   parts[1],
                    'author':    parts[2],
                    'date':      parts[3][:10],   # YYYY-MM-DD only
                })
        return entries

    # ------------------------------------------------------------------
    # Branching and checkout
    # ------------------------------------------------------------------

    def checkout(self, ref: str):
        self._run('checkout', ref)

    def restore_files_from(self, ref: str, path: str = 'nodes/'):
        """Restore files at *path* from *ref* without moving HEAD.

        This is equivalent to ``git checkout <ref> -- <path>`` and keeps the
        repo on its current branch so history is never hidden.
        """
        self._run('checkout', ref, '--', path)

