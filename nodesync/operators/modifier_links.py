"""
Modifier-link snapshot — persists across operator calls within a session.

Maps group_name → [(object_name, modifier_name), ...]
Captures which GN modifiers were pointing to which groups so that if a group
is deleted and later re-imported the modifiers can be automatically re-linked.
"""

import bpy

_modifier_link_snapshot: dict = {}


def _snapshot_modifier_links() -> None:
    """Add current modifier→group links to the snapshot (additive, never clears)."""
    for obj in bpy.data.objects:
        for mod in obj.modifiers:
            if mod.type == 'NODES' and mod.node_group is not None:
                key   = mod.node_group.name
                entry = (obj.name, mod.name)
                if key not in _modifier_link_snapshot:
                    _modifier_link_snapshot[key] = []
                if entry not in _modifier_link_snapshot[key]:
                    _modifier_link_snapshot[key].append(entry)


def _restore_modifier_links(imported_names: list) -> int:
    """Re-link GN modifiers whose node_group became None after a group was
    removed and then re-imported.  Returns count of modifiers re-linked."""
    relinked = 0
    for group_name in imported_names:
        entries = _modifier_link_snapshot.get(group_name)
        if not entries:
            continue
        ng = bpy.data.node_groups.get(group_name)
        if ng is None:
            continue
        for obj_name, mod_name in entries:
            obj = bpy.data.objects.get(obj_name)
            if obj is None:
                continue
            mod = obj.modifiers.get(mod_name)
            if mod is None or mod.type != 'NODES':
                continue
            if mod.node_group is None:
                mod.node_group = ng
                relinked += 1
    return relinked
