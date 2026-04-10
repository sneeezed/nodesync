"""
Operators for resolving merge conflicts.
"""

import bpy
import os

from .helpers import _get_project, _refresh_branches, _refresh_history
from .modifier_links import _snapshot_modifier_links, _restore_modifier_links


class NODESYNC_OT_resolve_conflict(bpy.types.Operator):
    bl_idname      = 'nodesync.resolve_conflict'
    bl_label       = 'Resolve'
    bl_description = 'Resolve this conflict by keeping one version'

    filepath : bpy.props.StringProperty()
    strategy : bpy.props.StringProperty()   # 'ours' or 'theirs'

    @classmethod
    def poll(cls, context):
        return (bool(context.scene.nodesync_project_root.strip())
                and context.scene.nodesync_has_conflicts)

    def execute(self, context):
        scene = context.scene
        proj  = _get_project(scene)
        if proj is None:
            self.report({'ERROR'}, "No active NodeSync project")
            return {'CANCELLED'}

        from ..git_ops import GitRepo, GitError
        try:
            repo = GitRepo(proj.root)
            if self.strategy == 'ours':
                repo.resolve_ours(self.filepath)
            elif self.strategy == 'theirs':
                repo.resolve_theirs(self.filepath)
            else:
                self.report({'ERROR'}, f"Unknown strategy: {self.strategy}")
                return {'CANCELLED'}
        except GitError as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}

        # Mark item as resolved
        for item in scene.nodesync_conflict_items:
            if item.filepath == self.filepath:
                item.resolved = True
                break

        label = 'local' if self.strategy == 'ours' else 'remote'
        self.report({'INFO'}, f"Kept {label} version of {os.path.basename(self.filepath)}")
        return {'FINISHED'}


class NODESYNC_OT_complete_merge(bpy.types.Operator):
    bl_idname      = 'nodesync.complete_merge'
    bl_label       = 'Complete Merge'
    bl_description = 'Finalize the merge commit after resolving all conflicts'

    @classmethod
    def poll(cls, context):
        scene = context.scene
        if not scene.nodesync_has_conflicts:
            return False
        return all(item.resolved for item in scene.nodesync_conflict_items)

    def execute(self, context):
        scene = context.scene
        proj  = _get_project(scene)
        if proj is None:
            self.report({'ERROR'}, "No active NodeSync project")
            return {'CANCELLED'}

        from ..git_ops import GitRepo, GitError
        try:
            repo      = GitRepo(proj.root)
            short_hash = repo.complete_merge()
        except GitError as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}

        # Reload all node groups from the merged state
        _snapshot_modifier_links()
        imported = proj.import_all_from_disk()
        _restore_modifier_links(imported)
        scene.nodesync_conflict_items.clear()
        scene.nodesync_has_conflicts  = False
        scene.nodesync_sync_status    = 'Merge complete'
        _refresh_branches(scene, proj.root)
        _refresh_history(scene, proj.root)
        self.report({'INFO'},
                    f"Merge complete [{short_hash}] — reimported {len(imported)} group(s)")
        return {'FINISHED'}


class NODESYNC_OT_abort_merge(bpy.types.Operator):
    bl_idname      = 'nodesync.abort_merge'
    bl_label       = 'Abort Merge'
    bl_description = 'Cancel the merge and return to the pre-merge state'

    @classmethod
    def poll(cls, context):
        return context.scene.nodesync_has_conflicts

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
            repo.abort_merge()
        except GitError as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}

        _snapshot_modifier_links()
        imported = proj.import_all_from_disk()
        _restore_modifier_links(imported)
        scene.nodesync_conflict_items.clear()
        scene.nodesync_has_conflicts  = False
        scene.nodesync_sync_status    = 'Merge aborted'
        _refresh_branches(scene, proj.root)
        _refresh_history(scene, proj.root)
        self.report({'INFO'}, f"Merge aborted — reverted to pre-merge state ({len(imported)} groups reloaded)")
        return {'FINISHED'}


classes = [
    NODESYNC_OT_resolve_conflict,
    NODESYNC_OT_complete_merge,
    NODESYNC_OT_abort_merge,
]
