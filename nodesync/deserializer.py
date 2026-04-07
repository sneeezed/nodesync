"""
Deserializer: reconstruct a bpy GeometryNodeTree from a serialized dict.

Usage:
    from nodesync.deserializer import reconstruct_node_group
    ng = reconstruct_node_group(data)   # data is a dict from export_node_group()
"""

import bpy
from .utils import deserialize_default_value, NO_DEFAULT_VALUE_SOCKETS


def _restore_interface(node_group, interface_data: list):
    """
    Rebuild the group's exposed interface sockets (Blender 4.x API).
    Falls back to legacy API for 3.x.
    """
    if not interface_data:
        return

    # Blender 4.x
    if hasattr(node_group, 'interface') and hasattr(node_group.interface, 'new_socket'):
        for item_data in interface_data:
            try:
                socket = node_group.interface.new_socket(
                    name=item_data['name'],
                    socket_type=item_data['socket_type'],
                    in_out=item_data['in_out'],
                )
            except Exception as e:
                print(f"[NodeSync] Could not create interface socket "
                      f"'{item_data['name']}': {e}")
                continue

            dv = item_data.get('default_value')
            if dv is not None and hasattr(socket, 'default_value'):
                try:
                    socket.default_value = deserialize_default_value(
                        item_data['socket_type'], dv)
                except Exception:
                    pass

            min_v = item_data.get('min_value')
            max_v = item_data.get('max_value')
            if min_v is not None and hasattr(socket, 'min_value'):
                try:
                    socket.min_value = min_v
                except Exception:
                    pass
            if max_v is not None and hasattr(socket, 'max_value'):
                try:
                    socket.max_value = max_v
                except Exception:
                    pass

            ad = item_data.get('attribute_domain')
            if ad is not None and hasattr(socket, 'attribute_domain'):
                try:
                    socket.attribute_domain = ad
                except Exception:
                    pass
        return

    # Blender 3.x fallback (deprecated but kept for compatibility)
    for item_data in interface_data:
        in_out = item_data.get('in_out', 'INPUT')
        try:
            if in_out == 'INPUT':
                sock = node_group.inputs.new(item_data['socket_type'], item_data['name'])
            else:
                sock = node_group.outputs.new(item_data['socket_type'], item_data['name'])

            dv = item_data.get('default_value')
            if dv is not None and hasattr(sock, 'default_value'):
                try:
                    sock.default_value = deserialize_default_value(
                        item_data['socket_type'], dv)
                except Exception:
                    pass
        except Exception as e:
            print(f"[NodeSync] 3.x interface socket creation failed: {e}")


def _apply_type_specific(node, ts: dict):
    """
    Apply type_specific properties to a node.
    Must be called BEFORE reading socket identifiers (some props add/remove sockets).
    """
    if not ts:
        return

    bl_idname = node.bl_idname

    # GROUP: resolve node tree reference
    if bl_idname == 'GeometryNodeGroup':
        ref = ts.get('node_tree_ref')
        if ref:
            ng = bpy.data.node_groups.get(ref)
            if ng is not None:
                node.node_tree = ng
            else:
                print(f"[NodeSync] Referenced node group '{ref}' not found in bpy.data")
        return

    # NodeFrame
    if bl_idname == 'NodeFrame':
        if 'shrink' in ts:
            try:
                node.shrink = ts['shrink']
            except Exception:
                pass
        text_name = ts.get('text')
        if text_name and text_name in bpy.data.texts:
            try:
                node.text = bpy.data.texts[text_name]
            except Exception:
                pass
        return

    # General case
    for prop, val in ts.items():
        if hasattr(node, prop):
            try:
                setattr(node, prop, val)
            except Exception as e:
                print(f"[NodeSync] Could not set {node.bl_idname}.{prop} = {val!r}: {e}")


def _restore_socket_defaults(node, sockets_data: list, is_input: bool):
    """
    Restore default values and visibility for node sockets.
    Matches by identifier for robustness against socket reordering.
    """
    socket_list = node.inputs if is_input else node.outputs
    id_to_data = {s['identifier']: s for s in sockets_data}

    for sock in socket_list:
        sdata = id_to_data.get(sock.identifier)
        if sdata is None:
            continue

        sock.hide = sdata.get('hide', False)
        hide_value = sdata.get('hide_value', False)
        if hasattr(sock, 'hide_value'):
            sock.hide_value = hide_value

        dv = sdata.get('default_value')
        if dv is not None and sock.bl_idname not in NO_DEFAULT_VALUE_SOCKETS:
            if hasattr(sock, 'default_value'):
                try:
                    sock.default_value = deserialize_default_value(sock.bl_idname, dv)
                except Exception as e:
                    print(f"[NodeSync] Could not restore default_value on "
                          f"{node.name}.{sock.name}: {e}")


def reconstruct_node_group(data: dict):
    """
    Reconstruct a GeometryNodeTree from a serialized dict.
    If a group with this name already exists it is cleared and rebuilt in place.
    Returns the reconstructed bpy node group, or None on failure.

    Dependency requirement: any nested group referenced by node_tree_ref must
    already exist in bpy.data.node_groups before this function is called.
    """
    name = data.get('name')
    if not name:
        print("[NodeSync] reconstruct_node_group: missing 'name' in data")
        return None

    tree_type = data.get('type', 'GeometryNodeTree')

    # Create or reuse existing node group
    if name in bpy.data.node_groups:
        ng = bpy.data.node_groups[name]
        ng.nodes.clear()  # also clears all links automatically

        # Clear interface (Blender 4.x)
        if hasattr(ng, 'interface') and hasattr(ng.interface, 'items_tree'):
            items = list(ng.interface.items_tree)
            for item in items:
                try:
                    ng.interface.remove(item)
                except Exception:
                    pass
        # Blender 3.x fallback
        elif hasattr(ng, 'inputs'):
            while ng.inputs:
                ng.inputs.remove(ng.inputs[0])
            while ng.outputs:
                ng.outputs.remove(ng.outputs[0])
    else:
        ng = bpy.data.node_groups.new(name, tree_type)

    # 1. Rebuild interface sockets
    _restore_interface(ng, data.get('interface', []))

    # 2. Create all nodes (two passes: create then parent)
    node_map = {}  # name -> bpy node

    for ndata in data.get('nodes', []):
        bl_idname = ndata['bl_idname']
        try:
            node = ng.nodes.new(bl_idname)
        except Exception as e:
            print(f"[NodeSync] Could not create node '{ndata['name']}' "
                  f"({bl_idname}): {e}")
            continue

        # Set name immediately (before other nodes are added) to get exact name
        node.name = ndata['name']
        node.label = ndata.get('label', '')

        # Apply type_specific BEFORE reading socket identifiers
        _apply_type_specific(node, ndata.get('type_specific', {}))

        # Restore socket defaults (identifiers are now stable)
        _restore_socket_defaults(node, ndata.get('inputs', []), is_input=True)
        _restore_socket_defaults(node, ndata.get('outputs', []), is_input=False)

        # Location, size, visibility
        loc = ndata.get('location', [0.0, 0.0])
        node.location = (loc[0], loc[1])
        node.width = ndata.get('width', 140.0)
        node.hide = ndata.get('hide', False)
        node.mute = ndata.get('mute', False)
        node.use_custom_color = ndata.get('use_custom_color', False)
        color = ndata.get('color', [0.608, 0.608, 0.608])
        node.color = (color[0], color[1], color[2])

        node_map[ndata['name']] = node

    # 3. Second pass: assign parent frames (all nodes must exist first)
    for ndata in data.get('nodes', []):
        parent_name = ndata.get('parent')
        if parent_name and parent_name in node_map and ndata['name'] in node_map:
            node_map[ndata['name']].parent = node_map[parent_name]

    # 4. Rebuild links
    for ldata in data.get('links', []):
        from_node = node_map.get(ldata['from_node'])
        to_node   = node_map.get(ldata['to_node'])
        if from_node is None or to_node is None:
            print(f"[NodeSync] Link skipped — node not found: "
                  f"{ldata['from_node']} → {ldata['to_node']}")
            continue

        from_id   = ldata['from_socket_identifier']
        from_name = ldata.get('from_socket_name', '')
        to_id     = ldata['to_socket_identifier']
        to_name   = ldata.get('to_socket_name', '')

        from_sock = (next((s for s in from_node.outputs if s.identifier == from_id), None)
                     or next((s for s in from_node.outputs if s.name == from_name), None))
        to_sock   = (next((s for s in to_node.inputs if s.identifier == to_id), None)
                     or next((s for s in to_node.inputs if s.name == to_name), None))

        if from_sock is None or to_sock is None:
            print(f"[NodeSync] Link skipped — socket not found: "
                  f"{ldata['from_node']}.{from_id}({from_name}) → "
                  f"{ldata['to_node']}.{to_id}({to_name})")
            continue

        try:
            ng.links.new(from_sock, to_sock)
        except Exception as e:
            print(f"[NodeSync] Could not create link: {e}")

    return ng


def reconstruct_all(all_data: list):
    """
    Reconstruct multiple node groups from a dependency-ordered list of dicts.
    Dependencies (deepest groups first) must come before the groups that use them.
    Returns a dict mapping group name -> reconstructed node group.
    """
    results = {}
    for data in all_data:
        ng = reconstruct_node_group(data)
        if ng is not None:
            results[ng.name] = ng
    return results
