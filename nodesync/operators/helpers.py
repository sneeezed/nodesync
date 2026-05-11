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


def _get_addon_prefs(context):
    """Return the NodeSync addon preferences object, or None.

    Robust against the addon being installed either as a legacy add-on
    ('nodesync') or as a Blender 4.2+ extension
    ('bl_ext.user_default.nodesync', etc.) — split('.')[0] guesses wrong in
    the extension case ('bl_ext'), which silently disables prefs-driven
    behavior like auto-push.  rsplit strips just the trailing submodule
    name, leaving the addon's actual registration key.
    """
    addon_key = __package__.rsplit('.', 1)[0]
    addon = context.preferences.addons.get(addon_key)
    if addon is None:
        return None
    return addon.preferences


def _get_credentials(context) -> tuple:
    """Return ``(username, token)`` from addon preferences.

    Either or both may be empty strings.  Empty token means no HTTPS
    auth — the caller should rely on SSH or system credential helpers.
    Empty username with a non-empty token is the GitHub / Azure DevOps
    pattern; other hosts need both.
    """
    prefs = _get_addon_prefs(context)
    if prefs is None:
        return ('', '')
    try:
        username = getattr(prefs, 'remote_username', '').strip()
    except Exception:
        username = ''
    try:
        token = getattr(prefs, 'remote_token', '').strip()
    except Exception:
        token = ''
    return (username, token)


def _clear_sync_status_if(scene_ptr, expected: str):
    """Timer callback: clear nodesync_sync_status iff it still equals
    *expected* (so a newer status message isn't overwritten).  Returns None
    so Blender unregisters the timer after one shot.
    """
    import bpy
    scene = bpy.context.scene
    if scene is not None and scene.nodesync_sync_status == expected:
        scene.nodesync_sync_status = ''
    return None


def _schedule_sync_status_clear(scene, expected: str, delay: float = 10.0):
    """Schedule the sync-status indicator to clear after *delay* seconds,
    but only if the status hasn't been changed in the meantime."""
    import bpy
    bpy.app.timers.register(
        lambda: _clear_sync_status_if(None, expected),
        first_interval=delay,
    )


# ---------------------------------------------------------------------------
# Tree path resolution — maps a live bpy node tree to its on-disk JSON path
# ---------------------------------------------------------------------------

def _resolve_tree_rel_path(node_tree) -> tuple[str, str]:
    """
    Return (rel_path, display_name) for the given live node tree.
    rel_path is the repo-relative JSON file path used by NodeSync.
    display_name is what to show in the UI (material name or group name).
    Returns ('', '') if the tree is not a tracked kind.

    Embedded shader trees (Material/World/Light) are detected by walking
    bpy.data.materials / worlds / lights and matching node_tree identity.
    """
    if node_tree is None:
        return ('', '')

    bl_idname = getattr(node_tree, 'bl_idname', '')
    safe_tree_name = node_tree.name.replace('/', '_').replace('\\', '_')

    if bl_idname == 'GeometryNodeTree':
        return (f'nodes/{safe_tree_name}.json', node_tree.name)

    if bl_idname == 'ShaderNodeTree':
        # Distinguish standalone shader groups from embedded material/world/light trees
        for collection_name, subdir in (
            ('materials', 'materials'),
            ('worlds',    'worlds'),
            ('lights',    'lights'),
        ):
            collection = getattr(bpy.data, collection_name, None)
            if collection is None:
                continue
            for owner in collection:
                if getattr(owner, 'use_nodes', False) and owner.node_tree is node_tree:
                    safe_owner = owner.name.replace('/', '_').replace('\\', '_')
                    return (
                        f'nodes/shader/{subdir}/{safe_owner}.json',
                        f'{owner.name} ({collection_name[:-1]})',
                    )
        # Standalone shader node group
        return (f'nodes/shader/{safe_tree_name}.json', node_tree.name)

    return ('', '')


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

    main/master always get index 7 (blue) to mark them as the default
    branch.  All other branches are hashed to a stable index that avoids
    blue so they stay visually distinct from the default branch.
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

def _compute_branch_ownership(entries, branch_reach: dict, current_branch: str) -> dict:
    """Assign each commit in *entries* to a single branch for coloring.

    Branch-lane coloring: the default branch (main/master) owns every
    commit it can reach — shared ancestors all get the default color.  A
    commit that the default branch cannot reach is owned by the
    most-specific other branch that reaches it (smallest reach set wins;
    current branch breaks ties; then alphabetical).

    *branch_reach* maps branch name → set of full commit hashes reachable
    from that branch tip.
    """
    default = 'main' if 'main' in branch_reach else ('master' if 'master' in branch_reach else None)

    others = [b for b in branch_reach if b != default]
    others.sort(key=lambda b: (len(branch_reach[b]), 0 if b == current_branch else 1, b))

    default_reach = branch_reach.get(default, set()) if default else set()

    ownership = {}
    for e in entries:
        h = e['full_hash']
        if default and h in default_reach:
            ownership[h] = default
            continue
        for b in others:
            if h in branch_reach[b]:
                ownership[h] = b
                break
        else:
            ownership[h] = current_branch or (default or '')
    return ownership


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
        branches = repo.list_branches()
        branch_reach = {b: repo.rev_list(b) for b in branches}
    except Exception:
        entries = []
        head_full = ''
        current_branch = ''
        branch_reach = {}

    scene.nodesync_head_hash = head_full

    ownership = _compute_branch_ownership(entries, branch_reach, current_branch)

    scene.nodesync_commit_history.clear()
    for e in entries:
        if filter_hashes is not None and e['full_hash'] not in filter_hashes:
            continue

        decs = e.get('decorations', [])
        owner = ownership.get(e['full_hash'], current_branch)

        item = scene.nodesync_commit_history.add()
        item.full_hash   = e['full_hash']
        item.hash        = e['hash']
        item.subject     = e['subject']
        item.author      = e['author']
        item.date        = e['date']
        item.decorations = ','.join(decs)
        idx, color        = _branch_color_for_name(owner)
        item.branch_name  = owner
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
# Node data removal helpers
# ---------------------------------------------------------------------------

def _deselect_tree_in_editors(tree) -> None:
    """Clear any node editor that is currently showing *tree*."""
    import bpy
    if tree is None:
        return
    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type != 'NODE_EDITOR':
                continue
            for space in area.spaces:
                if space.type != 'NODE_EDITOR':
                    continue
                try:
                    if space.node_tree is tree:
                        space.node_tree = None
                except Exception:
                    pass


def _collection_for_path(rel_path: str):
    """Return the bpy.data collection that owns the data-block for *rel_path*."""
    import bpy
    if rel_path.startswith('nodes/shader/materials/'):
        return bpy.data.materials
    if rel_path.startswith('nodes/shader/worlds/'):
        return bpy.data.worlds
    if rel_path.startswith('nodes/shader/lights/'):
        return bpy.data.lights
    return bpy.data.node_groups


def _remove_node_data(rel_path: str) -> str | None:
    """Remove the Blender data-block that corresponds to a repo-relative path.

    Routes to the correct bpy.data collection (materials / worlds / lights /
    node_groups) based on the path prefix, deselects the tree from any open
    node editor first, then removes the item.  Returns the removed name, or
    None if the item was not found.
    """
    import bpy
    import os
    name = os.path.basename(rel_path)
    if name.endswith('.json'):
        name = name[:-5]

    collection = _collection_for_path(rel_path)
    item = collection.get(name)
    if item is None:
        return None

    tree = item if collection is bpy.data.node_groups else getattr(item, 'node_tree', None)
    _deselect_tree_in_editors(tree)
    collection.remove(item)
    return name


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
