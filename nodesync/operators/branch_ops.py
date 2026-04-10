"""
Operators for creating and switching git branches.
"""

import bpy

from .helpers import _get_project, _refresh_branches, _refresh_history
from .modifier_links import _snapshot_modifier_links, _restore_modifier_links


class NODESYNC_OT_create_branch(bpy.types.Operator):
    bl_idname      = 'nodesync.create_branch'
    bl_label       = 'Create Branch'
    bl_description = 'Create a new git branch with a display color'

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=280)

    def draw(self, context):
        self.layout.prop(context.scene, 'nodesync_new_branch_name', text='Name')

    @classmethod
    def poll(cls, context):
        return bool(context.scene.nodesync_project_root.strip())

    def execute(self, context):
        scene = context.scene
        name  = scene.nodesync_new_branch_name.strip()
        if not name:
            self.report({'ERROR'}, "Enter a branch name")
            return {'CANCELLED'}

        proj = _get_project(scene)
        if proj is None:
            self.report({'ERROR'}, "No active NodeSync project")
            return {'CANCELLED'}

        from ..git_ops import GitRepo, GitError
        try:
            repo = GitRepo(proj.root)
            repo.create_branch(name)
        except GitError as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}

        scene.nodesync_new_branch_name = ''

        _refresh_branches(scene, proj.root)
        _refresh_history(scene, proj.root)
        self.report({'INFO'}, f"Created and switched to branch '{name}'")
        return {'FINISHED'}


class NODESYNC_OT_switch_branch(bpy.types.Operator):
    bl_idname      = 'nodesync.switch_branch'
    bl_label       = 'Switch'
    bl_description = 'Switch to this branch and reload node groups'

    branch_name : bpy.props.StringProperty()

    @classmethod
    def poll(cls, context):
        return bool(context.scene.nodesync_project_root.strip())

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        scene = context.scene
        proj  = _get_project(scene)
        if proj is None:
            self.report({'ERROR'}, "No active NodeSync project")
            return {'CANCELLED'}

        from ..git_ops import GitRepo, GitError
        try:
            repo = GitRepo(proj.root)
            repo.switch_branch(self.branch_name)
        except GitError as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}

        _snapshot_modifier_links()
        imported = proj.import_all_from_disk()
        _restore_modifier_links(imported)
        _refresh_branches(scene, proj.root)
        _refresh_history(scene, proj.root)
        self.report({'INFO'},
                    f"Switched to '{self.branch_name}' — reimported {len(imported)} group(s)")
        return {'FINISHED'}


classes = [
    NODESYNC_OT_create_branch,
    NODESYNC_OT_switch_branch,
]
