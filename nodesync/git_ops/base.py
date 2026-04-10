"""
Base class: git executable discovery and subprocess runner.
"""

import subprocess
import shutil

from .exceptions import GitError, GitNotFoundError


class GitRepoBase:
    def __init__(self, root: str):
        self.root = root
        self._git = self._find_git()

    def _find_git(self) -> str:
        exe = shutil.which('git')
        if exe is None:
            raise GitNotFoundError(
                "Git executable not found in PATH. "
                "Install Git and make sure it is on your system PATH."
            )
        return exe

    def _run(self, *args, check=True, timeout=30) -> subprocess.CompletedProcess:
        try:
            result = subprocess.run(
                [self._git] + list(args),
                cwd=self.root,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except FileNotFoundError:
            raise GitNotFoundError("Git executable disappeared from PATH")
        except subprocess.TimeoutExpired:
            raise GitError(f"Git command timed out after {timeout} seconds")

        if check and result.returncode != 0:
            msg = (result.stderr.strip() or result.stdout.strip()
                   or f"git {args[0]} exited with code {result.returncode}")
            raise GitError(msg)

        return result
