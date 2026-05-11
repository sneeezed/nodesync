"""
Operators for Git remote operations: clone, set remote, push, pull.
"""

import bpy
import os

from .helpers import (
    _get_project,
    _get_credentials,
    _get_addon_prefs,
    _refresh_branches,
    _refresh_history,
    _pending_pull_changes,
    _remove_node_data,
    _schedule_sync_status_clear,
)


class NODESYNC_OT_clone_from_url(bpy.types.Operator):
    bl_idname      = 'nodesync.clone_from_url'
    bl_label       = 'Clone from Git Remote'
    bl_description = ('Clone an existing NodeSync repository from a Git '
                      'remote URL into a local folder and open it as the '
                      'active project')

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
                    placeholder='https://example.com/user/repo.git')
        layout.separator()
        layout.label(text='Clone into folder:')
        layout.prop(scene, 'nodesync_clone_dir', text='')
        layout.separator()
        if not scene.nodesync_clone_url.strip():
            layout.label(text='Enter a Git repository URL above', icon='INFO')
        prefs = _get_addon_prefs(context)
        token_set = bool(prefs and getattr(prefs, 'remote_token', '').strip())
        if not token_set:
            layout.label(text='No token set — only public repos and SSH URLs will work',
                         icon='INFO')

    def execute(self, context):
        scene = context.scene
        url   = scene.nodesync_clone_url.strip()
        directory = scene.nodesync_clone_dir.strip().rstrip('/\\')

        if not url:
            self.report({'ERROR'}, "Enter a Git repository URL")
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

        username, token = _get_credentials(context)

        from ..git_ops import GitRepo, GitNotFoundError, GitError
        from ..project import NodeSyncProject

        try:
            GitRepo.clone(url, target_dir, token=token, username=username)
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
        proj.apply_scene_assignments()

        _refresh_branches(scene, target_dir)
        _refresh_history(scene, target_dir)

        self.report({'INFO'},
                    f"Cloned into '{target_dir}' — imported {len(imported)} group(s)")
        return {'FINISHED'}


class NODESYNC_OT_set_remote(bpy.types.Operator):
    bl_idname      = 'nodesync.set_remote'
    bl_label       = 'Set Remote'
    bl_description = 'Save the Git remote URL and configure the origin remote'

    @classmethod
    def poll(cls, context):
        return bool(context.scene.nodesync_project_root.strip())

    def execute(self, context):
        scene = context.scene
        url   = scene.nodesync_remote_url.strip()
        if not url:
            self.report({'ERROR'}, "Enter a Git repository URL first")
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
    bl_description = 'Push commits to the configured Git remote'

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

        username, token = _get_credentials(context)

        from ..git_ops import GitRepo, GitError
        try:
            repo = GitRepo(proj.root)
            repo.push(token=token, username=username)
            scene.nodesync_sync_status = 'Pushed OK'
            _schedule_sync_status_clear(scene, 'Pushed OK')
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
            for rel_path in data['deletes']:
                display = os.path.basename(rel_path)
                if display.endswith('.json'):
                    display = display[:-5]
                col.label(text=f"    {display}")
            layout.separator(factor=0.5)

        layout.label(text="Click OK to apply, or Cancel to skip.")

    def execute(self, context):
        data = _pending_pull_changes
        proj_root = data['project_root']

        proj = None
        if proj_root:
            from ..project import NodeSyncProject
            proj = NodeSyncProject(proj_root)

        if data['creates'] and proj is not None:
            paths = [p for _, p in data['creates']]
            imported = proj.import_specific_from_disk(paths, report=self.report)
            if imported:
                self.report({'INFO'}, f"Imported: {', '.join(imported)}")

        if data['deletes']:
            removed = []
            for rel_path in data['deletes']:
                name = _remove_node_data(rel_path)
                if name:
                    removed.append(name)
            if removed:
                self.report({'INFO'}, f"Removed: {', '.join(removed)}")

        if proj is not None:
            proj.apply_scene_assignments()

        data['creates'].clear()
        data['deletes'].clear()
        data['project_root'] = ''
        return {'FINISHED'}

    def cancel(self, context):
        _pending_pull_changes['creates'].clear()
        _pending_pull_changes['deletes'].clear()
        _pending_pull_changes['project_root'] = ''


def _tree_type_for_path(rel_path: str) -> str:
    """Human-readable label for the candidate's tree kind."""
    if rel_path.startswith('nodes/shader/materials/'):
        return 'Material'
    if rel_path.startswith('nodes/shader/worlds/'):
        return 'World'
    if rel_path.startswith('nodes/shader/lights/'):
        return 'Light'
    if rel_path.startswith('nodes/shader/'):
        return 'Shader'
    return 'Geometry'


def _group_name_for_path(rel_path: str) -> str:
    """Strip directory and .json extension to get the group/owner name."""
    base = os.path.basename(rel_path)
    return base[:-5] if base.endswith('.json') else base


class NODESYNC_OT_pull(bpy.types.Operator):
    bl_idname      = 'nodesync.pull'
    bl_label       = 'Pull'
    bl_description = ('Fetch from the configured Git remote, then choose '
                      'which node groups to apply from the incoming changes')

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

        username, token = _get_credentials(context)

        from ..git_ops import GitRepo, GitError
        try:
            repo   = GitRepo(proj.root)
            branch = repo.current_branch()
            repo.fetch_only(token=token, username=username)
            diff = repo.diff_local_vs_remote(branch)
        except GitError as e:
            scene.nodesync_sync_status = 'Fetch failed'
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}

        # _scene_assignments.json is bookkeeping, not a node group — never
        # show it in the candidate dialog or feed it into import_specific_from_disk.
        def _is_group_path(p):
            return os.path.basename(p) != '_scene_assignments.json'

        modified = [p for p in diff['modified'] if _is_group_path(p)]
        added    = [p for p in diff['added']    if _is_group_path(p)]
        deleted  = [p for p in diff['deleted']  if _is_group_path(p)]

        if not (modified or added or deleted):
            scene.nodesync_sync_status = 'Already up to date'
            self.report({'INFO'}, "Already up to date — nothing to pull")
            return {'FINISHED'}

        # Populate the candidate list for the selection dialog
        scene.nodesync_pull_candidates.clear()
        for rel_path in modified:
            item            = scene.nodesync_pull_candidates.add()
            item.rel_path   = rel_path
            item.group_name = _group_name_for_path(rel_path)
            item.tree_type  = _tree_type_for_path(rel_path)
            item.status     = 'modified'
            item.selected   = True
        for rel_path in added:
            item            = scene.nodesync_pull_candidates.add()
            item.rel_path   = rel_path
            item.group_name = _group_name_for_path(rel_path)
            item.tree_type  = _tree_type_for_path(rel_path)
            item.status     = 'added'
            item.selected   = True
        for rel_path in deleted:
            item            = scene.nodesync_pull_candidates.add()
            item.rel_path   = rel_path
            item.group_name = _group_name_for_path(rel_path)
            item.tree_type  = _tree_type_for_path(rel_path)
            item.status     = 'deleted'
            item.selected   = True

        scene.nodesync_sync_status = (
            f'Fetched — {len(modified) + len(added) + len(deleted)} '
            f'group(s) changed on remote'
        )
        bpy.ops.nodesync.select_pull_groups('INVOKE_DEFAULT')
        return {'FINISHED'}


class NODESYNC_OT_select_pull_groups(bpy.types.Operator):
    bl_idname      = 'nodesync.select_pull_groups'
    bl_label       = 'Select Groups to Pull'
    bl_description = ('Choose which incoming node group changes to apply to '
                      'your project')

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=460)

    def draw(self, context):
        layout = self.layout
        scene  = context.scene

        layout.label(text='Incoming changes from origin:', icon='IMPORT')
        layout.separator()

        # Quick toggle row
        row = layout.row(align=True)
        row.operator('nodesync.pull_select_all', text='Select All', icon='CHECKBOX_HLT')
        row.operator('nodesync.pull_select_none', text='Select None', icon='CHECKBOX_DEHLT')

        layout.separator()

        if not scene.nodesync_pull_candidates:
            layout.label(text='No candidates', icon='INFO')
            return

        # Per-group checkbox rows
        col = layout.column(align=True)
        for item in scene.nodesync_pull_candidates:
            row = col.row(align=True)
            row.prop(item, 'selected', text='')
            status_icon = {
                'modified': 'FILE_REFRESH',
                'added':    'ADD',
                'deleted':  'TRASH',
            }.get(item.status, 'QUESTION')
            row.label(text=item.group_name, icon=status_icon)
            sub = row.row()
            sub.alignment = 'RIGHT'
            sub.label(text=f"[{item.tree_type}]  {item.status}")

        layout.separator()
        layout.label(text='Unselected groups will keep their local version.',
                     icon='INFO')

    def execute(self, context):
        scene = context.scene
        proj  = _get_project(scene)
        if proj is None:
            scene.nodesync_pull_candidates.clear()
            self.report({'ERROR'}, "No active NodeSync project")
            return {'CANCELLED'}

        candidates = list(scene.nodesync_pull_candidates)
        selected   = [c for c in candidates if c.selected]
        unselected = [c for c in candidates if not c.selected]

        if not selected:
            scene.nodesync_pull_candidates.clear()
            scene.nodesync_sync_status = 'Pull cancelled — nothing selected'
            self.report({'INFO'}, "Nothing selected — pull cancelled")
            return {'CANCELLED'}

        from ..git_ops import GitRepo, GitError
        try:
            repo   = GitRepo(proj.root)
            branch = repo.current_branch()
            sel_paths   = [c.rel_path for c in selected]
            unsel_paths = [c.rel_path for c in unselected]

            sel_names = ', '.join(c.group_name for c in selected)
            message = (f"NodeSync selective pull: {sel_names}"
                       if len(sel_names) < 200
                       else f"NodeSync selective pull: {len(selected)} group(s)")

            has_conflicts, conflicted = repo.selective_pull(
                branch, sel_paths, unsel_paths, message,
            )
        except GitError as e:
            scene.nodesync_pull_candidates.clear()
            scene.nodesync_sync_status = 'Pull failed'
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}

        if has_conflicts:
            scene.nodesync_conflict_items.clear()
            for filepath in conflicted:
                item            = scene.nodesync_conflict_items.add()
                item.filepath   = filepath
                basename        = os.path.basename(filepath)
                item.group_name = basename[:-5] if basename.endswith('.json') else basename
                item.resolved   = False
            scene.nodesync_has_conflicts = True
            scene.nodesync_sync_status   = f'{len(conflicted)} conflict(s) — resolve in Conflicts panel'
            scene.nodesync_pull_candidates.clear()
            self.report({'WARNING'},
                        f"Pull produced {len(conflicted)} conflict(s). "
                        "Use the Conflicts panel to resolve them.")
            return {'FINISHED'}

        # Apply selected changes to Blender state
        modified_paths = [c.rel_path for c in selected if c.status == 'modified']
        added_paths    = [c.rel_path for c in selected if c.status == 'added']

        reimported = []
        if modified_paths:
            reimported += proj.import_specific_from_disk(modified_paths, report=self.report)
        if added_paths:
            reimported += proj.import_specific_from_disk(added_paths, report=self.report)

        # Remove Blender data-blocks whose files were dropped in this pull
        deleted_candidates = [c for c in selected if c.status == 'deleted']
        removed = []
        for c in deleted_candidates:
            name = _remove_node_data(c.rel_path)
            if name:
                removed.append(name)

        proj.apply_scene_assignments()

        # After a successful pull the user is by definition at the new HEAD,
        # not at a previously-checked-out commit, so clear the restore hash
        # so the history bookmark advances with HEAD instead of staying on
        # the old commit.
        scene.nodesync_restore_hash = ''

        _refresh_branches(scene, proj.root)
        _refresh_history(scene, proj.root)
        scene.nodesync_pull_candidates.clear()

        applied  = len(reimported) + len(removed)
        skipped  = len(unselected)
        status   = f'Pulled {applied} group(s)'
        if skipped:
            status += f' — {skipped} skipped'
        scene.nodesync_sync_status = status
        self.report({'INFO'}, status)
        return {'FINISHED'}

    def cancel(self, context):
        context.scene.nodesync_pull_candidates.clear()
        context.scene.nodesync_sync_status = 'Pull cancelled'


class NODESYNC_OT_pull_select_all(bpy.types.Operator):
    bl_idname  = 'nodesync.pull_select_all'
    bl_label   = 'Select All'
    bl_options = {'INTERNAL'}

    def execute(self, context):
        for item in context.scene.nodesync_pull_candidates:
            item.selected = True
        return {'FINISHED'}


class NODESYNC_OT_pull_select_none(bpy.types.Operator):
    bl_idname  = 'nodesync.pull_select_none'
    bl_label   = 'Select None'
    bl_options = {'INTERNAL'}

    def execute(self, context):
        for item in context.scene.nodesync_pull_candidates:
            item.selected = False
        return {'FINISHED'}


classes = [
    NODESYNC_OT_clone_from_url,
    NODESYNC_OT_set_remote,
    NODESYNC_OT_push,
    NODESYNC_OT_confirm_pull_changes,
    NODESYNC_OT_pull,
    NODESYNC_OT_select_pull_groups,
    NODESYNC_OT_pull_select_all,
    NODESYNC_OT_pull_select_none,
]
