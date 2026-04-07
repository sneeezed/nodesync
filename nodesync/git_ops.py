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
            { hash, full_hash, subject, author, date, decorations }
        decorations is a list of ref names (branch/tag) pointing at that commit.
        """
        fmt = '%H\x1f%s\x1f%an\x1f%ai\x1f%D'
        r = self._run('log', f'-{n}', f'--pretty=format:{fmt}', check=False)
        if r.returncode != 0 or not r.stdout.strip():
            return []
        entries = []
        for line in r.stdout.strip().split('\n'):
            parts = line.split('\x1f')
            if len(parts) >= 4:
                raw_decorations = parts[4].strip() if len(parts) >= 5 else ''
                decorations = []
                if raw_decorations:
                    for d in raw_decorations.split(','):
                        d = d.strip()
                        # "HEAD -> main" → extract "main"
                        if '->' in d:
                            d = d.split('->')[-1].strip()
                        if d and d != 'HEAD':
                            decorations.append(d)
                entries.append({
                    'full_hash':   parts[0],
                    'hash':        parts[0][:8],
                    'subject':     parts[1],
                    'author':      parts[2],
                    'date':        parts[3][:10],   # YYYY-MM-DD only
                    'decorations': decorations,
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

    def show_file_at_head(self, git_relative_path: str) -> str | None:
        """Return the contents of a file at HEAD as a string.

        Returns None if there are no commits yet or the file doesn't exist
        in HEAD (e.g. a newly added group that hasn't been committed).
        """
        r = self._run('show', f'HEAD:{git_relative_path}', check=False)
        if r.returncode != 0:
            return None
        return r.stdout

    # ------------------------------------------------------------------
    # Remote operations
    # ------------------------------------------------------------------

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
    def clone(cls, url: str, target_dir: str, token: str = '') -> 'GitRepo':
        """Clone a remote repo into target_dir. Returns a GitRepo for the result."""
        import shutil
        git = shutil.which('git')
        if git is None:
            raise GitNotFoundError(
                "Git executable not found in PATH."
            )
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

        # Inject token into HTTPS URL if provided
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

    # ------------------------------------------------------------------
    # Branch operations
    # ------------------------------------------------------------------

    def current_branch(self) -> str:
        """Return the name of the current branch."""
        r = self._run('rev-parse', '--abbrev-ref', 'HEAD', check=False)
        if r.returncode != 0 or not r.stdout.strip():
            return 'main'
        return r.stdout.strip()

    def list_branches(self) -> list:
        """Return list of local branch names."""
        r = self._run('branch', check=False)
        if r.returncode != 0 or not r.stdout.strip():
            return []
        branches = []
        for line in r.stdout.strip().split('\n'):
            name = line.strip().lstrip('* ').strip()
            if name:
                branches.append(name)
        return branches

    def create_branch(self, name: str):
        """Create and switch to a new branch."""
        self._run('checkout', '-b', name)

    def switch_branch(self, name: str):
        """Switch to an existing branch."""
        self._run('checkout', name)

    # ------------------------------------------------------------------
    # Conflict resolution
    # ------------------------------------------------------------------

    def get_conflicted_files(self) -> list:
        """Return list of paths with merge conflicts (UU/AA/DD in porcelain status)."""
        r = self._run('status', '--porcelain', check=False)
        if r.returncode != 0 or not r.stdout.strip():
            return []
        conflicted = []
        for line in r.stdout.strip().split('\n'):
            if len(line) >= 2 and line[:2] in ('UU', 'AA', 'DD', 'AU', 'UA', 'DU', 'UD'):
                path = line[3:].strip()
                conflicted.append(path)
        return conflicted

    def resolve_ours(self, path: str):
        """Resolve conflict by keeping our (local) version."""
        self._run('checkout', '--ours', '--', path)
        self._run('add', path)

    def resolve_theirs(self, path: str):
        """Resolve conflict by using their (remote) version."""
        self._run('checkout', '--theirs', '--', path)
        self._run('add', path)

    def complete_merge(self) -> str:
        """Finalize a merge after all conflicts are resolved. Returns short hash."""
        self._run('commit', '--no-edit')
        return self.current_commit_hash()

    def abort_merge(self):
        """Abort an in-progress merge and return to pre-merge state."""
        self._run('merge', '--abort')


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _inject_token(url: str, token: str) -> str:
    """Embed a PAT into an HTTPS GitHub URL for authentication."""
    if not token or not url.startswith('https://'):
        return url
    # Avoid double-injection
    if '@' in url.split('//')[1].split('/')[0]:
        return url
    return url.replace('https://', f'https://{token}@', 1)

