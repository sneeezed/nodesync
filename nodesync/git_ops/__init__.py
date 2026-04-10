"""
Git interface layer — wraps subprocess calls to the git CLI.
No external dependencies, pure stdlib.

Sub-modules:
  exceptions  — GitError, GitNotFoundError
  base        — GitRepoBase (_find_git, _run)
  state       — is_repo, init, current_commit_hash, has_commits, status_porcelain, add, commit
  history     — log, log_for_file
  checkout    — checkout, restore_files_from, show_file_at_head
  diff        — diff_since, diff_worktree_vs_commit, diff_between
  remote      — get_remote_url, set_remote_url, clone, push, pull, fetch
  branches    — current_branch, list_branches, create_branch, switch_branch
  conflicts   — get_conflicted_files, resolve_ours, resolve_theirs, complete_merge, abort_merge
"""

from .exceptions import GitError, GitNotFoundError
from .base       import GitRepoBase
from .state      import StateMixin
from .history    import HistoryMixin
from .checkout   import CheckoutMixin
from .diff       import DiffMixin
from .remote     import RemoteMixin
from .branches   import BranchMixin
from .conflicts  import ConflictMixin


class GitRepo(
    RemoteMixin,
    ConflictMixin,
    BranchMixin,
    DiffMixin,
    CheckoutMixin,
    HistoryMixin,
    StateMixin,
    GitRepoBase,
):
    """Full git repository interface. All methods are provided by mixins."""


__all__ = ['GitRepo', 'GitError', 'GitNotFoundError']
