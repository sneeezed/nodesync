"""
Serializer: convert a bpy GeometryNodeTree into a JSON-safe dict.

Usage:
    from nodesync.serializer import export_node_group, collect_all_groups
    data = export_node_group(bpy.data.node_groups['MyGroup'])
"""

import bpy
from .utils import serialize_default_value, TYPE_SPECIFIC_PROPS


def _serialize_socket(socket) -> dict:
    return {
        'identifier':    socket.identifier,
        'name':          socket.name,
        'socket_type':   socket.bl_idname,
        'default_value': serialize_default_value(socket),
        'hide':          socket.hide,
        'hide_value':    getattr(socket, 'hide_value', False),
    }


def _serialize_interface(node_group) -> list:
    """
    Read the group's exposed interface sockets (Blender 4.x API).
    Falls back to legacy ng.inputs / ng.outputs for 3.x compatibility.
    """
    items = []

    # Blender 4.x: node_group.interface.items_tree
    if hasattr(node_group, 'interface') and hasattr(node_group.interface, 'items_tree'):
        for item in node_group.interface.items_tree:
            if item.item_type != 'SOCKET':
                continue
            entry = {
                'name':             item.name,
                'socket_type':      item.socket_type,
                'in_out':           item.in_out,
                'default_value':    None,
                'min_value':        None,
                'max_value':        None,
                'attribute_domain': None,
            }
            if hasattr(item, 'default_value'):
                try:
                    val = item.default_value
                    entry['default_value'] = list(val) if hasattr(val, '__iter__') and not isinstance(val, str) else val
                except Exception:
                    pass
            if hasattr(item, 'min_value'):
                try:
                    entry['min_value'] = item.min_value
                except Exception:
                    pass
            if hasattr(item, 'max_value'):
                try:
                    entry['max_value'] = item.max_value
                except Exception:
                    pass
            if hasattr(item, 'attribute_domain'):
                try:
                    entry['attribute_domain'] = item.attribute_domain
                except Exception:
                    pass
            items.append(entry)
        return items

    # Blender 3.x fallback
    for sock in getattr(node_group, 'inputs', []):
        items.append({
            'name':             sock.name,
            'socket_type':      sock.bl_idname,
            'in_out':           'INPUT',
            'default_value':    serialize_default_value(sock),
            'min_value':        getattr(sock, 'min_value', None),
            'max_value':        getattr(sock, 'max_value', None),
            'attribute_domain': None,
        })
    for sock in getattr(node_group, 'outputs', []):
        items.append({
            'name':             sock.name,
            'socket_type':      sock.bl_idname,
            'in_out':           'OUTPUT',
            'default_value':    serialize_default_value(sock),
            'min_value':        getattr(sock, 'min_value', None),
            'max_value':        getattr(sock, 'max_value', None),
            'attribute_domain': None,
        })
    return items


def _serialize_type_specific(node) -> dict:
    """
    Read node-type-specific properties. Always sets type_specific props
    BEFORE socket identifiers are read (some props add/remove sockets).
    For GROUP nodes, stores a reference to the nested node tree by name.
    """
    ts = {}
    bl_idname = node.bl_idname

    # GROUP: store reference by name only — never inline-serialize
    if bl_idname in ('GeometryNodeGroup', 'ShaderNodeGroup'):
        if node.node_tree is not None:
            ts['node_tree_ref'] = node.node_tree.name
        return ts

    # NodeFrame: also capture text block name if set
    if bl_idname == 'NodeFrame':
        ts['shrink'] = getattr(node, 'shrink', True)
        if getattr(node, 'text', None) is not None:
            ts['text'] = node.text.name
        else:
            ts['text'] = None
        return ts

    # General case: use the known props list, then fall back to an introspection
    known_props = TYPE_SPECIFIC_PROPS.get(bl_idname, None)

    if known_props is not None:
        for prop in known_props:
            if hasattr(node, prop):
                try:
                    val = getattr(node, prop)
                    # Enum values come back as strings already
                    ts[prop] = val
                except Exception:
                    pass
    else:
        # Unknown node type: try to capture any non-default RNA props
        # This is a best-effort fallback for node types not in TYPE_SPECIFIC_PROPS
        pass

    return ts


def export_node_group(node_group) -> dict:
    """
    Serialize a single GeometryNodeTree into a JSON-safe dict.
    Nested groups are referenced by name only — call collect_all_groups()
    to get the full dependency list for multi-file export.
    """
    nodes_data = []
    for node in node_group.nodes:
        node_data = {
            'name':             node.name,
            'label':            node.label,
            'bl_idname':        node.bl_idname,
            'location':         [node.location.x, node.location.y],
            'width':            node.width,
            'hide':             node.hide,
            'mute':             node.mute,
            'use_custom_color': node.use_custom_color,
            'color':            list(node.color),
            'parent':           node.parent.name if node.parent is not None else None,
            'type_specific':    _serialize_type_specific(node),
            'inputs':           [_serialize_socket(s) for s in node.inputs],
            'outputs':          [_serialize_socket(s) for s in node.outputs],
        }
        nodes_data.append(node_data)

    links_data = []
    for link in node_group.links:
        links_data.append({
            'from_node':             link.from_node.name,
            'from_socket_identifier': link.from_socket.identifier,
            'from_socket_name':      link.from_socket.name,
            'to_node':               link.to_node.name,
            'to_socket_identifier':  link.to_socket.identifier,
            'to_socket_name':        link.to_socket.name,
        })

    return {
        'schema_version': '1.0',
        'name':           node_group.name,
        'type':           node_group.bl_idname,
        'interface':      _serialize_interface(node_group),
        'nodes':          nodes_data,
        'links':          links_data,
    }


def collect_all_groups(root_name: str) -> list:
    """
    Return a list of all node group names reachable from root_name,
    in dependency order (deepest dependencies first, root last).
    Works for both GeometryNodeGroup and ShaderNodeGroup references.
    Safe against circular references.
    """
    visited = set()
    order = []

    def _visit(name):
        if name in visited:
            return
        visited.add(name)
        ng = bpy.data.node_groups.get(name)
        if ng is None:
            return
        # Visit all nested group references first
        for node in ng.nodes:
            if (node.bl_idname in ('GeometryNodeGroup', 'ShaderNodeGroup')
                    and node.node_tree is not None):
                _visit(node.node_tree.name)
        order.append(name)

    _visit(root_name)
    return order
