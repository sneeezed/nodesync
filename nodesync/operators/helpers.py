"""
Shared helpers and state used by multiple operators.
"""

import os
import bpy


# ---------------------------------------------------------------------------
# Simple project / repo / token accessors
# ---------------------------------------------------------------------------

def _get_project(scene):
    """Return a NodeSyncProject for the active project root, or None."""
    from ..project import NodeSyncProject
    root = scene.nodesync_project_root.strip()
    if not root or not os.path.isdir(root):
        return None
    return NodeSyncProject(root)


def _get_repo(root):
    """Return a GitRepo, raising GitNotFoundError / GitError on failure."""
    from ..git_ops import GitRepo
    return GitRepo(root)


def _get_token(context):
    """Return the GitHub PAT from addon preferences, or empty string."""
    try:
        prefs = context.preferences.addons[__package__.split('.')[0]].preferences
        return prefs.github_token.strip()
    except Exception:
        return ''


# ---------------------------------------------------------------------------
# Branch colour palette
# ---------------------------------------------------------------------------

# 20 colours matched to COLORSET_01_VEC … COLORSET_20_VEC (Blender's bone colour sets).
# Index 0 → COLORSET_01_VEC, index 19 → COLORSET_20_VEC.
_BRANCH_PALETTE = [
    (0.90, 0.15, 0.15),  # 01 red
    (0.90, 0.40, 0.10),  # 02 orange-red
    (0.90, 0.68, 0.10),  # 03 orange
    (0.68, 0.90, 0.10),  # 04 yellow-green
    (0.15, 0.85, 0.20),  # 05 green
    (0.10, 0.85, 0.55),  # 06 teal
    (0.10, 0.72, 0.90),  # 07 cyan
    (0.10, 0.42, 0.90),  # 08 blue
    (0.28, 0.10, 0.90),  # 09 blue-purple
    (0.60, 0.10, 0.90),  # 10 purple
    (0.90, 0.10, 0.65),  # 11 magenta
    (0.90, 0.10, 0.28),  # 12 rose-red
    (0.95, 0.60, 0.60),  # 13 light red/salmon
    (0.95, 0.78, 0.55),  # 14 peach
    (0.95, 0.95, 0.50),  # 15 light yellow
    (0.55, 0.95, 0.55),  # 16 light green
    (0.50, 0.95, 0.95),  # 17 light cyan
    (0.55, 0.60, 0.95),  # 18 light blue
    (0.82, 0.82, 0.82),  # 19 light grey
    (0.45, 0.45, 0.45),  # 20 dark grey
]


def _branch_color_for_name(branch_name: str) -> tuple:
    """Return a deterministic (palette_index, rgb) based solely on the branch name.

    main/master always get index 7 (blue), matching GitHub's convention.
    All other branches are hashed to a stable index that avoids blue so
    they stay visually distinct from the default branch.
    """
    if branch_name in ('main', 'master'):
        return 7, _BRANCH_PALETTE[7]
    # Simple djb2-style hash — stable across runs
    h = 5381
    for ch in branch_name:
        h = ((h << 5) + h + ord(ch)) & 0xFFFFFFFF
    # Exclude index 7 (reserved for main/master)
    available = [i for i in range(len(_BRANCH_PALETTE)) if i != 7]
    idx = available[h % len(available)]
    return idx, _BRANCH_PALETTE[idx]


# ---------------------------------------------------------------------------
# History / branch refresh
# ---------------------------------------------------------------------------

def _refresh_history(scene, root, filter_hashes=None):
    """Populate scene.nodesync_commit_history from git log.

    If *filter_hashes* is a set of full commit hashes, only those commits
    are added to the list (used for per-node-group filtering).
    """
    try:
        from ..git_ops import GitRepo
        repo = GitRepo(root)
        entries = repo.log(300)
        head_full = repo.current_commit_hash(short=False)
        current_branch = repo.current_branch()
    except Exception:
        entries = []
        head_full = ''
        current_branch = ''

    scene.nodesync_head_hash = head_full

    # Walk newest→oldest, propagating the active branch name from decoration tags
    active_branch = current_branch

    scene.nodesync_commit_history.clear()
    for e in entries:
        # If this commit is a branch tip, update the active branch name
        decs = e.get('decorations', [])
        local_decs = [d for d in decs if not d.startswith('origin/')]
        if local_decs:
            active_branch = local_decs[0]

        if filter_hashes is not None and e['full_hash'] not in filter_hashes:
            continue

        item = scene.nodesync_commit_history.add()
        item.full_hash   = e['full_hash']
        item.hash        = e['hash']
        item.subject     = e['subject']
        item.author      = e['author']
        item.date        = e['date']
        item.decorations = ','.join(decs)
        idx, color        = _branch_color_for_name(active_branch)
        item.branch_name  = active_branch
        item.color_index  = idx
        item.branch_color = color


def _refresh_branches(scene, root):
    """Populate scene.nodesync_branch_list and nodesync_current_branch."""
    from ..git_ops import GitRepo
    try:
        repo    = GitRepo(root)
        current = repo.current_branch()
        branches = repo.list_branches()
    except Exception:
        return

    scene.nodesync_current_branch = current
    scene.nodesync_branch_list.clear()
    for name in branches:
        item       = scene.nodesync_branch_list.add()
        item.name  = name
        idx, color      = _branch_color_for_name(name)
        item.color       = color
        item.color_index = idx


# ---------------------------------------------------------------------------
# Shared mutable state for the pull confirmation dialog
# ---------------------------------------------------------------------------

# Populated by NODESYNC_OT_pull / NODESYNC_OT_checkout_commit before invoking
# NODESYNC_OT_confirm_pull_changes.
_pending_pull_changes = {
    'creates': [],   # list of (group_name, repo_relative_path)
    'deletes': [],   # list of group_name strings
    'project_root': '',
}
