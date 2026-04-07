"""
Diff logic for NodeSync — compares two serialized node group dicts and
applies/removes a visual overlay in the live Blender node tree.
"""

GHOST_PREFIX = '__diff_ghost__'

# Colors in linear RGB
COLOR_ADDED    = (0.05, 0.45, 0.05)   # green  — node exists now, not in HEAD
COLOR_MODIFIED = (0.60, 0.28, 0.02)   # orange — node exists in both, values differ
COLOR_DELETED  = (0.55, 0.04, 0.04)   # red    — node was in HEAD, now gone

# Stores original color state for nodes we've re-colored so we can restore them.
# Key: (node_group_name, node_name)  Value: (use_custom_color: bool, color: tuple)
_saved_colors: dict = {}


# ---------------------------------------------------------------------------
# Core diff computation
# ---------------------------------------------------------------------------

def compute_diff(head_data: dict, current_data: dict) -> dict:
    """
    Compare two serialized node group dicts (output of export_node_group).

    Returns:
        {
            'added':    [name, ...],      # in current, not in HEAD
            'removed':  [node_dict, ...], # in HEAD, not in current (full data kept)
            'modified': [name, ...],      # in both, but values differ
        }
    """
    head_nodes    = {n['name']: n for n in head_data.get('nodes', [])}
    current_nodes = {n['name']: n for n in current_data.get('nodes', [])}

    added   = [name for name in current_nodes if name not in head_nodes]
    removed = [head_nodes[name] for name in head_nodes if name not in current_nodes]
    modified = [
        name for name in head_nodes
        if name in current_nodes and _nodes_differ(head_nodes[name], current_nodes[name])
    ]

    return {'added': added, 'removed': removed, 'modified': modified}


def _nodes_differ(a: dict, b: dict) -> bool:
    """Return True if two serialized nodes have meaningfully different values."""
    for field in ('mute', 'hide', 'label', 'type_specific'):
        if a.get(field) != b.get(field):
            return True
    # Compare input socket default values by identifier
    a_inputs = {s['identifier']: s.get('default_value') for s in a.get('inputs', [])}
    b_inputs = {s['identifier']: s.get('default_value') for s in b.get('inputs', [])}
    return a_inputs != b_inputs


# ---------------------------------------------------------------------------
# Overlay — apply
# ---------------------------------------------------------------------------

def apply_diff_overlay(node_group, diff: dict):
    """
    Color-highlight live nodes (added/modified) and create muted ghost nodes
    at the positions of deleted nodes. Saves original colors for restoration.
    """
    ng_name  = node_group.name
    added    = set(diff['added'])
    modified = set(diff['modified'])

    # Highlight existing nodes
    for node in node_group.nodes:
        if node.name.startswith(GHOST_PREFIX):
            continue
        if node.name in added:
            _save_and_color(ng_name, node, COLOR_ADDED)
        elif node.name in modified:
            _save_and_color(ng_name, node, COLOR_MODIFIED)

    # Create ghost nodes for deleted nodes
    for ndata in diff['removed']:
        ghost_name = GHOST_PREFIX + ndata['name']
        if ghost_name in node_group.nodes:
            continue  # already exists, don't double-create

        bl_idname = ndata.get('bl_idname', 'NodeFrame')
        ghost = _create_node_safe(node_group, bl_idname)
        if ghost is None:
            continue

        ghost.name  = ghost_name
        ghost.label = f'[DELETED] {ndata["name"]}'
        loc = ndata.get('location', [0.0, 0.0])
        ghost.location       = (loc[0], loc[1])
        ghost.mute           = True
        ghost.use_custom_color = True
        ghost.color          = COLOR_DELETED
        if hasattr(ghost, 'width'):
            ghost.width = ndata.get('width', 140.0)


def _create_node_safe(node_group, bl_idname: str):
    """Try to create a node; fall back to NodeReroute on failure."""
    try:
        return node_group.nodes.new(bl_idname)
    except Exception:
        pass
    try:
        return node_group.nodes.new('NodeReroute')
    except Exception:
        return None


def _save_and_color(ng_name: str, node, color: tuple):
    key = (ng_name, node.name)
    if key not in _saved_colors:
        _saved_colors[key] = (node.use_custom_color, tuple(node.color))
    node.use_custom_color = True
    node.color = color


# ---------------------------------------------------------------------------
# Overlay — remove
# ---------------------------------------------------------------------------

def remove_diff_overlay(node_group):
    """
    Remove all ghost nodes and restore original node colors for this group.
    """
    ng_name = node_group.name

    # Remove ghosts (collect first; can't remove while iterating)
    ghosts = [n for n in node_group.nodes if n.name.startswith(GHOST_PREFIX)]
    for ghost in ghosts:
        node_group.nodes.remove(ghost)

    # Restore original colors
    for node in node_group.nodes:
        key = (ng_name, node.name)
        if key in _saved_colors:
            use_cc, color = _saved_colors.pop(key)
            node.use_custom_color = use_cc
            node.color = color

    # Drop any stale entries for this group (e.g. nodes deleted by the user)
    stale = [k for k in list(_saved_colors) if k[0] == ng_name]
    for k in stale:
        del _saved_colors[k]
