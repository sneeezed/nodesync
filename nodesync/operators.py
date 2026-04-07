"""
All bpy.types.Operator subclasses for NodeSync.
"""

import bpy
import os
import json


# ---------------------------------------------------------------------------
# Helpers shared by multiple operators
# ---------------------------------------------------------------------------

def _get_project(scene):
    """Return a NodeSyncProject for the active project root, or None."""
    from .project import NodeSyncProject
    root = scene.nodesync_project_root.strip()
    if not root or not os.path.isdir(root):
        return None
    return NodeSyncProject(root)


def _get_repo(root):
    """Return a GitRepo, raising GitNotFoundError / GitError on failure."""
    from .git_ops import GitRepo
    return GitRepo(root)


def _refresh_history(scene, root):
    """Populate scene.nodesync_commit_history from git log."""
    try:
        from .git_ops import GitRepo
        repo = GitRepo(root)
        entries = repo.log(30)
    except Exception:
        entries = []

    scene.nodesync_commit_history.clear()
    for e in entries:
        item = scene.nodesync_commit_history.add()
        item.full_hash = e['full_hash']
        item.hash      = e['hash']
        item.subject   = e['subject']
        item.author    = e['author']
        item.date      = e['date']


# ---------------------------------------------------------------------------
# Init Project
# ---------------------------------------------------------------------------

class NODESYNC_OT_init_project(bpy.types.Operator):
    bl_idname  = 'nodesync.init_project'
    bl_label   = 'Initialize Project'
    bl_description = ('Create the NodeSync folder structure and run git init '
                      'in the selected project root')

    def execute(self, context):
        scene = context.scene
        root  = scene.nodesync_project_root.strip()

        # Fall back to blend file directory if no root set
        if not root:
            blend = bpy.data.filepath
            if not blend:
                self.report({'ERROR'},
                            "Set a Project Root folder, or save the .blend file first")
                return {'CANCELLED'}
            root = os.path.dirname(blend)
            scene.nodesync_project_root = root

        root = os.path.normpath(root)
        if not os.path.isdir(root):
            try:
                os.makedirs(root, exist_ok=True)
            except Exception as e:
                self.report({'ERROR'}, f"Cannot create folder: {e}")
                return {'CANCELLED'}

        from .project import NodeSyncProject
        from .git_ops  import GitRepo, GitNotFoundError, GitError

        proj = NodeSyncProject(root)
        proj.ensure_nodes_dir()

        if not proj.config_exists():
            proj.save_config({'version': '1.0', 'tracked_groups': []})

        try:
            repo = GitRepo(root)
            if not repo.is_repo():
                repo.init()
                self.report({'INFO'}, f"Initialized git repo in {root}")
            else:
                self.report({'INFO'}, f"Git repo already exists in {root}")
        except GitNotFoundError as e:
            self.report({'WARNING'}, str(e))
        except GitError as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}

        _refresh_history(scene, root)
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# Open Project (directory picker)
# ---------------------------------------------------------------------------

class NODESYNC_OT_open_project(bpy.types.Operator):
    bl_idname  = 'nodesync.open_project'
    bl_label   = 'Open Project'
    bl_description = 'Open an existing NodeSync project folder'

    directory      : bpy.props.StringProperty(subtype='DIR_PATH')
    filter_folder  : bpy.props.BoolProperty(default=True, options={'HIDDEN'})

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        root = self.directory.rstrip('/\\').strip()
        if not os.path.isdir(root):
            self.report({'ERROR'}, f"Not a directory: {root}")
            return {'CANCELLED'}

        from .project import NodeSyncProject
        proj = NodeSyncProject(root)

        if not proj.config_exists():
            self.report({'ERROR'},
                        "No .nodesync config found — use 'Initialize Project' first")
            return {'CANCELLED'}

        context.scene.nodesync_project_root = root
        _refresh_history(context.scene, root)
        self.report({'INFO'}, f"Opened: {root}")
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# Commit
# ---------------------------------------------------------------------------

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

        # Export all geometry node groups
        exported = proj.export_all_groups()
        if not exported:
            self.report({'WARNING'}, "No Geometry Node groups found in file")
            return {'CANCELLED'}

        from .git_ops import GitRepo, GitNotFoundError, GitError
        try:
            repo = GitRepo(proj.root)
            repo.add('nodes/')
            # Also commit .nodesync config
            repo.add(os.path.join(proj.root, '.nodesync'))
            short_hash = repo.commit(msg)
            scene.nodesync_commit_message = ''
            _refresh_history(scene, proj.root)
            self.report({'INFO'},
                        f"Committed {len(exported)} group(s) [{short_hash}]: {msg[:40]}")
        except GitNotFoundError as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}
        except GitError as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}

        return {'FINISHED'}


# ---------------------------------------------------------------------------
# Refresh History
# ---------------------------------------------------------------------------

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
        _refresh_history(scene, root)
        self.report({'INFO'}, f"History refreshed: {len(scene.nodesync_commit_history)} commits")
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# Checkout commit
# ---------------------------------------------------------------------------

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

        from .git_ops import GitRepo, GitNotFoundError, GitError
        try:
            repo = GitRepo(proj.root)
            # Restore only the nodes/ files from the target commit without
            # moving HEAD. This keeps the repo on the current branch so that
            # all newer commits remain visible in the history.
            repo.restore_files_from(self.commit_hash, 'nodes/')
        except GitNotFoundError as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}
        except GitError as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}

        # Reimport all JSON files from the restored version
        imported = proj.import_all_from_disk()
        _refresh_history(scene, proj.root)
        self.report({'INFO'},
                    f"Restored nodes from {self.commit_hash[:8]} — "
                    f"reimported {len(imported)} group(s). "
                    f"Commit to save this state.")
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# Registration list
# ---------------------------------------------------------------------------

classes = [
    NODESYNC_OT_init_project,
    NODESYNC_OT_open_project,
    NODESYNC_OT_commit,
    NODESYNC_OT_refresh_history,
    NODESYNC_OT_checkout_commit,
]
