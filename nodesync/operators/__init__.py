"""
NodeSync operators package.

Sub-modules:
  modifier_links  — session-scoped modifier link snapshot/restore helpers
  helpers         — shared accessors, branch colours, history/branch refresh
  project_ops     — init_project, open_project
  commit_ops      — commit, refresh_history, checkout_commit, toggle_history_filter
  diff_ops        — enter_diff, exit_diff, diff_legend
  remote_ops      — clone_from_github, set_remote, push, pull, confirm_pull_changes
  branch_ops      — create_branch, switch_branch
  conflict_ops    — resolve_conflict, complete_merge, abort_merge
"""

from .project_ops  import classes as _project_classes
from .commit_ops   import classes as _commit_classes
from .diff_ops     import classes as _diff_classes
from .remote_ops   import classes as _remote_classes
from .branch_ops   import classes as _branch_classes
from .conflict_ops import classes as _conflict_classes

classes = (
    _project_classes
    + _commit_classes
    + _diff_classes
    + _remote_classes
    + _branch_classes
    + _conflict_classes
)
