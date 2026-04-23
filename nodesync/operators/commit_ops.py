"""
Operators for committing, restoring, and filtering commit history.
"""

import bpy
import os

from .helpers import (
    _get_project,
    _get_token,
    _refresh_branches,
    _refresh_history,
    _pending_pull_changes,
    _resolve_tree_rel_path,
)
from .modifier_links import _snapshot_modifier_links, _restore_modifier_links


class NODESYNC_OT_commit(bpy.types.Operator):
    bl_idname  = 'nodesync.commit'
    bl_label   = 'Commit'
    bl_description = 'Export tracked node groups to JSON and create a Git commit'

    @classmethod
    def poll(cls, context):
        return bool(context.scene.nodesync_project_root.strip())

    def execute(self, context):
        scene = context.scene
        msg   = scene.nodesync_commit_message.strip()
        if not msg:
            self.report({'ERROR'}, "Enter a commit message first")
            return {'CANCELLED'}

        proj = _get_project(scene)
        if proj is None:
            self.report({'ERROR'}, "No active NodeSync project")
            return {'CANCELLED'}

        # Export all tracked node groups (Geometry + Shader)
        exported = proj.export_all_groups()
        if not exported:
            self.report({'WARNING'}, "No tracked node groups found in file")
            return {'CANCELLED'}

        # Optionally collect referenced shader textures into textures/
        try:
            prefs = context.preferences.addons[__package__.split('.')[0]].preferences
            track_textures = prefs.track_textures
        except Exception:
            track_textures = False

        textures_written = 0
        if track_textures:
            try:
                textures_written = len(proj.collect_shader_textures())
            except Exception as e:
                self.report({'WARNING'}, f"Texture collection failed: {e}")

        from ..git_ops import GitRepo, GitNotFoundError, GitError
        try:
            repo = GitRepo(proj.root)
            repo.add('nodes/')
            if track_textures and textures_written:
                repo.add('textures/')
            # Also commit .nodesync config
            repo.add(os.path.join(proj.root, '.nodesync'))
            short_hash = repo.commit(msg)
            full_hash  = repo.current_commit_hash(short=False)
            scene.nodesync_commit_message = ''
            scene.nodesync_restore_hash   = ''  # back to HEAD, clear revert marker
            _refresh_branches(scene, proj.root)
            _refresh_history(scene, proj.root)
            self.report({'INFO'},
                        f"Committed {len(exported)} group(s) [{short_hash}]: {msg[:40]}")
        except GitNotFoundError as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}
        except GitError as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}

        # Screenshot — only when the preference is enabled
        try:
            prefs = context.preferences.addons[__package__.split('.')[0]].preferences
            do_screenshot = prefs.screenshot_on_commit
        except Exception:
            do_screenshot = False

        if do_screenshot:
            previews_dir = os.path.join(proj.root, 'previews')
            os.makedirs(previews_dir, exist_ok=True)
            png_path = os.path.join(previews_dir, f'{full_hash}.png')
            try:
                with context.temp_override(area=context.area):
                    bpy.ops.screen.screenshot_area(
                        filepath=png_path,
                        check_existing=False,
                    )
            except Exception as e:
                self.report({'WARNING'}, f"Commit OK but screenshot failed: {e}")

        # Auto-push if the preference is enabled and a remote is configured
        try:
            prefs = context.preferences.addons[__package__.split('.')[0]].preferences
            auto_push = prefs.auto_push_on_commit
        except Exception:
            auto_push = False

        if auto_push and scene.nodesync_remote_url.strip():
            token = _get_token(context)
            try:
                branch = repo.current_branch()
                repo.push(token=token)
                scene.nodesync_sync_status = 'Pushed OK'
                self.report({'INFO'}, f"Auto-pushed branch '{branch}' to origin")
            except GitError as e:
                scene.nodesync_sync_status = 'Auto-push failed'
                self.report({'WARNING'}, f"Commit OK but auto-push failed: {e}")

        return {'FINISHED'}


class NODESYNC_OT_refresh_history(bpy.types.Operator):
    bl_idname  = 'nodesync.refresh_history'
    bl_label   = 'Refresh'
    bl_description = 'Re-read git log and update the history list'

    @classmethod
    def poll(cls, context):
        return bool(context.scene.nodesync_project_root.strip())

    def execute(self, context):
        scene = context.scene
        root  = scene.nodesync_project_root.strip()
        # Pressing refresh always clears any active filter
        scene.nodesync_history_filter_active = False
        scene.nodesync_history_filter_label  = ''
        _refresh_branches(scene, root)
        _refresh_history(scene, root)
        self.report({'INFO'}, f"History refreshed: {len(scene.nodesync_commit_history)} commits")
        return {'FINISHED'}


class NODESYNC_OT_checkout_commit(bpy.types.Operator):
    bl_idname  = 'nodesync.checkout_commit'
    bl_label   = 'Checkout'
    bl_description = 'Check out this commit and reimport all node groups from that version'

    commit_hash : bpy.props.StringProperty()

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

        # Snapshot before anything changes so modifiers can be re-linked after
        _snapshot_modifier_links()

        from ..git_ops import GitRepo, GitNotFoundError, GitError
        try:
            repo = GitRepo(proj.root)
            # Diff worktree vs target BEFORE restoring to find groups that will
            # disappear from disk (exist on disk now but not in the target commit).
            # We do NOT use this diff to limit which groups get imported — we
            # always do a full import so that Blender state is guaranteed to match
            # the target regardless of what the user changed in-memory.
            diff = repo.diff_worktree_vs_commit(self.commit_hash)
            repo.restore_files_from(self.commit_hash, 'nodes/')
        except GitNotFoundError as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}
        except GitError as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}

        # Files that exist on disk but not in the target commit are NOT removed
        # by git checkout — delete them explicitly so import_all_from_disk only
        # sees the files that belong to the target commit.
        for rel_path in diff['added']:
            abs_path = os.path.join(proj.root, rel_path)
            try:
                if os.path.isfile(abs_path):
                    os.remove(abs_path)
            except OSError as e:
                print(f"[NodeSync] Could not remove '{rel_path}': {e}")

        # Always reconstruct every group from the restored files so that
        # in-Blender edits (deletions, manual changes) are fully overwritten.
        imported = proj.import_all_from_disk()
        _restore_modifier_links(imported)

        # Track which commit is currently loaded so the bookmark stays accurate.
        scene.nodesync_restore_hash = self.commit_hash

        _refresh_history(scene, proj.root)

        # Ask the user whether to also remove the corresponding Blender groups
        # (the JSON files are already gone from disk at this point).
        to_delete_names = [
            os.path.basename(p)[:-5] if p.endswith('.json') else os.path.basename(p)
            for p in diff['added']
        ]

        if not to_delete_names:
            self.report({'INFO'},
                        f"Restored nodes from {self.commit_hash[:8]} — "
                        f"{len(imported)} group(s) loaded. Commit to save this state.")
            return {'FINISHED'}

        _pending_pull_changes['creates'] = []
        _pending_pull_changes['deletes'] = to_delete_names
        _pending_pull_changes['project_root'] = proj.root

        bpy.ops.nodesync.confirm_pull_changes('INVOKE_DEFAULT')
        return {'FINISHED'}


class NODESYNC_OT_toggle_history_filter(bpy.types.Operator):
    bl_idname      = 'nodesync.toggle_history_filter'
    bl_label       = 'Toggle History Filter'
    bl_description = ('Show only commits that touched the currently viewed '
                      'node group, or clear the filter to show all commits')

    @classmethod
    def poll(cls, context):
        return bool(context.scene.nodesync_project_root.strip())

    def execute(self, context):
        scene = context.scene
        root  = scene.nodesync_project_root.strip()

        if scene.nodesync_history_filter_active:
            # Clear filter — show all commits
            scene.nodesync_history_filter_active = False
            scene.nodesync_history_filter_label  = ''
            _refresh_history(scene, root)
            return {'FINISHED'}

        # Activate filter for the currently viewed node tree
        sdata = context.space_data
        nt = getattr(sdata, 'node_tree', None) if sdata else None
        if not nt:
            self.report({'WARNING'}, "No active node tree in the editor")
            return {'CANCELLED'}

        filepath, display_name = _resolve_tree_rel_path(nt)
        if not filepath:
            self.report({'WARNING'}, "Active node tree is not tracked by NodeSync")
            return {'CANCELLED'}

        try:
            from ..git_ops import GitRepo
            repo   = GitRepo(root)
            hashes = repo.log_for_file(filepath)
        except Exception as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}

        scene.nodesync_history_filter_active = True
        scene.nodesync_history_filter_label  = display_name
        _refresh_history(scene, root, filter_hashes=hashes)
        count = len(scene.nodesync_commit_history)
        self.report({'INFO'}, f"Filtered to {count} commit(s) for '{display_name}'")
        return {'FINISHED'}


classes = [
    NODESYNC_OT_commit,
    NODESYNC_OT_refresh_history,
    NODESYNC_OT_checkout_commit,
    NODESYNC_OT_toggle_history_filter,
]
