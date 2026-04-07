"""
NodeSync Phase 1 — Round-trip test.

Run from Blender's scripting editor, or from the terminal:
    blender --background --python test_roundtrip.py

The script:
  1. Builds a known Geometry Node tree with a variety of node types.
  2. Exports it to a dict (and JSON string).
  3. Deletes the original from bpy.data.
  4. Reimports it from the dict.
  5. Asserts the reimported tree is identical to the original.
  6. Also tests a nested-group round-trip.

Prints PASSED or FAILED with details.
"""

import bpy
import json
import sys
import os
import math

# Make the nodesync package importable.
# __file__ is not always defined in Blender's text editor, so fall back to the
# hardcoded project root.
_NODESYNC_ROOT = '/Users/matiassevak/Desktop/nodesync'
try:
    _script_dir = os.path.dirname(os.path.abspath(__file__))
    if os.path.isdir(os.path.join(_script_dir, 'nodesync')):
        _NODESYNC_ROOT = _script_dir
except NameError:
    pass  # __file__ not defined in Blender scripting editor — use hardcoded path

if _NODESYNC_ROOT not in sys.path:
    sys.path.insert(0, _NODESYNC_ROOT)

from nodesync.serializer import export_node_group, collect_all_groups
from nodesync.deserializer import reconstruct_node_group, reconstruct_all


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FLOAT_EPSILON = 1e-4

def _approx_equal(a, b):
    """Recursively compare floats/lists/dicts with tolerance."""
    if isinstance(a, float) and isinstance(b, float):
        return math.isclose(a, b, rel_tol=1e-4, abs_tol=FLOAT_EPSILON)
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        return len(a) == len(b) and all(_approx_equal(x, y) for x, y in zip(a, b))
    return a == b


def _remove_group(name):
    if name in bpy.data.node_groups:
        bpy.data.node_groups.remove(bpy.data.node_groups[name])


def _report(errors, msg):
    errors.append(msg)
    print(f"  FAIL: {msg}")


# ---------------------------------------------------------------------------
# Tree builders
# ---------------------------------------------------------------------------

def build_basic_tree(name='NS_Test_Basic'):
    """
    A tree with:
    - Group Input / Output
    - Math node (MULTIPLY, non-default value on input)
    - Boolean Math node
    - Reroute
    - A named Frame containing the Math node
    - A custom color on one node
    """
    _remove_group(name)
    ng = bpy.data.node_groups.new(name, 'GeometryNodeTree')

    # Interface
    ng.interface.new_socket('Geometry', socket_type='NodeSocketGeometry', in_out='INPUT')
    ng.interface.new_socket('Value',    socket_type='NodeSocketFloat',    in_out='INPUT')
    ng.interface.new_socket('Geometry', socket_type='NodeSocketGeometry', in_out='OUTPUT')

    # Nodes
    gi = ng.nodes.new('NodeGroupInput')
    gi.location = (-400, 0)

    go = ng.nodes.new('NodeGroupOutput')
    go.location = (400, 0)

    math_node = ng.nodes.new('ShaderNodeMath')
    math_node.operation = 'MULTIPLY'
    math_node.use_clamp = True
    math_node.location = (0, 100)
    math_node.inputs[0].default_value = 2.718
    math_node.inputs[1].default_value = 3.14159
    math_node.use_custom_color = True
    math_node.color = (0.1, 0.5, 0.9)

    # Frame
    frame = ng.nodes.new('NodeFrame')
    frame.label = 'My Frame'
    frame.location = (-50, 130)
    frame.use_custom_color = True
    frame.color = (0.8, 0.3, 0.1)
    math_node.parent = frame

    # Reroute
    reroute = ng.nodes.new('NodeReroute')
    reroute.location = (200, 0)

    # Links: gi.geometry -> go.geometry (passthrough via reroute)
    ng.links.new(gi.outputs[0], reroute.inputs[0])
    ng.links.new(reroute.outputs[0], go.inputs[0])

    return ng


def build_nested_group(inner_name='NS_Test_Inner', outer_name='NS_Test_Outer'):
    """
    Inner group: simple value-through.
    Outer group: uses the inner group node.
    """
    # Inner
    _remove_group(inner_name)
    inner = bpy.data.node_groups.new(inner_name, 'GeometryNodeTree')
    inner.interface.new_socket('Value', socket_type='NodeSocketFloat', in_out='INPUT')
    inner.interface.new_socket('Value', socket_type='NodeSocketFloat', in_out='OUTPUT')
    ii = inner.nodes.new('NodeGroupInput')
    ii.location = (-200, 0)
    io_ = inner.nodes.new('NodeGroupOutput')
    io_.location = (200, 0)
    inner.links.new(ii.outputs[0], io_.inputs[0])

    # Outer
    _remove_group(outer_name)
    outer = bpy.data.node_groups.new(outer_name, 'GeometryNodeTree')
    outer.interface.new_socket('Value', socket_type='NodeSocketFloat', in_out='INPUT')
    outer.interface.new_socket('Value', socket_type='NodeSocketFloat', in_out='OUTPUT')
    oi = outer.nodes.new('NodeGroupInput')
    oi.location = (-400, 0)
    oo = outer.nodes.new('NodeGroupOutput')
    oo.location = (400, 0)
    grp = outer.nodes.new('GeometryNodeGroup')
    grp.node_tree = inner
    grp.location = (0, 0)
    outer.links.new(oi.outputs[0], grp.inputs[0])
    outer.links.new(grp.outputs[0], oo.inputs[0])

    return inner, outer


# ---------------------------------------------------------------------------
# Comparison helpers
# ---------------------------------------------------------------------------

def compare_interface(ng_a, ng_b, errors):
    """Compare group interface sockets."""
    if not (hasattr(ng_a, 'interface') and hasattr(ng_a.interface, 'items_tree')):
        return  # skip on 3.x

    socks_a = [i for i in ng_a.interface.items_tree if i.item_type == 'SOCKET']
    socks_b = [i for i in ng_b.interface.items_tree if i.item_type == 'SOCKET']

    if len(socks_a) != len(socks_b):
        _report(errors, f"Interface socket count: {len(socks_a)} vs {len(socks_b)}")
        return

    for a, b in zip(socks_a, socks_b):
        if a.name != b.name:
            _report(errors, f"Interface socket name mismatch: '{a.name}' vs '{b.name}'")
        if a.socket_type != b.socket_type:
            _report(errors, f"Interface socket type mismatch on '{a.name}': "
                            f"{a.socket_type} vs {b.socket_type}")
        if a.in_out != b.in_out:
            _report(errors, f"Interface socket in_out mismatch on '{a.name}': "
                            f"{a.in_out} vs {b.in_out}")


def compare_nodes(ng_a, ng_b, errors):
    """Compare all nodes between two trees."""
    names_a = {n.name: n for n in ng_a.nodes}
    names_b = {n.name: n for n in ng_b.nodes}

    if len(names_a) != len(names_b):
        _report(errors, f"Node count: {len(names_a)} vs {len(names_b)}")

    for name, na in names_a.items():
        if name not in names_b:
            _report(errors, f"Node missing after reimport: '{name}'")
            continue
        nb = names_b[name]

        if na.bl_idname != nb.bl_idname:
            _report(errors, f"Node '{name}': bl_idname {na.bl_idname} != {nb.bl_idname}")

        if not _approx_equal(na.location.x, nb.location.x) or \
           not _approx_equal(na.location.y, nb.location.y):
            _report(errors, f"Node '{name}': location {list(na.location)} != {list(nb.location)}")

        if na.hide != nb.hide:
            _report(errors, f"Node '{name}': hide {na.hide} != {nb.hide}")

        if na.mute != nb.mute:
            _report(errors, f"Node '{name}': mute {na.mute} != {nb.mute}")

        if na.use_custom_color != nb.use_custom_color:
            _report(errors, f"Node '{name}': use_custom_color mismatch")
        elif na.use_custom_color:
            if not _approx_equal(list(na.color), list(nb.color)):
                _report(errors, f"Node '{name}': color {list(na.color)} != {list(nb.color)}")

        # Parent frame
        parent_a = na.parent.name if na.parent else None
        parent_b = nb.parent.name if nb.parent else None
        if parent_a != parent_b:
            _report(errors, f"Node '{name}': parent '{parent_a}' != '{parent_b}'")

        # type_specific spot checks
        if na.bl_idname == 'ShaderNodeMath':
            if na.operation != nb.operation:
                _report(errors, f"Node '{name}': operation {na.operation} != {nb.operation}")
            if na.use_clamp != nb.use_clamp:
                _report(errors, f"Node '{name}': use_clamp {na.use_clamp} != {nb.use_clamp}")

        if na.bl_idname == 'GeometryNodeGroup':
            ref_a = na.node_tree.name if na.node_tree else None
            ref_b = nb.node_tree.name if nb.node_tree else None
            if ref_a != ref_b:
                _report(errors, f"Node '{name}': node_tree_ref '{ref_a}' != '{ref_b}'")

    # Check for extra nodes in b
    for name in names_b:
        if name not in names_a:
            _report(errors, f"Extra node after reimport: '{name}'")


def compare_socket_defaults(ng_a, ng_b, errors):
    """Compare socket default values on all nodes."""
    nodes_a = {n.name: n for n in ng_a.nodes}
    nodes_b = {n.name: n for n in ng_b.nodes}

    for name, na in nodes_a.items():
        nb = nodes_b.get(name)
        if nb is None:
            continue
        for side, socks_a, socks_b in [
            ('inputs',  na.inputs,  nb.inputs),
            ('outputs', na.outputs, nb.outputs),
        ]:
            id_map_b = {s.identifier: s for s in socks_b}
            for sa in socks_a:
                sb = id_map_b.get(sa.identifier)
                if sb is None:
                    _report(errors, f"Node '{name}' {side}: socket '{sa.identifier}' "
                                    f"missing after reimport")
                    continue
                if not hasattr(sa, 'default_value') or not hasattr(sb, 'default_value'):
                    continue
                try:
                    va, vb = sa.default_value, sb.default_value
                    # Convert mathutils to list for comparison
                    if hasattr(va, '__iter__') and not isinstance(va, str):
                        va, vb = list(va), list(vb)
                    if not _approx_equal(va, vb):
                        _report(errors, f"Node '{name}' {side} socket '{sa.name}': "
                                        f"default_value {va!r} != {vb!r}")
                except Exception:
                    pass


def compare_links(ng_a, ng_b, errors):
    """Compare all links by (from_node, from_socket_id, to_node, to_socket_id)."""
    def link_key(link):
        return (link.from_node.name, link.from_socket.identifier,
                link.to_node.name,   link.to_socket.identifier)

    links_a = {link_key(l) for l in ng_a.links}
    links_b = {link_key(l) for l in ng_b.links}

    if len(links_a) != len(links_b):
        _report(errors, f"Link count: {len(links_a)} vs {len(links_b)}")

    for key in links_a - links_b:
        _report(errors, f"Link missing after reimport: {key}")
    for key in links_b - links_a:
        _report(errors, f"Extra link after reimport: {key}")


def assert_trees_equal(ng_a, ng_b):
    """Full comparison. Returns list of error strings (empty = identical)."""
    errors = []
    compare_interface(ng_a, ng_b, errors)
    compare_nodes(ng_a, ng_b, errors)
    compare_socket_defaults(ng_a, ng_b, errors)
    compare_links(ng_a, ng_b, errors)
    return errors


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_basic_roundtrip():
    print("\n--- Test: Basic round-trip ---")
    ng_orig = build_basic_tree('NS_Test_Basic')

    # Export
    data = export_node_group(ng_orig)
    json_str = json.dumps(data, indent=2)
    print(f"  Exported {len(ng_orig.nodes)} nodes, "
          f"{len(ng_orig.links)} links, "
          f"{len(json_str)} JSON bytes")

    # Keep a reference snapshot for comparison
    ng_ref = build_basic_tree('NS_Test_Basic_Ref')

    # Delete original
    _remove_group('NS_Test_Basic')
    assert 'NS_Test_Basic' not in bpy.data.node_groups, "Delete failed"

    # Reimport from dict (NOT from json_str — same data, avoids re-parse noise)
    ng_reimported = reconstruct_node_group(data)
    assert ng_reimported is not None, "reconstruct_node_group returned None"

    errors = assert_trees_equal(ng_ref, ng_reimported)

    # Cleanup
    _remove_group('NS_Test_Basic')
    _remove_group('NS_Test_Basic_Ref')

    return errors


def test_json_serialization():
    """Verify the dict survives a JSON encode/decode cycle."""
    print("\n--- Test: JSON encode/decode ---")
    ng_orig = build_basic_tree('NS_Test_JSON')
    data = export_node_group(ng_orig)

    json_str = json.dumps(data)
    data2 = json.loads(json_str)

    # Re-import from the round-tripped dict
    _remove_group('NS_Test_JSON')
    ng_reimported = reconstruct_node_group(data2)
    assert ng_reimported is not None

    ng_ref = build_basic_tree('NS_Test_JSON_Ref')
    errors = assert_trees_equal(ng_ref, ng_reimported)

    _remove_group('NS_Test_JSON')
    _remove_group('NS_Test_JSON_Ref')
    return errors


def test_nested_groups():
    print("\n--- Test: Nested group round-trip ---")
    inner, outer = build_nested_group('NS_Inner', 'NS_Outer')

    # Collect dependency order and export both
    all_names = collect_all_groups('NS_Outer')
    all_data = [export_node_group(bpy.data.node_groups[n]) for n in all_names]

    json_str = json.dumps(all_data, indent=2)
    print(f"  Exported {len(all_names)} groups, {len(json_str)} JSON bytes")
    print(f"  Export order: {all_names}")

    # Keep refs
    inner_ref, outer_ref = build_nested_group('NS_Inner_Ref', 'NS_Outer_Ref')

    # Delete originals
    _remove_group('NS_Inner')
    _remove_group('NS_Outer')

    # Reimport in dependency order (inner first, outer last)
    all_data_rt = json.loads(json_str)
    results = reconstruct_all(all_data_rt)

    errors = []
    if 'NS_Inner' not in results:
        errors.append("NS_Inner not in results")
    if 'NS_Outer' not in results:
        errors.append("NS_Outer not in results")

    if 'NS_Inner' in results:
        errors.extend(assert_trees_equal(inner_ref, results['NS_Inner']))
    if 'NS_Outer' in results:
        errors.extend(assert_trees_equal(outer_ref, results['NS_Outer']))

    # Cleanup
    for n in ['NS_Inner', 'NS_Outer', 'NS_Inner_Ref', 'NS_Outer_Ref']:
        _remove_group(n)

    return errors


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run_all_tests():
    print("=" * 60)
    print("NodeSync Phase 1 — Round-trip Tests")
    print("=" * 60)

    results = {}
    for test_fn in [test_basic_roundtrip, test_json_serialization, test_nested_groups]:
        name = test_fn.__name__
        try:
            errors = test_fn()
            if errors:
                results[name] = ('FAILED', errors)
                print(f"  => FAILED ({len(errors)} error(s))")
            else:
                results[name] = ('PASSED', [])
                print(f"  => PASSED")
        except Exception as e:
            import traceback
            results[name] = ('ERROR', [str(e)])
            print(f"  => ERROR: {e}")
            traceback.print_exc()

    print("\n" + "=" * 60)
    print("Summary")
    print("=" * 60)
    all_passed = True
    for name, (status, errs) in results.items():
        icon = '✓' if status == 'PASSED' else '✗'
        print(f"  {icon} {name}: {status}")
        for e in errs:
            print(f"      {e}")
        if status != 'PASSED':
            all_passed = False

    print()
    if all_passed:
        print("ALL TESTS PASSED")
    else:
        print("SOME TESTS FAILED — see details above")
    print("=" * 60)


run_all_tests()
