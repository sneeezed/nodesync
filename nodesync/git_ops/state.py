"""
Mixin: repository state, staging, and committing.
"""


class StateMixin:
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

    def add(self, path: str = '.'):
        self._run('add', path)

    def commit(self, message: str) -> str:
        """Commit and return the short hash."""
        self._run('commit', '-m', message)
        return self.current_commit_hash()
