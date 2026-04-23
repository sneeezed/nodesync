"""
Operators for committing, restoring, and filtering commit history.
"""

import bpy
import os
import threading

from .helpers import (
    _get_project,
    _get_token,
    _refresh_branches,
    _refresh_history,
    _pending_pull_changes,
    _resolve_tree_rel_path,
    _branch_color_for_name,
)
from .modifier_links import _snapshot_modifier_links, _restore_modifier_links


class NODESYNC_OT_commit(bpy.types.Operator):
    bl_idname  = 'nodesync.commit'
    bl_label   = 'Commit'
    bl_description = 'Export tracked node groups to JSON and create a Git commit'

    _timer  = None
    _thread = None
    _result = None

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

        # Export all tracked node groups — must be on main thread (reads bpy data)
        exported = proj.export_all_groups()
        if not exported:
            self.report({'WARNING'}, "No tracked node groups found in file")
            return {'CANCELLED'}

        # Read preferences on main thread before spawning the worker thread
        try:
            prefs = context.preferences.addons[__package__.split('.')[0]].preferences
            track_textures = prefs.track_textures
            do_screenshot  = prefs.screenshot_on_commit
            auto_push      = prefs.auto_push_on_commit
        except Exception:
            track_textures = False
            do_screenshot  = False
            auto_push      = False

        # Collect textures on main thread — uses bpy.data and image.save_render
        textures_written = 0
        texture_warning  = ''
        if track_textures:
            try:
                textures_written = len(proj.collect_shader_textures())
            except Exception as e:
                texture_warning = str(e)

        token      = _get_token(context) if auto_push else ''
        remote_url = scene.nodesync_remote_url.strip()
        proj_root  = proj.root
        n_exported = len(exported)

        self._result          = None
        self._proj            = proj
        self._do_screenshot   = do_screenshot
        self._texture_warning = texture_warning

        def _git_work():
            result = {}
            try:
                from ..git_ops import GitRepo, GitNotFoundError, GitError
                try:
                    repo = GitRepo(proj_root)

                    repo.add('nodes/')
                    if track_textures and textures_written:
                        repo.add('textures/')
                    repo.add(os.path.join(proj_root, '.nodesync'))

                    short_hash = repo.commit(msg)
                    full_hash  = repo.current_commit_hash(short=False)

                    result['short_hash']     = short_hash
                    result['full_hash']      = full_hash
                    result['exported_count'] = n_exported
                    result['msg']            = msg

                    # Fetch history and branch data while still in the thread
                    try:
                        entries        = repo.log(300)
                        head_full      = repo.current_commit_hash(short=False)
                        current_branch = repo.current_branch()
                        branches       = repo.list_branches()
                        result['history_entries'] = entries
                        result['history_head']    = head_full
                        result['current_branch']  = current_branch
                        result['branches']        = branches
                    except Exception:
                        pass  # modal will fall back to synchronous refresh

                    if auto_push and remote_url:
                        try:
                            branch = repo.current_branch()
                            repo.push(token=token)
                            result['pushed']      = True
                            result['push_branch'] = branch
                        except GitError as e:
                            result['push_error'] = str(e)

                except GitNotFoundError as e:
                    result['error'] = str(e)
                except GitError as e:
                    result['error'] = str(e)
            except Exception as e:
                result['error'] = f"Unexpected error: {e}"
            finally:
                self._result = result

        self._thread = threading.Thread(target=_git_work, daemon=True)
        self._thread.start()

        wm = context.window_manager
        self._timer = wm.event_timer_add(0.05, window=context.window)
        wm.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        if event.type != 'TIMER':
            return {'PASS_THROUGH'}

        if self._thread.is_alive():
            return {'PASS_THROUGH'}

        context.window_manager.event_timer_remove(self._timer)
        self._timer = None

        result = self._result
        scene  = context.scene

        if result is None or result.get('error'):
            self.report({'ERROR'}, (result or {}).get('error', 'Unknown git error'))
            return {'CANCELLED'}

        if self._texture_warning:
            self.report({'WARNING'}, f"Texture collection failed: {self._texture_warning}")

        scene.nodesync_commit_message = ''
        scene.nodesync_restore_hash   = ''

        # Apply pre-fetched history/branch data (no subprocess calls here)
        if 'history_entries' in result:
            self._apply_history(scene, result)
            self._apply_branches(scene, result)
        else:
            _refresh_branches(scene, self._proj.root)
            _refresh_history(scene, self._proj.root)

        msg_preview = result['msg'][:40]
        self.report({'INFO'},
                    f"Committed {result['exported_count']} group(s) "
                    f"[{result['short_hash']}]: {msg_preview}")

        if result.get('pushed'):
            scene.nodesync_sync_status = 'Pushed OK'
            self.report({'INFO'}, f"Auto-pushed branch '{result['push_branch']}' to origin")
        elif result.get('push_error'):
            scene.nodesync_sync_status = 'Auto-push failed'
            self.report({'WARNING'}, f"Commit OK but auto-push failed: {result['push_error']}")

        if self._do_screenshot:
            previews_dir = os.path.join(self._proj.root, 'previews')
            os.makedirs(previews_dir, exist_ok=True)
            png_path = os.path.join(previews_dir, f"{result['full_hash']}.png")
            try:
                with context.temp_override(area=context.area):
                    bpy.ops.screen.screenshot_area(
                        filepath=png_path,
                        check_existing=False,
                    )
            except Exception as e:
                self.report({'WARNING'}, f"Commit OK but screenshot failed: {e}")

        return {'FINISHED'}

    def cancel(self, context):
        if self._timer:
            context.window_manager.event_timer_remove(self._timer)
            self._timer = None

    def _apply_history(self, scene, result):
        entries        = result.get('history_entries', [])
        head_full      = result.get('history_head', '')
        current_branch = result.get('current_branch', '')

        scene.nodesync_head_hash = head_full
        active_branch = current_branch

        scene.nodesync_commit_history.clear()
        for e in entries:
            decs       = e.get('decorations', [])
            local_decs = [d for d in decs if not d.startswith('origin/')]
            if local_decs:
                active_branch = local_decs[0]

            item             = scene.nodesync_commit_history.add()
            item.full_hash   = e['full_hash']
            item.hash        = e['hash']
            item.subject     = e['subject']
            item.author      = e['author']
            item.date        = e['date']
            item.decorations = ','.join(decs)
            idx, color       = _branch_color_for_name(active_branch)
            item.branch_name = active_branch
            item.color_index = idx
            item.branch_color = color

    def _apply_branches(self, scene, result):
        current  = result.get('current_branch', '')
        branches = result.get('branches', [])

        scene.nodesync_current_branch = current
        scene.nodesync_branch_list.clear()
        for name in branches:
            item             = scene.nodesync_branch_list.add()
            item.name        = name
            idx, color       = _branch_color_for_name(name)
            item.color       = color
            item.color_index = idx


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

        _snapshot_modifier_links()

        from ..git_ops import GitRepo, GitNotFoundError, GitError
        try:
            repo = GitRepo(proj.root)
            diff = repo.diff_worktree_vs_commit(self.commit_hash)
            repo.restore_files_from(self.commit_hash, 'nodes/')
        except GitNotFoundError as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}
        except GitError as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}

        for rel_path in diff['added']:
            abs_path = os.path.join(proj.root, rel_path)
            try:
                if os.path.isfile(abs_path):
                    os.remove(abs_path)
            except OSError as e:
                print(f"[NodeSync] Could not remove '{rel_path}': {e}")

        imported = proj.import_all_from_disk()
        _restore_modifier_links(imported)

        scene.nodesync_restore_hash = self.commit_hash

        _refresh_history(scene, proj.root)

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
            scene.nodesync_history_filter_active = False
            scene.nodesync_history_filter_label  = ''
            _refresh_history(scene, root)
            return {'FINISHED'}

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
