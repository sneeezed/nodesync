"""
Mixin: remote operations — clone, push, pull, fetch, remote URL management.
"""

import subprocess
import shutil

from .exceptions import GitError, GitNotFoundError


def _inject_token(url: str, token: str) -> str:
    """Embed a PAT into an HTTPS GitHub URL for authentication."""
    if not token or not url.startswith('https://'):
        return url
    # Avoid double-injection
    if '@' in url.split('//')[1].split('/')[0]:
        return url
    return url.replace('https://', f'https://{token}@', 1)


class RemoteMixin:
    def get_remote_url(self) -> str | None:
        """Return the origin remote URL, or None if no remote is configured."""
        r = self._run('remote', 'get-url', 'origin', check=False)
        if r.returncode != 0 or not r.stdout.strip():
            return None
        return r.stdout.strip()

    def set_remote_url(self, url: str):
        """Add origin remote, or update it if one already exists."""
        existing = self.get_remote_url()
        if existing is None:
            self._run('remote', 'add', 'origin', url)
        else:
            self._run('remote', 'set-url', 'origin', url)

    @classmethod
    def clone(cls, url: str, target_dir: str, token: str = '') -> 'RemoteMixin':
        """Clone a remote repo into target_dir. Returns a GitRepo for the result."""
        git = shutil.which('git')
        if git is None:
            raise GitNotFoundError("Git executable not found in PATH.")
        clone_url = _inject_token(url, token)
        try:
            result = subprocess.run(
                [git, 'clone', clone_url, target_dir],
                capture_output=True,
                text=True,
                timeout=120,
            )
        except subprocess.TimeoutExpired:
            raise GitError("git clone timed out after 120 seconds")
        if result.returncode != 0:
            msg = result.stderr.strip() or result.stdout.strip() or 'git clone failed'
            raise GitError(msg)
        return cls(target_dir)

    def push(self, branch: str | None = None, token: str = '') -> str:
        """Push to origin. Returns stdout. Raises GitError on failure."""
        remote_url = self.get_remote_url()
        if not remote_url:
            raise GitError("No remote URL configured. Set one in the GitHub panel first.")

        push_url = _inject_token(remote_url, token)

        if branch is None:
            branch = self.current_branch()

        r = self._run(
            'push', '--set-upstream', push_url, branch,
            check=False, timeout=60,
        )
        if r.returncode != 0:
            msg = r.stderr.strip() or r.stdout.strip() or 'push failed'
            raise GitError(msg)
        return r.stdout.strip() or r.stderr.strip()

    def pull(self, token: str = '') -> tuple[bool, list]:
        """Pull from origin current branch.

        Returns (has_conflicts, conflicted_files).
        has_conflicts is True if merge produced conflicts.
        conflicted_files is a list of paths like 'nodes/Foo.json'.
        Raises GitError for non-conflict failures.
        """
        remote_url = self.get_remote_url()
        if not remote_url:
            raise GitError("No remote URL configured. Set one in the GitHub panel first.")

        pull_url = _inject_token(remote_url, token)
        branch = self.current_branch()

        r = self._run('pull', pull_url, branch, check=False, timeout=60)

        if r.returncode == 0:
            return False, []

        # Check if the failure is due to merge conflicts
        conflicted = self.get_conflicted_files()
        if conflicted:
            return True, conflicted

        # Some other error
        msg = r.stderr.strip() or r.stdout.strip() or 'pull failed'
        raise GitError(msg)

    def fetch(self, token: str = '') -> str:
        """Fetch from origin without merging. Returns stdout."""
        remote_url = self.get_remote_url()
        if not remote_url:
            raise GitError("No remote URL configured.")
        fetch_url = _inject_token(remote_url, token)
        r = self._run('fetch', fetch_url, check=False, timeout=60)
        if r.returncode != 0:
            msg = r.stderr.strip() or r.stdout.strip() or 'fetch failed'
            raise GitError(msg)
        return r.stdout.strip()
