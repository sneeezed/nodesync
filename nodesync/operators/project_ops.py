"""
Operators for initializing and opening NodeSync projects.
"""

import bpy
import os

from .helpers import _get_project, _refresh_branches, _refresh_history


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

        from ..project import NodeSyncProject
        from ..git_ops  import GitRepo, GitNotFoundError, GitError

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

        # Load remote URL from config into scene property
        proj2 = NodeSyncProject(root)
        saved_url = proj2.get_remote_url()
        if saved_url:
            scene.nodesync_remote_url = saved_url

        _refresh_branches(scene, root)
        _refresh_history(scene, root)
        return {'FINISHED'}


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

        from ..project import NodeSyncProject
        proj = NodeSyncProject(root)

        if not proj.config_exists():
            self.report({'ERROR'},
                        "No .nodesync config found — use 'Initialize Project' first")
            return {'CANCELLED'}

        context.scene.nodesync_project_root = root

        # Load remote URL from config
        saved_url = proj.get_remote_url()
        if saved_url:
            context.scene.nodesync_remote_url = saved_url

        _refresh_branches(context.scene, root)
        _refresh_history(context.scene, root)
        self.report({'INFO'}, f"Opened: {root}")
        return {'FINISHED'}


classes = [
    NODESYNC_OT_init_project,
    NODESYNC_OT_open_project,
]
