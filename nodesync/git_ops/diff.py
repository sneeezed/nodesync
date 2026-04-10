"""
Mixin: diff operations between commits and the working tree.
"""


def _parse_name_status(output: str) -> dict:
    """Parse git --name-status output into categorized path lists.

    Handles M (modified), A (added), D (deleted), and R (renamed).
    Renames are split into a delete of the old path and an add of the new
    path so callers can remove the old group and import the new one.

    Returns {'modified': [...], 'added': [...], 'deleted': [...]}.
    """
    result = {'modified': [], 'added': [], 'deleted': []}
    for line in output.strip().splitlines():
        if not line:
            continue
        parts = line.split('\t')
        if len(parts) < 2:
            continue
        status = parts[0].strip()
        if status == 'M':
            result['modified'].append(parts[1].strip())
        elif status == 'A':
            result['added'].append(parts[1].strip())
        elif status == 'D':
            result['deleted'].append(parts[1].strip())
        elif status.startswith('R') and len(parts) == 3:
            # R90\told_path\tnew_path — treat as delete old + add new
            result['deleted'].append(parts[1].strip())
            result['added'].append(parts[2].strip())
    return result


class DiffMixin:
    def diff_since(self, pre_hash: str) -> dict:
        """
        Return nodes/ files changed between pre_hash and HEAD, categorized by
        git status.  Returns {'modified': [...], 'added': [...], 'deleted': [...]}
        with paths relative to the repo root (e.g. 'nodes/Foo.json').
        Handles fast-forward, merge commits, and multi-commit pulls correctly
        because it diffs two tree states rather than a single step.
        """
        if not pre_hash:
            return {'modified': [], 'added': [], 'deleted': []}
        r = self._run(
            'diff', '--name-status', f'{pre_hash}..HEAD', '--', 'nodes/',
            check=False,
        )
        if r.returncode != 0 or not r.stdout.strip():
            return {'modified': [], 'added': [], 'deleted': []}
        return _parse_name_status(r.stdout)

    def diff_worktree_vs_commit(self, commit_hash: str) -> dict:
        """
        Diff the current working tree (actual files on disk) against
        commit_hash, scoped to nodes/.  This is correct even when HEAD hasn't
        moved (e.g. after a restore_files_from that wasn't committed).

        Returns {'modified': [...], 'added': [...], 'deleted': [...]} where:
          'added'   — file exists on disk but NOT in commit (will vanish after restore)
          'deleted' — file exists in commit but NOT on disk  (will appear after restore)
          'modified'— file exists in both but differs
        """
        if not commit_hash:
            return {'modified': [], 'added': [], 'deleted': []}
        r = self._run(
            'diff', '--name-status', commit_hash, '--', 'nodes/',
            check=False,
        )
        if r.returncode != 0 or not r.stdout.strip():
            return {'modified': [], 'added': [], 'deleted': []}
        return _parse_name_status(r.stdout)

    def diff_between(self, from_hash: str, to_hash: str) -> dict:
        """
        Like diff_since but diffs from_hash..to_hash instead of pre_hash..HEAD.
        Useful when HEAD hasn't moved (e.g. restore_files_from) but you still
        need to know what changed between two specific commits.
        Returns {'modified': [...], 'added': [...], 'deleted': [...]}.
        """
        if not from_hash or not to_hash:
            return {'modified': [], 'added': [], 'deleted': []}
        r = self._run(
            'diff', '--name-status', f'{from_hash}..{to_hash}', '--', 'nodes/',
            check=False,
        )
        if r.returncode != 0 or not r.stdout.strip():
            return {'modified': [], 'added': [], 'deleted': []}
        return _parse_name_status(r.stdout)
