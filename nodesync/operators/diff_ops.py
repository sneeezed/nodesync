"""
Operators for viewing diffs between the live node tree and the last commit.
"""

import bpy
import json

from .helpers import _get_project, _get_repo


class NODESYNC_OT_enter_diff(bpy.types.Operator):
    bl_idname  = 'nodesync.enter_diff'
    bl_label   = 'View Diff'
    bl_description = ('Compare the active node group against the last commit. '
                      'Green = added, Orange = modified, Red ghost = deleted.')

    @classmethod
    def poll(cls, context):
        sdata = context.space_data
        return (
            bool(context.scene.nodesync_project_root.strip())
            and sdata is not None
            and getattr(sdata, 'node_tree', None) is not None
            and not context.scene.nodesync_diff_active
        )

    def execute(self, context):
        scene     = context.scene
        node_tree = context.space_data.node_tree

        proj = _get_project(scene)
        if proj is None:
            self.report({'ERROR'}, "No active NodeSync project")
            return {'CANCELLED'}

        # Serialize the current live state
        from ..serializer import export_node_group
        current_data = export_node_group(node_tree)

        # Load the HEAD version from git
        safe_name    = node_tree.name.replace('/', '_').replace('\\', '_')
        git_rel_path = f'nodes/{safe_name}.json'

        try:
            repo = _get_repo(proj.root)
            head_json = repo.show_file_at_head(git_rel_path)
        except Exception as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}

        if head_json is None:
            # No commits yet or group never committed — everything is "new"
            head_data = {'nodes': [], 'links': []}
            self.report({'INFO'}, "No committed version found — all nodes marked as new")
        else:
            try:
                head_data = json.loads(head_json)
            except Exception as e:
                self.report({'ERROR'}, f"Could not parse HEAD JSON: {e}")
                return {'CANCELLED'}

        from ..diff import compute_diff, apply_diff_overlay
        diff = compute_diff(head_data, current_data)

        apply_diff_overlay(node_tree, diff)
        scene.nodesync_diff_active = True

        added    = len(diff['added'])
        modified = len(diff['modified'])
        removed  = len(diff['removed'])
        self.report({'INFO'},
                    f"Diff: {added} added, {modified} modified, {removed} deleted")
        return {'FINISHED'}


class NODESYNC_OT_diff_legend(bpy.types.Operator):
    bl_idname  = 'nodesync.diff_legend'
    bl_label   = 'Diff Legend'
    bl_description = 'Green = added  |  Orange = modified  |  Red ghost = deleted'

    def execute(self, context):
        return {'FINISHED'}


class NODESYNC_OT_exit_diff(bpy.types.Operator):
    bl_idname  = 'nodesync.exit_diff'
    bl_label   = 'Exit Diff'
    bl_description = 'Remove the diff overlay and restore original node colors'

    @classmethod
    def poll(cls, context):
        sdata = context.space_data
        return (
            context.scene.nodesync_diff_active
            and sdata is not None
            and getattr(sdata, 'node_tree', None) is not None
        )

    def execute(self, context):
        from ..diff import remove_diff_overlay
        node_tree = context.space_data.node_tree
        remove_diff_overlay(node_tree)
        context.scene.nodesync_diff_active = False
        self.report({'INFO'}, "Diff overlay removed")
        return {'FINISHED'}


classes = [
    NODESYNC_OT_enter_diff,
    NODESYNC_OT_diff_legend,
    NODESYNC_OT_exit_diff,
]
