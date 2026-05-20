"""
Operators for committing, restoring, and filtering commit history.
"""

import bpy
import os
import shutil
import subprocess
import time

from .helpers import (
    _get_project,
    _get_credentials,
    _get_addon_prefs,
    _refresh_branches,
    _refresh_history,
    _pending_pull_changes,
    _resolve_tree_rel_path,
    _branch_color_for_name,
    _compute_branch_ownership,
    _remove_node_data,
    _schedule_sync_status_clear,
)
from ..git_ops.remote import _inject_token


class NODESYNC_OT_commit(bpy.types.Operator):
    bl_idname  = 'nodesync.commit'
    bl_label   = 'Commit'
    bl_description = 'Export tracked node groups to JSON and create a Git commit'

    # Modal state machine
    _timer      = None
    _proc       = None
    _proc_step  = None
    _proc_start = 0.0
    _steps      = None    # list of {'label', 'args', 'timeout', 'on_done'}
    _step_idx   = 0
    _result     = None
    _error      = None

    # Carried from execute() into modal()
    _git_exe         = ''
    _proj            = None
    _proj_root       = ''
    _do_screenshot   = False
    _texture_warning = ''
    _auto_push       = False
    _auto_push_url   = ''

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

        # Main-thread-only: export node groups to JSON before staging.
        exported = proj.export_all_groups()
        if not exported:
            self.report({'WARNING'}, "No tracked node groups found in file")
            return {'CANCELLED'}

        prefs = _get_addon_prefs(context)
        if prefs is not None:
            track_textures = bool(getattr(prefs, 'track_textures', False))
            do_screenshot  = bool(getattr(prefs, 'screenshot_on_commit', False))
            auto_push      = bool(getattr(prefs, 'auto_push_on_commit', False))
        else:
            track_textures = False
            do_screenshot  = False
            auto_push      = False

        # Texture collection touches bpy.data / image.save_render — main thread only.
        textures_written = 0
        texture_warning  = ''
        if track_textures:
            try:
                textures_written = len(proj.collect_shader_textures())
            except Exception as e:
                texture_warning = str(e)

        if auto_push:
            username, token = _get_credentials(context)
        else:
            username, token = '', ''
        remote_url_pref = scene.nodesync_remote_url.strip()
        proj_root  = proj.root
        n_exported = len(exported)

        git_exe = shutil.which('git')
        if git_exe is None:
            self.report({'ERROR'},
                        "Git executable not found in PATH. "
                        "Install Git and make sure it is on your system PATH.")
            return {'CANCELLED'}

        # Resolve the origin URL synchronously — it's a local git-config read
        # with no network I/O, so it's effectively instant.  Only the slow
        # steps below need to be driven asynchronously.
        push_url = ''
        if auto_push and remote_url_pref:
            try:
                r = subprocess.run(
                    [git_exe, 'remote', 'get-url', 'origin'],
                    cwd=proj_root, capture_output=True, text=True, timeout=10,
                )
                origin = r.stdout.strip() if r.returncode == 0 else ''
            except Exception:
                origin = ''
            if origin:
                push_url = _inject_token(origin, token, username)

        self._proj            = proj
        self._proj_root       = proj_root
        self._git_exe         = git_exe
        self._do_screenshot   = do_screenshot
        self._texture_warning = texture_warning
        self._auto_push       = bool(push_url)
        self._auto_push_url   = push_url

        self._steps      = []
        self._step_idx   = 0
        self._proc       = None
        self._proc_step  = None
        self._proc_start = 0.0
        self._error      = None
        self._result     = {
            'short_hash':      '',
            'full_hash':       '',
            'msg':             msg,
            'exported_count':  n_exported,
            'history_entries': None,
            'history_head':    '',
            'current_branch':  '',
            'branches':        [],
            'branch_reach':    {},
            'pushed':          False,
            'push_branch':     '',
            'push_error':      '',
        }

        # Stage 1 — staging + commit
        self._steps.append({
            'label':   'add nodes/',
            'args':    ['add', 'nodes/'],
            'timeout': 30,
            'on_done': self._on_step_fail_if_rc,
        })
        if track_textures and textures_written:
            self._steps.append({
                'label':   'add textures/',
                'args':    ['add', 'textures/'],
                'timeout': 30,
                'on_done': self._on_step_fail_if_rc,
            })
        self._steps.append({
            'label':   'add .nodesync',
            'args':    ['add', os.path.join(proj_root, '.nodesync')],
            'timeout': 30,
            'on_done': self._on_step_fail_if_rc,
        })
        self._steps.append({
            'label':   'commit',
            'args':    ['commit', '-m', msg],
            'timeout': 30,
            'on_done': self._on_step_fail_if_rc,
        })

        # Stage 2 — post-commit metadata fetch (used to refresh the UI)
        self._steps.append({
            'label':   'rev-parse HEAD',
            'args':    ['rev-parse', 'HEAD'],
            'timeout': 10,
            'on_done': self._on_rev_parse_head_done,
        })
        self._steps.append({
            'label':   'log',
            'args':    ['log', '-300',
                        '--pretty=format:%H\x1f%s\x1f%an\x1f%ai\x1f%D'],
            'timeout': 30,
            'on_done': self._on_log_done,
        })
        self._steps.append({
            'label':   'rev-parse --abbrev-ref HEAD',
            'args':    ['rev-parse', '--abbrev-ref', 'HEAD'],
            'timeout': 10,
            'on_done': self._on_abbrev_ref_done,
        })
        # Branch listing dynamically appends one rev-list step per branch, and
        # the push step (if auto-push is enabled).
        self._steps.append({
            'label':   'branch',
            'args':    ['branch'],
            'timeout': 10,
            'on_done': self._on_branch_list_done,
        })

        wm = context.window_manager
        self._timer = wm.event_timer_add(0.05, window=context.window)
        wm.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    # ----- Step result callbacks ------------------------------------------------

    def _on_step_fail_if_rc(self, rc, out, err):
        if rc != 0:
            self._error = (err.strip() or out.strip()
                           or f"git exited with code {rc}")

    def _on_rev_parse_head_done(self, rc, out, err):
        if rc != 0 or not out.strip():
            self._error = err.strip() or out.strip() or "rev-parse HEAD failed"
            return
        full = out.strip()
        self._result['full_hash']    = full
        self._result['short_hash']   = full[:8]
        self._result['history_head'] = full

    def _on_log_done(self, rc, out, err):
        # Log failure is non-fatal — fall back to a sync refresh on finalize.
        if rc != 0:
            return
        entries = []
        text = out.strip()
        if text:
            for line in text.split('\n'):
                parts = line.split('\x1f')
                if len(parts) < 4:
                    continue
                raw_dec = parts[4].strip() if len(parts) >= 5 else ''
                decorations = []
                if raw_dec:
                    for d in raw_dec.split(','):
                        d = d.strip()
                        if '->' in d:
                            d = d.split('->')[-1].strip()
                        if d and d != 'HEAD':
                            decorations.append(d)
                entries.append({
                    'full_hash':   parts[0],
                    'hash':        parts[0][:8],
                    'subject':     parts[1],
                    'author':      parts[2],
                    'date':        parts[3][:10],
                    'decorations': decorations,
                })
        self._result['history_entries'] = entries

    def _on_abbrev_ref_done(self, rc, out, err):
        self._result['current_branch'] = (out.strip()
                                          if rc == 0 and out.strip()
                                          else 'main')

    def _on_branch_list_done(self, rc, out, err):
        branches = []
        if rc == 0 and out.strip():
            for line in out.strip().split('\n'):
                name = line.strip().lstrip('* ').strip()
                if name:
                    branches.append(name)
        self._result['branches'] = branches

        for b in branches:
            self._steps.append({
                'label':   f'rev-list {b}',
                'args':    ['rev-list', '--max-count=1000', b],
                'timeout': 30,
                'on_done': (lambda rc, out, err, _b=b:
                            self._on_rev_list_done(_b, rc, out, err)),
            })

        if self._auto_push:
            branch = self._result['current_branch']
            self._steps.append({
                'label':   f'push {branch}',
                'args':    ['push', '--set-upstream',
                            self._auto_push_url, branch],
                'timeout': 60,
                'on_done': self._on_push_done,
            })

    def _on_rev_list_done(self, branch, rc, out, err):
        if rc != 0 or not out.strip():
            self._result['branch_reach'][branch] = set()
        else:
            self._result['branch_reach'][branch] = set(out.strip().splitlines())

    def _on_push_done(self, rc, out, err):
        if rc != 0:
            self._result['push_error'] = (err.strip() or out.strip()
                                          or 'push failed')
        else:
            self._result['pushed']      = True
            self._result['push_branch'] = self._result['current_branch']

    # ----- Modal driver ---------------------------------------------------------

    def modal(self, context, event):
        if event.type != 'TIMER':
            return {'PASS_THROUGH'}

        # If a subprocess is currently in flight, poll it.
        if self._proc is not None:
            rc = self._proc.poll()
            if rc is None:
                if (time.time() - self._proc_start) > self._proc_step['timeout']:
                    try:
                        self._proc.kill()
                    except Exception:
                        pass
                    try:
                        self._proc.communicate(timeout=1)
                    except Exception:
                        pass
                    self._error = (f"git {self._proc_step['label']} "
                                   f"timed out after "
                                   f"{self._proc_step['timeout']}s")
                    self._proc      = None
                    self._proc_step = None
                else:
                    return {'PASS_THROUGH'}
            else:
                try:
                    out, err = self._proc.communicate(timeout=1)
                except Exception:
                    out, err = '', ''
                step = self._proc_step
                self._proc      = None
                self._proc_step = None
                try:
                    step['on_done'](rc, out or '', err or '')
                except Exception as e:
                    self._error = f"Error processing {step['label']}: {e}"

        if self._error is not None:
            return self._finalize_error(context)

        # No subprocess running — start the next queued step or finish.
        if self._step_idx < len(self._steps):
            step = self._steps[self._step_idx]
            self._step_idx += 1
            try:
                self._proc = subprocess.Popen(
                    [self._git_exe] + step['args'],
                    cwd=self._proj_root,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                self._proc_step  = step
                self._proc_start = time.time()
            except Exception as e:
                self._error = f"Failed to start git {step['label']}: {e}"
                return self._finalize_error(context)
            return {'PASS_THROUGH'}

        return self._finalize_success(context)

    # ----- Finalization ---------------------------------------------------------

    def _finalize_success(self, context):
        self._remove_timer(context)
        result = self._result
        scene  = context.scene

        if self._texture_warning:
            self.report({'WARNING'},
                        f"Texture collection failed: {self._texture_warning}")

        scene.nodesync_commit_message = ''
        scene.nodesync_restore_hash   = ''

        if result.get('history_entries') is not None:
            self._apply_history(scene, result)
        else:
            _refresh_history(scene, self._proj.root)

        if result.get('branches'):
            self._apply_branches(scene, result)
        else:
            _refresh_branches(scene, self._proj.root)

        msg_preview = result['msg'][:40]
        self.report({'INFO'},
                    f"Committed {result['exported_count']} group(s) "
                    f"[{result['short_hash']}]: {msg_preview}")

        if result.get('pushed'):
            scene.nodesync_sync_status = 'Pushed OK'
            _schedule_sync_status_clear(scene, 'Pushed OK')
            self.report({'INFO'},
                        f"Auto-pushed branch '{result['push_branch']}' to origin")
        elif result.get('push_error'):
            scene.nodesync_sync_status = 'Auto-push failed'
            self.report({'WARNING'},
                        f"Commit OK but auto-push failed: {result['push_error']}")

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
                self.report({'WARNING'},
                            f"Commit OK but screenshot failed: {e}")

        return {'FINISHED'}

    def _finalize_error(self, context):
        self._cleanup_proc()
        self._remove_timer(context)
        self.report({'ERROR'}, self._error or 'Unknown git error')
        return {'CANCELLED'}

    def cancel(self, context):
        self._cleanup_proc()
        self._remove_timer(context)

    def _cleanup_proc(self):
        if self._proc is not None:
            try:
                if self._proc.poll() is None:
                    self._proc.kill()
                self._proc.communicate(timeout=1)
            except Exception:
                pass
            self._proc      = None
            self._proc_step = None

    def _remove_timer(self, context):
        if self._timer is not None:
            try:
                context.window_manager.event_timer_remove(self._timer)
            except Exception:
                pass
            self._timer = None

    # ----- UI application (unchanged behavior) ---------------------------------

    def _apply_history(self, scene, result):
        entries        = result.get('history_entries', [])
        head_full      = result.get('history_head', '')
        current_branch = result.get('current_branch', '')
        branch_reach   = result.get('branch_reach', {})

        scene.nodesync_head_hash = head_full

        ownership = _compute_branch_ownership(entries, branch_reach, current_branch)

        scene.nodesync_commit_history.clear()
        for e in entries:
            decs  = e.get('decorations', [])
            owner = ownership.get(e['full_hash'], current_branch)

            item             = scene.nodesync_commit_history.add()
            item.full_hash   = e['full_hash']
            item.hash        = e['hash']
            item.subject     = e['subject']
            item.author      = e['author']
            item.date        = e['date']
            item.decorations = ','.join(decs)
            idx, color       = _branch_color_for_name(owner)
            item.branch_name = owner
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
        scene.nodesync_history_filter_type   = ''
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

        # Only reimport files that actually changed between the worktree and
        # the target commit.  Unchanged groups stay in bpy.data untouched, so a
        # huge revert that only modifies a handful of trees no longer pays the
        # cost of clearing and rebuilding every other group via the Python API
        # (which is what made large reverts feel much slower than Ctrl+Z).
        from ..project import ASSIGNMENTS_FILENAME, NODES_DIRNAME
        assignments_rel = f"{NODES_DIRNAME}/{ASSIGNMENTS_FILENAME}"
        to_reimport = [
            p for p in (diff['modified'] + diff['deleted'])
            if p != assignments_rel
        ]
        if to_reimport:
            imported = proj.import_specific_from_disk(to_reimport)
        else:
            imported = []
        proj.apply_scene_assignments()

        scene.nodesync_restore_hash = self.commit_hash

        _refresh_history(scene, proj.root)

        to_delete_paths = list(diff['added'])  # keep rel_paths so we know the collection

        if not to_delete_paths:
            self.report({'INFO'},
                        f"Restored nodes from {self.commit_hash[:8]} — "
                        f"{len(imported)} group(s) loaded. Commit to save this state.")
            return {'FINISHED'}

        _pending_pull_changes['creates'] = []
        _pending_pull_changes['deletes'] = to_delete_paths
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

        # Clear any active filter
        if scene.nodesync_history_filter_active:
            scene.nodesync_history_filter_active = False
            scene.nodesync_history_filter_label  = ''
            scene.nodesync_history_filter_type   = ''
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
        scene.nodesync_history_filter_type   = 'TREE'
        _refresh_history(scene, root, filter_hashes=hashes)
        count = len(scene.nodesync_commit_history)
        self.report({'INFO'}, f"Filtered to {count} commit(s) for '{display_name}'")
        return {'FINISHED'}


class NODESYNC_OT_filter_history_by_type(bpy.types.Operator):
    bl_idname      = 'nodesync.filter_history_by_type'
    bl_label       = 'Filter History by Type'
    bl_description = 'Show only commits that affected geometry nodes or shader nodes'

    tree_type: bpy.props.EnumProperty(
        items=[
            ('GEO',    'Geometry Nodes', 'Show commits that touched geometry node groups'),
            ('SHADER', 'Shader Nodes',   'Show commits that touched shader node trees'),
        ]
    )

    @classmethod
    def poll(cls, context):
        return bool(context.scene.nodesync_project_root.strip())

    def execute(self, context):
        scene = context.scene
        root  = scene.nodesync_project_root.strip()

        # Toggle off if already active with the same type
        if (scene.nodesync_history_filter_active
                and scene.nodesync_history_filter_type == self.tree_type):
            scene.nodesync_history_filter_active = False
            scene.nodesync_history_filter_label  = ''
            scene.nodesync_history_filter_type   = ''
            _refresh_history(scene, root)
            return {'FINISHED'}

        try:
            from ..git_ops import GitRepo
            repo = GitRepo(root)
            if self.tree_type == 'SHADER':
                hashes = repo.log_for_file('nodes/shader/')
                label  = 'Shader nodes'
            else:
                all_nodes    = repo.log_for_file('nodes/')
                shader_nodes = repo.log_for_file('nodes/shader/')
                hashes = all_nodes - shader_nodes
                label  = 'Geometry nodes'
        except Exception as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}

        scene.nodesync_history_filter_active = True
        scene.nodesync_history_filter_label  = label
        scene.nodesync_history_filter_type   = self.tree_type
        _refresh_history(scene, root, filter_hashes=hashes)
        count = len(scene.nodesync_commit_history)
        self.report({'INFO'}, f"Showing {count} commit(s) for {label}")
        return {'FINISHED'}


classes = [
    NODESYNC_OT_commit,
    NODESYNC_OT_refresh_history,
    NODESYNC_OT_checkout_commit,
    NODESYNC_OT_toggle_history_filter,
    NODESYNC_OT_filter_history_by_type,
]
