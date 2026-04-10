"""
Operators for GitHub remote operations: clone, set remote, push, pull.
"""

import bpy
import os

from .helpers import (
    _get_project,
    _get_token,
    _refresh_branches,
    _refresh_history,
    _pending_pull_changes,
)
from .modifier_links import _snapshot_modifier_links, _restore_modifier_links


class NODESYNC_OT_clone_from_github(bpy.types.Operator):
    bl_idname      = 'nodesync.clone_from_github'
    bl_label       = 'Clone from GitHub'
    bl_description = ('Clone an existing NodeSync GitHub repository into a '
                      'local folder and open it as the active project')

    def invoke(self, context, event):
        # Pre-fill clone dir from blend file location if available
        scene = context.scene
        if not scene.nodesync_clone_dir and bpy.data.filepath:
            scene.nodesync_clone_dir = os.path.dirname(bpy.data.filepath)
        return context.window_manager.invoke_props_dialog(self, width=420)

    def draw(self, context):
        layout = self.layout
        scene  = context.scene
        layout.label(text='Repository URL:')
        layout.prop(scene, 'nodesync_clone_url', text='',
                    placeholder='https://github.com/user/repo')
        layout.separator()
        layout.label(text='Clone into folder:')
        layout.prop(scene, 'nodesync_clone_dir', text='')
        layout.separator()
        if not scene.nodesync_clone_url.strip():
            layout.label(text='Enter a GitHub URL above', icon='INFO')
        token_set = False
        try:
            prefs = context.preferences.addons[__package__.split('.')[0]].preferences
            token_set = bool(prefs.github_token.strip())
        except Exception:
            pass
        if not token_set:
            layout.label(text='No token set — only public repos will work', icon='ERROR')

    def execute(self, context):
        scene = context.scene
        url   = scene.nodesync_clone_url.strip()
        directory = scene.nodesync_clone_dir.strip().rstrip('/\\')

        if not url:
            self.report({'ERROR'}, "Enter a GitHub repository URL")
            return {'CANCELLED'}
        if not directory:
            self.report({'ERROR'}, "Choose a local folder to clone into")
            return {'CANCELLED'}
        if not os.path.isdir(directory):
            self.report({'ERROR'}, f"Folder does not exist: {directory}")
            return {'CANCELLED'}

        # Derive target subfolder name from URL (same as git clone default)
        repo_name = url.rstrip('/').split('/')[-1]
        if repo_name.endswith('.git'):
            repo_name = repo_name[:-4]
        target_dir = os.path.join(directory, repo_name)

        if os.path.exists(target_dir):
            self.report({'ERROR'},
                        f"Folder already exists: {target_dir}\n"
                        "Delete it or choose a different parent folder.")
            return {'CANCELLED'}

        token = _get_token(context)

        from ..git_ops import GitRepo, GitNotFoundError, GitError
        from ..project import NodeSyncProject

        try:
            GitRepo.clone(url, target_dir, token=token)
        except GitNotFoundError as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}
        except GitError as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}

        # Verify it has a .nodesync config
        proj = NodeSyncProject(target_dir)
        if not proj.config_exists():
            self.report({'WARNING'},
                        "Cloned successfully but no .nodesync config found. "
                        "This may not be a NodeSync project.")

        # Set project root and populate UI
        scene.nodesync_project_root = target_dir
        scene.nodesync_remote_url   = url
        scene.nodesync_clone_url    = ''   # clear for next use

        # Save remote URL into config so it persists
        proj.set_remote_url(url)

        # Import all node groups from the cloned nodes/ directory
        imported = proj.import_all_from_disk()

        _refresh_branches(scene, target_dir)
        _refresh_history(scene, target_dir)

        self.report({'INFO'},
                    f"Cloned into '{target_dir}' — imported {len(imported)} group(s)")
        return {'FINISHED'}


class NODESYNC_OT_set_remote(bpy.types.Operator):
    bl_idname      = 'nodesync.set_remote'
    bl_label       = 'Set Remote'
    bl_description = 'Save the GitHub repository URL and configure git remote'

    @classmethod
    def poll(cls, context):
        return bool(context.scene.nodesync_project_root.strip())

    def execute(self, context):
        scene = context.scene
        url   = scene.nodesync_remote_url.strip()
        if not url:
            self.report({'ERROR'}, "Enter a GitHub repository URL first")
            return {'CANCELLED'}

        proj = _get_project(scene)
        if proj is None:
            self.report({'ERROR'}, "No active NodeSync project")
            return {'CANCELLED'}

        from ..git_ops import GitRepo, GitError
        try:
            repo = GitRepo(proj.root)
            repo.set_remote_url(url)
            proj.set_remote_url(url)
        except GitError as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}

        self.report({'INFO'}, f"Remote set to: {url}")
        return {'FINISHED'}


class NODESYNC_OT_push(bpy.types.Operator):
    bl_idname      = 'nodesync.push'
    bl_label       = 'Push'
    bl_description = 'Push commits to GitHub'

    @classmethod
    def poll(cls, context):
        scene = context.scene
        return (bool(scene.nodesync_project_root.strip())
                and bool(scene.nodesync_remote_url.strip()))

    def execute(self, context):
        scene = context.scene
        proj  = _get_project(scene)
        if proj is None:
            self.report({'ERROR'}, "No active NodeSync project")
            return {'CANCELLED'}

        token = _get_token(context)

        from ..git_ops import GitRepo, GitError
        try:
            repo = GitRepo(proj.root)
            repo.push(token=token)
            scene.nodesync_sync_status = 'Pushed OK'
            branch = repo.current_branch()
            self.report({'INFO'}, f"Pushed branch '{branch}' to origin")
        except GitError as e:
            scene.nodesync_sync_status = 'Push failed'
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}

        return {'FINISHED'}


class NODESYNC_OT_confirm_pull_changes(bpy.types.Operator):
    bl_idname  = 'nodesync.confirm_pull_changes'
    bl_label   = 'Apply Pull Changes'

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=360)

    def draw(self, context):
        layout = self.layout
        data = _pending_pull_changes

        if data['creates']:
            layout.label(text="New node groups incoming from pull:", icon='ADD')
            col = layout.column(align=True)
            for name, _ in data['creates']:
                col.label(text=f"    {name}")
            layout.separator(factor=0.5)

        if data['deletes']:
            layout.label(text="Node groups removed in pull:", icon='TRASH')
            col = layout.column(align=True)
            for name in data['deletes']:
                col.label(text=f"    {name}")
            layout.separator(factor=0.5)

        layout.label(text="Click OK to apply, or Cancel to skip.")

    def execute(self, context):
        data = _pending_pull_changes
        proj_root = data['project_root']

        if data['creates'] and proj_root:
            from ..project import NodeSyncProject
            proj = NodeSyncProject(proj_root)
            paths = [p for _, p in data['creates']]
            imported = proj.import_specific_from_disk(paths)
            _restore_modifier_links(imported)
            if imported:
                self.report({'INFO'}, f"Imported: {', '.join(imported)}")

        if data['deletes']:
            # Snapshot before deletion so we can re-link if these groups return
            _snapshot_modifier_links()
            removed = []
            for name in data['deletes']:
                ng = bpy.data.node_groups.get(name)
                if ng:
                    bpy.data.node_groups.remove(ng)
                    removed.append(name)
            if removed:
                self.report({'INFO'}, f"Removed: {', '.join(removed)}")

        data['creates'].clear()
        data['deletes'].clear()
        data['project_root'] = ''
        return {'FINISHED'}

    def cancel(self, context):
        _pending_pull_changes['creates'].clear()
        _pending_pull_changes['deletes'].clear()
        _pending_pull_changes['project_root'] = ''


class NODESYNC_OT_pull(bpy.types.Operator):
    bl_idname      = 'nodesync.pull'
    bl_label       = 'Pull'
    bl_description = 'Pull latest commits from GitHub'

    @classmethod
    def poll(cls, context):
        scene = context.scene
        return (bool(scene.nodesync_project_root.strip())
                and bool(scene.nodesync_remote_url.strip())
                and not scene.nodesync_has_conflicts)

    def execute(self, context):
        scene = context.scene
        proj  = _get_project(scene)
        if proj is None:
            self.report({'ERROR'}, "No active NodeSync project")
            return {'CANCELLED'}

        token = _get_token(context)

        # Snapshot before anything changes so we can re-link modifiers later
        _snapshot_modifier_links()

        from ..git_ops import GitRepo, GitError
        try:
            repo = GitRepo(proj.root)
            pre_hash = repo.current_commit_hash(short=False)
            has_conflicts, conflicted_files = repo.pull(token=token)
        except GitError as e:
            scene.nodesync_sync_status = 'Pull failed'
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}

        if has_conflicts:
            # Populate conflict list
            scene.nodesync_conflict_items.clear()
            for filepath in conflicted_files:
                item            = scene.nodesync_conflict_items.add()
                item.filepath   = filepath
                # Derive display name from filename
                basename        = os.path.basename(filepath)
                item.group_name = basename[:-5] if basename.endswith('.json') else basename
                item.resolved   = False
            scene.nodesync_has_conflicts  = True
            scene.nodesync_sync_status    = f'{len(conflicted_files)} conflict(s) — resolve in Conflicts panel'
            self.report({'WARNING'},
                        f"Pull produced {len(conflicted_files)} conflict(s). "
                        "Use the Conflicts panel to resolve them.")
            return {'FINISHED'}

        # Clean pull — selectively reimport only what changed
        if not pre_hash:
            # No prior commit (shouldn't happen, but fall back to full import)
            imported = proj.import_all_from_disk()
            _refresh_branches(scene, proj.root)
            _refresh_history(scene, proj.root)
            scene.nodesync_sync_status = 'Pulled OK'
            self.report({'INFO'}, f"Pulled OK — {len(imported)} group(s) imported")
            return {'FINISHED'}

        diff = repo.diff_since(pre_hash)
        modified = diff['modified']
        added    = diff['added']
        deleted  = diff['deleted']

        # Reconstruct groups whose files were modified
        reimported = proj.import_specific_from_disk(modified) if modified else []
        _restore_modifier_links(reimported)

        _refresh_branches(scene, proj.root)
        _refresh_history(scene, proj.root)

        # If nothing needs confirmation just report and finish
        if not added and not deleted:
            count = len(reimported)
            scene.nodesync_sync_status = 'Pulled OK'
            self.report({'INFO'},
                        f"Pulled OK — {count} group(s) updated" if count
                        else "Pulled OK — already up to date")
            return {'FINISHED'}

        # Populate the confirmation dialog and invoke it
        _pending_pull_changes['creates'] = proj.load_group_data_from_disk(added)
        _pending_pull_changes['deletes'] = [
            os.path.basename(p)[:-5] if p.endswith('.json') else os.path.basename(p)
            for p in deleted
        ]
        _pending_pull_changes['project_root'] = proj.root

        scene.nodesync_sync_status = 'Pulled OK — review changes below'
        bpy.ops.nodesync.confirm_pull_changes('INVOKE_DEFAULT')
        return {'FINISHED'}


classes = [
    NODESYNC_OT_clone_from_github,
    NODESYNC_OT_set_remote,
    NODESYNC_OT_push,
    NODESYNC_OT_confirm_pull_changes,
    NODESYNC_OT_pull,
]
