"""
Mixin: branch listing, creation, and switching.
"""


class BranchMixin:
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
