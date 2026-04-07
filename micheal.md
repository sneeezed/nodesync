NodeSync — Implementation Plan
Addon Structure

nodesync/
├── __init__.py        # bl_info, register/unregister, save_post hook
├── serializer.py      # export_node_group() → dict
├── deserializer.py    # reconstruct_node_group(dict) → bpy node group
├── git_ops.py         # GitRepo class wrapping subprocess calls
├── project.py         # project init, .nodesync config, path helpers
├── operators.py       # all bpy.types.Operator subclasses
├── panels.py          # all bpy.types.Panel + UIList subclasses
├── props.py           # PropertyGroup types registered on Scene
└── utils.py           # socket type helpers, safe default_value reader
Phase 1 — Serializer + Deserializer
JSON Schema (one file per node group):


{
  "schema_version": "1.0",
  "name": "MyGeoGroup",
  "type": "GeometryNodeTree",
  "interface": [
    { "name": "Geometry", "socket_type": "NodeSocketGeometry", "in_out": "INPUT",
      "default_value": null, "min_value": null, "max_value": null }
  ],
  "nodes": [
    {
      "name": "Math", "label": "Add Float", "bl_idname": "ShaderNodeMath",
      "location": [200.0, 100.0], "width": 140.0,
      "hide": false, "mute": false, "use_custom_color": false,
      "color": [0.608, 0.608, 0.608], "parent": null,
      "type_specific": { "operation": "ADD", "use_clamp": false },
      "inputs": [
        { "identifier": "Input_0", "name": "Value", "socket_type": "NodeSocketFloat",
          "default_value": 0.5, "hide": false, "hide_value": false }
      ],
      "outputs": [...]
    }
  ],
  "links": [
    { "from_node": "Group Input", "from_socket_identifier": "Output_0",
      "to_node": "Math", "to_socket_identifier": "Input_0" }
  ]
}
Key design decisions:

Sockets matched by identifier (stable across renames), never by list index
type_specific uses a dispatch dict keyed on bl_idname (e.g. ShaderNodeMath → ['operation', 'use_clamp'])
Group nodes store node_tree_ref: name — never inline recursion
Blender 4.x interface API: ng.interface.items_tree for reading, ng.interface.new_socket() for writing (not the deprecated ng.inputs/ng.outputs)
Vector/Color default_value returns mathutils objects — serialize as list(val)
Geometry/Object/Image sockets have no default_value — guard with hasattr + try/except
Nesting without infinite recursion:

A collect_all_referenced_groups(root_name) walk builds a topologically-ordered list of all reachable groups using a visited: set. Export/import that list with dependencies first, root last. Circular refs are impossible in Blender's editor but the visited-set guards defensively.

Deserialization order:

Create/clear the node group
Rebuild interface sockets
Create all nodes (set type_specific props before reading sockets)
Two-pass parent assignment (Frame nodes must exist before children reference them)
Match socket defaults by identifier
Rebuild links
Round-trip test — run via blender --background --python test_roundtrip.py:

Build a known tree programmatically
Export → delete → reimport
Assert: node count, names, bl_idnames, locations (float tolerance), link count, socket identifiers, type_specific props, frame parent assignments
Phase 2 — Project Initialization
Folder structure created on "Init Project":


<project_root>/
├── .git/
├── .nodesync          ← JSON config: { "version", "tracked_groups", "blend_file" }
└── nodes/
    └── MyGeoGroup.json
NodeSyncProject class handles: config load/save, node_file_path(group_name), walking up from the .blend file to find the project root.

Phase 3 — Git Interface Layer
GitRepo class wraps subprocess calls. All commands run with cwd=self.root, capture_output=True, timeout=30. Two exception types: GitNotFoundError (no git in PATH) and GitError (non-zero exit). Methods:

Method	Git command
init()	git init + configure identity if missing
add(path)	git add <path>
commit(msg)	git commit -m <msg>
current_branch()	git rev-parse --abbrev-ref HEAD
log(n=20)	git log -N --pretty=format:%H\x1f%s\x1f%an\x1f%ai
checkout(ref)	git checkout <ref>
create_branch(name)	git checkout -b <name>
push(remote, branch)	git push <remote> [branch]
pull(remote, branch)	git pull <remote> [branch]
is_repo()	git rev-parse --git-dir
Phase 4 — Auto-Export Save Hook

@bpy.app.handlers.persistent
def _on_save_post(filepath):   # Note: 4.x signature takes filepath, use *args for compatibility
    # Export all tracked groups to nodes/ — never let exceptions crash Blender's save
Registered in bpy.app.handlers.save_post. @persistent keeps it alive across file opens. Only accesses bpy.context.scene and bpy.data — never calls bpy.ops or accesses context.area (both are unsafe in save handlers).

Phase 5 — Blender UI Panel
Panel hierarchy in the Geometry Node editor N-panel (bl_space_type='NODE_EDITOR', bl_region_type='UI', bl_category='NodeSync'):


NODE_PT_nodesync                  ← root tab
├── NODE_PT_nodesync_project      ← folder path, Init/Open buttons, branch display
├── NODE_PT_nodesync_nodes        ← per-group checkboxes (toggle tracking)
└── NODE_PT_nodesync_vc           ← commit message input, Commit button, Push/Pull
poll() checks context.space_data is not None and context.space_data.tree_type == 'GeometryNodeTree'.

Scene properties registered in register():

nodesync_project_root — StringProperty(subtype='DIR_PATH')
nodesync_commit_message — StringProperty
nodesync_commit_history — CollectionProperty(type=NodeSyncCommitItem)
nodesync_history_index — IntProperty
Operators:

NODESYNC_OT_init_project — git init + folder structure
NODESYNC_OT_toggle_track — toggle group_name in config's tracked_groups
NODESYNC_OT_commit — export all tracked → git add nodes/ → git commit
NODESYNC_OT_push / NODESYNC_OT_pull
NODESYNC_OT_export_group / NODESYNC_OT_import_group (manual)
Phase 6 — History Panel
NODESYNC_UL_history UIList shows hash + subject per row with a "Checkout" button. NODESYNC_OT_refresh_history reads repo.log(20) into scene.nodesync_commit_history. NODESYNC_OT_checkout_commit calls repo.checkout(hash) then reimports all tracked groups from disk.

Critical Blender 4.x Gotchas
ng.inputs/ng.outputs deprecated — use ng.interface.new_socket() and ng.interface.items_tree
Set type_specific props before reading socket identifiers — changing data_type on some nodes adds/removes sockets dynamically
node.name auto-deduplicates — set name immediately after nodes.new(), before adding other nodes
Frames need two-pass parent assignment — all nodes must exist before .parent is assigned
Vector default_value is mathutils.Vector — call list(val) before JSON serialization
Geometry/Object/Image sockets have no default_value — always hasattr + try/except
nodes.clear() also clears links — don't call links.clear() separately
save_post handler signature — use def handler(*args) for 3.x/4.x compatibility
Build Order & Gate Conditions
Phase	Gate
1 Serializer + Deserializer	Round-trip test passes (export→delete→reimport = identical)
2 Project init	nodes/ dir + .nodesync created, git init ran
3 Git layer	git commit appears in git log, GitNotFoundError shown cleanly
4 Save hook	Saving .blend writes JSON files to nodes/
5 UI panel	N-panel visible, Commit button works end-to-end
6 History	Scroll commits, Checkout restores node tree
Ready to start? I'd suggest beginning with Phase 1 — the serializer + deserializer + round-trip test, since that's the foundation everything else depends on. Want me to write the code now?