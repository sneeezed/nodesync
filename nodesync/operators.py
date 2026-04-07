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


def _get_token(context):
    """Return the GitHub PAT from addon preferences, or empty string."""
    try:
        prefs = context.preferences.addons[__package__].preferences
        return prefs.github_token.strip()
    except Exception:
        return ''


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
        item.full_hash   = e['full_hash']
        item.hash        = e['hash']
        item.subject     = e['subject']
        item.author      = e['author']
        item.date        = e['date']
        item.decorations = ','.join(e.get('decorations', []))


def _refresh_branches(scene, root):
    """Populate scene.nodesync_branch_list and nodesync_current_branch."""
    from .git_ops import GitRepo
    from .project import NodeSyncProject
    try:
        repo    = GitRepo(root)
        proj    = NodeSyncProject(root)
        current = repo.current_branch()
        branches = repo.list_branches()
        colors   = proj.get_branch_colors()
    except Exception:
        return

    scene.nodesync_current_branch = current
    scene.nodesync_branch_list.clear()
    for name in branches:
        item       = scene.nodesync_branch_list.add()
        item.name  = name
        saved_color = colors.get(name)
        if saved_color and len(saved_color) == 3:
            item.color = saved_color


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

        # Load remote URL from config into scene property
        from .project import NodeSyncProject
        proj2 = NodeSyncProject(root)
        saved_url = proj2.get_remote_url()
        if saved_url:
            scene.nodesync_remote_url = saved_url

        _refresh_history(scene, root)
        _refresh_branches(scene, root)
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

        # Load remote URL from config
        saved_url = proj.get_remote_url()
        if saved_url:
            context.scene.nodesync_remote_url = saved_url

        _refresh_history(context.scene, root)
        _refresh_branches(context.scene, root)
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
            _refresh_branches(scene, proj.root)
            self.report({'INFO'},
                        f"Committed {len(exported)} group(s) [{short_hash}]: {msg[:40]}")
        except GitNotFoundError as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}
        except GitError as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}

        # Auto-push if the preference is enabled and a remote is configured
        try:
            prefs = context.preferences.addons[__package__].preferences
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
        _refresh_branches(scene, root)
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
# Enter Diff Mode
# ---------------------------------------------------------------------------

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
        from .serializer import export_node_group
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

        from .diff import compute_diff, apply_diff_overlay
        diff = compute_diff(head_data, current_data)

        apply_diff_overlay(node_tree, diff)
        scene.nodesync_diff_active = True

        added    = len(diff['added'])
        modified = len(diff['modified'])
        removed  = len(diff['removed'])
        self.report({'INFO'},
                    f"Diff: {added} added, {modified} modified, {removed} deleted")
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# Diff Legend (tooltip-only, no-op)
# ---------------------------------------------------------------------------

class NODESYNC_OT_diff_legend(bpy.types.Operator):
    bl_idname  = 'nodesync.diff_legend'
    bl_label   = 'Diff Legend'
    bl_description = 'Green = added  |  Orange = modified  |  Red ghost = deleted'

    def execute(self, context):
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# Exit Diff Mode
# ---------------------------------------------------------------------------

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
        from .diff import remove_diff_overlay
        node_tree = context.space_data.node_tree
        remove_diff_overlay(node_tree)
        context.scene.nodesync_diff_active = False
        self.report({'INFO'}, "Diff overlay removed")
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# Clone from GitHub
# ---------------------------------------------------------------------------

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
            prefs = context.preferences.addons[__package__].preferences
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

        from .git_ops import GitRepo, GitNotFoundError, GitError
        from .project import NodeSyncProject

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

        _refresh_history(scene, target_dir)
        _refresh_branches(scene, target_dir)

        self.report({'INFO'},
                    f"Cloned into '{target_dir}' — imported {len(imported)} group(s)")
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# Set Remote URL
# ---------------------------------------------------------------------------

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

        from .git_ops import GitRepo, GitError
        try:
            repo = GitRepo(proj.root)
            repo.set_remote_url(url)
            proj.set_remote_url(url)
        except GitError as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}

        self.report({'INFO'}, f"Remote set to: {url}")
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# Push
# ---------------------------------------------------------------------------

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

        from .git_ops import GitRepo, GitError
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


# ---------------------------------------------------------------------------
# Pull
# ---------------------------------------------------------------------------

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

        from .git_ops import GitRepo, GitError
        try:
            repo = GitRepo(proj.root)
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

        # Clean pull — reimport node groups
        imported = proj.import_all_from_disk()
        _refresh_history(scene, proj.root)
        _refresh_branches(scene, proj.root)
        scene.nodesync_sync_status = 'Pulled OK'
        self.report({'INFO'}, f"Pulled OK — reimported {len(imported)} group(s)")
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# Create Branch
# ---------------------------------------------------------------------------

class NODESYNC_OT_create_branch(bpy.types.Operator):
    bl_idname      = 'nodesync.create_branch'
    bl_label       = 'Create Branch'
    bl_description = 'Create a new git branch with a display color'

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=300)

    def draw(self, context):
        layout = self.layout
        scene  = context.scene
        layout.prop(scene, 'nodesync_new_branch_name', text='Name')
        layout.prop(scene, 'nodesync_new_branch_color', text='Color')

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

        from .git_ops import GitRepo, GitError
        try:
            repo = GitRepo(proj.root)
            repo.create_branch(name)
        except GitError as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}

        color = list(scene.nodesync_new_branch_color)
        proj.set_branch_color(name, color)

        # Clear input
        scene.nodesync_new_branch_name = ''

        _refresh_history(scene, proj.root)
        _refresh_branches(scene, proj.root)
        self.report({'INFO'}, f"Created and switched to branch '{name}'")
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# Switch Branch
# ---------------------------------------------------------------------------

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

        from .git_ops import GitRepo, GitError
        try:
            repo = GitRepo(proj.root)
            repo.switch_branch(self.branch_name)
        except GitError as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}

        imported = proj.import_all_from_disk()
        _refresh_history(scene, proj.root)
        _refresh_branches(scene, proj.root)
        self.report({'INFO'},
                    f"Switched to '{self.branch_name}' — reimported {len(imported)} group(s)")
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# Resolve Conflict
# ---------------------------------------------------------------------------

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

        from .git_ops import GitRepo, GitError
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


# ---------------------------------------------------------------------------
# Complete Merge
# ---------------------------------------------------------------------------

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

        from .git_ops import GitRepo, GitError
        try:
            repo      = GitRepo(proj.root)
            short_hash = repo.complete_merge()
        except GitError as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}

        # Reload all node groups from the merged state
        imported = proj.import_all_from_disk()
        scene.nodesync_conflict_items.clear()
        scene.nodesync_has_conflicts  = False
        scene.nodesync_sync_status    = 'Merge complete'
        _refresh_history(scene, proj.root)
        _refresh_branches(scene, proj.root)
        self.report({'INFO'},
                    f"Merge complete [{short_hash}] — reimported {len(imported)} group(s)")
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# Abort Merge
# ---------------------------------------------------------------------------

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

        from .git_ops import GitRepo, GitError
        try:
            repo = GitRepo(proj.root)
            repo.abort_merge()
        except GitError as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}

        imported = proj.import_all_from_disk()
        scene.nodesync_conflict_items.clear()
        scene.nodesync_has_conflicts  = False
        scene.nodesync_sync_status    = 'Merge aborted'
        _refresh_history(scene, proj.root)
        _refresh_branches(scene, proj.root)
        self.report({'INFO'}, f"Merge aborted — reverted to pre-merge state ({len(imported)} groups reloaded)")
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# Registration list
# ---------------------------------------------------------------------------

classes = [
    NODESYNC_OT_clone_from_github,
    NODESYNC_OT_init_project,
    NODESYNC_OT_open_project,
    NODESYNC_OT_commit,
    NODESYNC_OT_refresh_history,
    NODESYNC_OT_checkout_commit,
    NODESYNC_OT_diff_legend,
    NODESYNC_OT_enter_diff,
    NODESYNC_OT_exit_diff,
    NODESYNC_OT_set_remote,
    NODESYNC_OT_push,
    NODESYNC_OT_pull,
    NODESYNC_OT_create_branch,
    NODESYNC_OT_switch_branch,
    NODESYNC_OT_resolve_conflict,
    NODESYNC_OT_complete_merge,
    NODESYNC_OT_abort_merge,
]
