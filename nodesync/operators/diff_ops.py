"""
Operators for viewing diffs between the live node tree and the last commit.
"""

import bpy
import json

from .helpers import _get_project, _get_repo, _resolve_tree_rel_path


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
        git_rel_path, _display = _resolve_tree_rel_path(node_tree)
        if not git_rel_path:
            self.report({'WARNING'}, "Active node tree is not tracked by NodeSync")
            return {'CANCELLED'}

        base_hash = scene.nodesync_diff_base_hash.strip()
        ref       = base_hash if base_hash else 'HEAD'
        ref_label = base_hash[:8] if base_hash else 'HEAD'

        try:
            repo     = _get_repo(proj.root)
            base_json = repo.show_file_at_commit(ref, git_rel_path)
        except Exception as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}

        if base_json is None:
            base_data = {'nodes': [], 'links': []}
            self.report({'INFO'},
                        f"No version of this group at {ref_label} — all nodes marked as new")
        else:
            try:
                base_data = json.loads(base_json)
            except Exception as e:
                self.report({'ERROR'}, f"Could not parse JSON at {ref_label}: {e}")
                return {'CANCELLED'}

        from ..diff import compute_diff, apply_diff_overlay
        diff = compute_diff(base_data, current_data)

        apply_diff_overlay(node_tree, diff)
        scene.nodesync_diff_active = True

        added    = len(diff['added'])
        modified = len(diff['modified'])
        removed  = len(diff['removed'])
        self.report({'INFO'},
                    f"Diff: live vs {ref_label} — "
                    f"{added} added, {modified} modified, {removed} deleted")
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


class NODESYNC_OT_set_diff_base(bpy.types.Operator):
    bl_idname  = 'nodesync.set_diff_base'
    bl_label   = 'Pin as Diff Base'
    bl_description = ('Pin this commit as the diff comparison base. '
                      "View Diff will compare the live tree against this "
                      'commit instead of HEAD. Click again to unpin.')

    commit_hash : bpy.props.StringProperty()

    @classmethod
    def poll(cls, context):
        return bool(context.scene.nodesync_project_root.strip())

    def execute(self, context):
        scene = context.scene
        if scene.nodesync_diff_base_hash == self.commit_hash:
            scene.nodesync_diff_base_hash = ''
            self.report({'INFO'}, "Diff base cleared — comparing against HEAD")
        else:
            scene.nodesync_diff_base_hash = self.commit_hash
            self.report({'INFO'}, f"Diff base pinned to {self.commit_hash[:8]}")
        return {'FINISHED'}


class NODESYNC_OT_clear_diff_base(bpy.types.Operator):
    bl_idname  = 'nodesync.clear_diff_base'
    bl_label   = 'Clear Diff Base'
    bl_description = 'Reset the diff comparison base back to HEAD'

    @classmethod
    def poll(cls, context):
        return bool(context.scene.nodesync_diff_base_hash)

    def execute(self, context):
        context.scene.nodesync_diff_base_hash = ''
        self.report({'INFO'}, "Diff base cleared — comparing against HEAD")
        return {'FINISHED'}


classes = [
    NODESYNC_OT_enter_diff,
    NODESYNC_OT_diff_legend,
    NODESYNC_OT_exit_diff,
    NODESYNC_OT_set_diff_base,
    NODESYNC_OT_clear_diff_base,
]
