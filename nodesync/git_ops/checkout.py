"""
Mixin: checkout and file restoration from specific refs.
"""


class CheckoutMixin:
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
