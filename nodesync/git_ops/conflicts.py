"""
Mixin: merge conflict detection and resolution.
"""


class ConflictMixin:
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
