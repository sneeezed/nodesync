"""
Deserializer: reconstruct a bpy GeometryNodeTree from a serialized dict.

Usage:
    from nodesync.deserializer import reconstruct_node_group
    ng = reconstruct_node_group(data)   # data is a dict from export_node_group()
"""

import bpy
from .utils import deserialize_default_value, NO_DEFAULT_VALUE_SOCKETS


def _apply_interface_item_props(item, d: dict):
    """Write stored values onto an existing interface socket item."""
    dv = d.get('default_value')
    if dv is not None and hasattr(item, 'default_value'):
        try:
            item.default_value = deserialize_default_value(d['socket_type'], dv)
        except Exception:
            pass
    min_v = d.get('min_value')
    if min_v is not None and hasattr(item, 'min_value'):
        try:
            item.min_value = min_v
        except Exception:
            pass
    max_v = d.get('max_value')
    if max_v is not None and hasattr(item, 'max_value'):
        try:
            item.max_value = max_v
        except Exception:
            pass
    ad = d.get('attribute_domain')
    if ad is not None and hasattr(item, 'attribute_domain'):
        try:
            item.attribute_domain = ad
        except Exception:
            pass


def _restore_interface(node_group, interface_data: list):
    """
    Rebuild the group's exposed interface sockets (Blender 4.x API).
    Falls back to legacy API for 3.x.

    When the interface structure is unchanged (same count, socket types, and
    directions in the same order), existing items are updated in-place so that
    their Blender-assigned identifiers (Socket_N) are preserved.  This prevents
    spurious identifier drift in git history when only node internals change.

    When the structure has genuinely changed the items are cleared and
    recreated, which is expected and correctly reflected in the commit diff.
    """
    if not interface_data:
        return

    # Blender 4.x
    if hasattr(node_group, 'interface') and hasattr(node_group.interface, 'new_socket'):
        existing = [
            item for item in node_group.interface.items_tree
            if item.item_type == 'SOCKET'
        ]

        # If structure is identical (same count + socket_type + in_out at each
        # position) update properties in-place to keep the original identifiers.
        if len(existing) == len(interface_data) and all(
            e.socket_type == d['socket_type'] and e.in_out == d['in_out']
            for e, d in zip(existing, interface_data)
        ):
            for item, d in zip(existing, interface_data):
                try:
                    item.name = d['name']
                except Exception:
                    pass
                _apply_interface_item_props(item, d)
            return

        # Structure changed — clear and recreate.
        for item in list(node_group.interface.items_tree):
            try:
                node_group.interface.remove(item)
            except Exception:
                pass
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
            _apply_interface_item_props(socket, item_data)
        return

    # Blender 3.x fallback (deprecated but kept for compatibility)
    while getattr(node_group, 'inputs', None):
        node_group.inputs.remove(node_group.inputs[0])
    while getattr(node_group, 'outputs', None):
        node_group.outputs.remove(node_group.outputs[0])
    for item_data in interface_data:
        in_out = item_data.get('in_out', 'INPUT')
        try:
            if in_out == 'INPUT':
                sock = node_group.inputs.new(item_data['socket_type'], item_data['name'])
            else:
                sock = node_group.outputs.new(item_data['socket_type'], item_data['name'])
            _apply_interface_item_props(sock, item_data)
        except Exception as e:
            print(f"[NodeSync] 3.x interface socket creation failed: {e}")


def _resolve_image(image_name: str, image_filepath: str,
                   project_root: str | None) -> 'bpy.types.Image | None':
    """
    Find or load a bpy.types.Image by name.  Lookup order:
      1. bpy.data.images by exact name (already in memory)
      2. bpy.data.images by filepath (avoids duplicates for differently-named reloads)
      3. Load from project textures/ directory (uses image_name as filename)
      4. Load from the stored image_filepath (absolute or blend-relative)
    Returns None if the image cannot be found or loaded.
    """
    import os

    # 1. Exact name match
    img = bpy.data.images.get(image_name)
    if img is not None:
        return img

    # 2. Already loaded under same filepath
    if project_root:
        tex_path = os.path.join(project_root, 'textures', image_name)
        if os.path.isfile(tex_path):
            for existing in bpy.data.images:
                if bpy.path.abspath(existing.filepath) == os.path.abspath(tex_path):
                    return existing
            try:
                img = bpy.data.images.load(tex_path, check_existing=True)
                img.name = image_name
                return img
            except Exception as e:
                print(f"[NodeSync] Could not load texture from textures/: {e}")

    # 3. Load from the original filepath recorded at export time
    if image_filepath:
        abs_fp = bpy.path.abspath(image_filepath)
        if os.path.isfile(abs_fp):
            try:
                img = bpy.data.images.load(abs_fp, check_existing=True)
                return img
            except Exception as e:
                print(f"[NodeSync] Could not load image from original path: {e}")

    return None


def _apply_type_specific(node, ts: dict, project_root: str | None = None):
    """
    Apply type_specific properties to a node.
    Must be called BEFORE reading socket identifiers (some props add/remove sockets).
    project_root is forwarded to _resolve_image for texture lookup.
    """
    if not ts:
        return

    bl_idname = node.bl_idname

    # GROUP: resolve node tree reference
    if bl_idname in ('GeometryNodeGroup', 'ShaderNodeGroup'):
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

    # Image-referencing nodes: restore .image before other props
    if bl_idname in ('ShaderNodeTexImage', 'ShaderNodeTexEnvironment'):
        image_name = ts.get('image_name')
        if image_name:
            img = _resolve_image(
                image_name,
                ts.get('image_filepath') or '',
                project_root,
            )
            if img is not None:
                try:
                    node.image = img
                except Exception as e:
                    print(f"[NodeSync] Could not assign image '{image_name}': {e}")
            else:
                print(f"[NodeSync] Image '{image_name}' not found — "
                      f"node will have no texture assigned")
        # Fall through to also restore interpolation / projection / extension

    # General case — skip image_name / image_filepath (data-block refs, not settable)
    skip = {'image_name', 'image_filepath'}
    for prop, val in ts.items():
        if prop in skip:
            continue
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


def reconstruct_node_group(data: dict, project_root: str | None = None):
    """
    Reconstruct a node group from a serialized dict.
    If a group with this name already exists it is cleared and rebuilt in place.
    Returns the reconstructed bpy node group, or None on failure.

    project_root is the filesystem root of the NodeSync project; when provided
    it is used to resolve ShaderNodeTexImage images from the textures/ folder.
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
        # Interface clearing is handled inside _restore_interface, which will
        # update items in-place when the structure is unchanged (preserving
        # Blender-assigned Socket_N identifiers) and only clear+recreate when
        # sockets are genuinely added/removed/reordered/retyped.
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
        _apply_type_specific(node, ndata.get('type_specific', {}), project_root)

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


def _rebuild_tree_in_place(ng, data: dict, project_root: str | None = None):
    """
    Clear ng's nodes/links and rebuild them from data — without touching the
    surrounding bpy data-block.  Used both for standalone groups (after they
    are created/cleared in reconstruct_node_group) and for embedded shader
    trees owned by a Material/World/Light.

    Splits the create-then-link pass out of reconstruct_node_group so it can
    be reused without name lookups against bpy.data.node_groups.
    """
    _restore_interface(ng, data.get('interface', []))

    node_map = {}
    for ndata in data.get('nodes', []):
        bl_idname = ndata['bl_idname']
        try:
            node = ng.nodes.new(bl_idname)
        except Exception as e:
            print(f"[NodeSync] Could not create node '{ndata['name']}' "
                  f"({bl_idname}): {e}")
            continue

        node.name  = ndata['name']
        node.label = ndata.get('label', '')
        _apply_type_specific(node, ndata.get('type_specific', {}), project_root)
        _restore_socket_defaults(node, ndata.get('inputs', []),  is_input=True)
        _restore_socket_defaults(node, ndata.get('outputs', []), is_input=False)

        loc = ndata.get('location', [0.0, 0.0])
        node.location = (loc[0], loc[1])
        node.width    = ndata.get('width', 140.0)
        node.hide     = ndata.get('hide', False)
        node.mute     = ndata.get('mute', False)
        node.use_custom_color = ndata.get('use_custom_color', False)
        color = ndata.get('color', [0.608, 0.608, 0.608])
        node.color = (color[0], color[1], color[2])

        node_map[ndata['name']] = node

    for ndata in data.get('nodes', []):
        parent_name = ndata.get('parent')
        if parent_name and parent_name in node_map and ndata['name'] in node_map:
            node_map[ndata['name']].parent = node_map[parent_name]

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


def reconstruct_embedded_shader(data: dict, project_root: str | None = None):
    """
    Reconstruct a shader node tree owned by a Material / World / Light.
    Looks at data['owner_type'] ('materials' / 'worlds' / 'lights') and
    data['owner_name'] to find or create the owner data-block, then rebuilds
    its embedded node_tree in place.
    project_root is forwarded to image resolution so ShaderNodeTexImage nodes
    can load files from the project textures/ directory.
    Returns the owner data-block, or None on failure.
    """
    owner_type = data.get('owner_type')
    owner_name = data.get('owner_name') or data.get('name')
    if owner_type not in {'materials', 'worlds', 'lights'} or not owner_name:
        print("[NodeSync] reconstruct_embedded_shader: missing owner_type/owner_name")
        return None

    collection = getattr(bpy.data, owner_type, None)
    if collection is None:
        print(f"[NodeSync] bpy.data.{owner_type} not available")
        return None

    owner = collection.get(owner_name)
    if owner is None:
        # Create a new data-block of the right kind so the embedded tree has a home
        try:
            if owner_type == 'materials':
                owner = bpy.data.materials.new(owner_name)
            elif owner_type == 'worlds':
                owner = bpy.data.worlds.new(owner_name)
            elif owner_type == 'lights':
                # Default to POINT — there's no light shader without a light type
                owner = bpy.data.lights.new(owner_name, type='POINT')
        except Exception as e:
            print(f"[NodeSync] Could not create {owner_type[:-1]} '{owner_name}': {e}")
            return None

    try:
        owner.use_nodes = True
    except Exception as e:
        print(f"[NodeSync] Could not enable nodes on {owner_type[:-1]} "
              f"'{owner_name}': {e}")
        return None

    nt = owner.node_tree
    if nt is None:
        print(f"[NodeSync] {owner_type[:-1]} '{owner_name}' has no node_tree")
        return None

    nt.nodes.clear()  # also clears all links
    _rebuild_tree_in_place(nt, data, project_root)
    return owner


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
