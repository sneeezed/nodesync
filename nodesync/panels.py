"""
Blender UI panels for NodeSync — shown in the Geometry Node editor N-panel.
"""

import bpy
import os


def _get_commit_preview_icon(full_hash: str, root: str) -> int:
    """Return an icon_id for the commit screenshot, or 0 if none exists."""
    if not full_hash or not root:
        return 0
    png_path = os.path.join(root, 'previews', f'{full_hash}.png')
    if not os.path.isfile(png_path):
        return 0
    try:
        from . import _previews
        if _previews is None:
            return 0
        if full_hash not in _previews:
            _previews.load(full_hash, png_path, 'IMAGE')
        return _previews[full_hash].icon_id
    except Exception:
        return 0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _active_root(scene) -> str:
    return scene.nodesync_project_root.strip()



# ---------------------------------------------------------------------------
# UIList — commit history
# ---------------------------------------------------------------------------

class NODESYNC_UL_history(bpy.types.UIList):
    bl_idname = 'NODESYNC_UL_history'

    def draw_item(self, context, layout, data, item, icon,
                  active_data, active_propname, index, flt_flag):
        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            row = layout.row(align=True)

            # Bookmark icon: shows on the currently-loaded commit (either a
            # revert target or HEAD if no revert is active)
            head_hash    = getattr(context.scene, 'nodesync_head_hash', '')
            restore_hash = getattr(context.scene, 'nodesync_restore_hash', '')
            active_hash  = restore_hash if restore_hash else head_hash
            is_active = bool(item.full_hash and item.full_hash == active_hash)
            row.label(text='', icon='BOOKMARKS' if is_active else 'BLANK1')

            # Branch color swatch — disabled so it shows color without opening the picker
            sub = row.row(align=True)
            sub.enabled = False
            sub.scale_x = 0.35
            sub.prop(item, 'branch_color', text='')

            row.label(text=f"{item.hash}", icon='FILE_TICK')
            col = row.column()
            col.label(text=item.subject[:30] + ('…' if len(item.subject) > 30 else ''))
            col = row.column()
            col.scale_x = 0.6
            col.label(text=item.date)
            op = row.operator('nodesync.checkout_commit', text='', icon='LOOP_BACK')
            op.commit_hash = item.full_hash
        elif self.layout_type == 'GRID':
            layout.label(text=item.hash)

    def filter_items(self, context, data, propname):
        items = getattr(data, propname)
        flt_flags = [self.bitflag_filter_item] * len(items)
        flt_neworder = list(range(len(items)))
        return flt_flags, flt_neworder


# ---------------------------------------------------------------------------
# UIList — branches
# ---------------------------------------------------------------------------

class NODESYNC_UL_branches(bpy.types.UIList):
    bl_idname = 'NODESYNC_UL_branches'

    def draw_item(self, context, layout, data, item, icon,
                  active_data, active_propname, index, flt_flag):
        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            row = layout.row(align=True)
            # Color swatch — disabled so it's display-only (slightly dimmed, not clickable)
            sub = row.row(align=True)
            sub.enabled = False
            sub.scale_x = 0.35
            sub.prop(item, 'color', text='')
            is_current = (item.name == context.scene.nodesync_current_branch)
            row.label(
                text=item.name,
                icon='LAYER_ACTIVE' if is_current else 'LAYER_USED',
            )
            if not is_current:
                op = row.operator('nodesync.switch_branch', text='', icon='LOOP_FORWARDS')
                op.branch_name = item.name
        elif self.layout_type == 'GRID':
            layout.label(text=item.name)

    def filter_items(self, context, data, propname):
        items = getattr(data, propname)
        flt_flags = [self.bitflag_filter_item] * len(items)
        flt_neworder = list(range(len(items)))
        return flt_flags, flt_neworder


# ---------------------------------------------------------------------------
# Root panel (tab header only)
# ---------------------------------------------------------------------------

class NODE_PT_nodesync(bpy.types.Panel):
    bl_idname      = 'NODE_PT_nodesync'
    bl_label       = 'NodeSync'
    bl_space_type  = 'NODE_EDITOR'
    bl_region_type = 'UI'
    bl_category    = 'NodeSync'

    @classmethod
    def poll(cls, context):
        sdata = context.space_data
        return (sdata is not None
                and sdata.type == 'NODE_EDITOR'
                and getattr(sdata, 'tree_type', '') == 'GeometryNodeTree')

    def draw(self, context):
        pass  # sub-panels carry all content


# ---------------------------------------------------------------------------
# Project section
# ---------------------------------------------------------------------------

class NODE_PT_nodesync_project(bpy.types.Panel):
    bl_idname      = 'NODE_PT_nodesync_project'
    bl_parent_id   = 'NODE_PT_nodesync'
    bl_label       = 'Project'
    bl_space_type  = 'NODE_EDITOR'
    bl_region_type = 'UI'

    def draw(self, context):
        layout = self.layout
        scene  = context.scene
        root   = _active_root(scene)

        # Folder path row
        row = layout.row(align=True)
        row.prop(scene, 'nodesync_project_root', text='')
        row.operator('nodesync.open_project', text='', icon='FILE_FOLDER')

        # Action buttons — Clone is the primary action for connecting to an existing repo
        col = layout.column(align=True)
        col.scale_y = 1.2
        col.operator('nodesync.clone_from_github', icon='IMPORT')
        col.operator('nodesync.init_project', text='Init New Project', icon='NEWFOLDER')

        # Status — only show once a valid project is set
        if root and os.path.isdir(root):
            box = layout.box()
            col = box.column(align=True)
            blend = bpy.data.filepath
            if blend:
                col.label(text=os.path.basename(blend), icon='FILE_BLEND')

            layout.separator()

            # GitHub / Remote section
            layout.label(text='GitHub', icon='URL')
            row = layout.row(align=True)
            row.prop(scene, 'nodesync_remote_url', text='', placeholder='https://github.com/user/repo')
            row.operator('nodesync.set_remote', text='', icon='CHECKMARK')

            row = layout.row(align=True)
            row.scale_y = 1.2
            push_op = row.operator('nodesync.push', text='Push ↑', icon='EXPORT')
            pull_op = row.operator('nodesync.pull', text='Pull ↓', icon='IMPORT')

            if scene.nodesync_sync_status:
                status = scene.nodesync_sync_status
                is_error = 'failed' in status.lower() or 'conflict' in status.lower()
                box2 = layout.box()
                box2.alert = is_error
                box2.label(text=status,
                           icon='ERROR' if is_error else 'INFO')

        elif root:
            layout.label(text='Folder not found', icon='ERROR')


# ---------------------------------------------------------------------------
# Version Control section
# ---------------------------------------------------------------------------

class NODE_PT_nodesync_vc(bpy.types.Panel):
    bl_idname      = 'NODE_PT_nodesync_vc'
    bl_parent_id   = 'NODE_PT_nodesync'
    bl_label       = 'Version Control'
    bl_space_type  = 'NODE_EDITOR'
    bl_region_type = 'UI'

    def draw(self, context):
        layout = self.layout
        scene  = context.scene
        root   = _active_root(scene)

        if not root:
            layout.label(text='Initialize a project first', icon='ERROR')
            return

        # Commit message
        layout.prop(scene, 'nodesync_commit_message', text='', placeholder='Commit message…')

        # Alert box when diff mode is blocking commits
        if scene.nodesync_diff_active:
            box = layout.box()
            box.alert = True
            box.label(text='Diff view active — exit before making changes', icon='ERROR')

        # Commit button (full width, disabled while diff is active)
        row = layout.row()
        row.scale_y = 1.3
        row.enabled = not scene.nodesync_diff_active
        row.operator('nodesync.commit', icon='FILE_TICK')

        layout.separator()

        # Diff toggle
        if scene.nodesync_diff_active:
            row = layout.row()
            row.alert = True
            row.scale_y = 1.2
            row.operator('nodesync.exit_diff', icon='HIDE_OFF')
        else:
            row = layout.row(align=True)
            row.scale_y = 1.2
            row.operator('nodesync.enter_diff', icon='HIDE_ON')
            row.operator('nodesync.diff_legend', text='', icon='QUESTION')


# ---------------------------------------------------------------------------
# Branches section
# ---------------------------------------------------------------------------

class NODE_PT_nodesync_branches(bpy.types.Panel):
    bl_idname      = 'NODE_PT_nodesync_branches'
    bl_parent_id   = 'NODE_PT_nodesync'
    bl_label       = 'Branches'
    bl_space_type  = 'NODE_EDITOR'
    bl_region_type = 'UI'
    bl_options     = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        scene  = context.scene
        root   = _active_root(scene)

        if not root:
            layout.label(text='Initialize a project first', icon='ERROR')
            return

        # Current branch + create button
        row = layout.row(align=True)
        row.label(
            text=f"Current: {scene.nodesync_current_branch or '—'}",
            icon='BOOKMARKS',
        )
        row.operator('nodesync.create_branch', text='', icon='ADD')

        if not scene.nodesync_branch_list:
            layout.label(text='No branches found', icon='INFO')
            return

        layout.template_list(
            'NODESYNC_UL_branches', '',
            scene, 'nodesync_branch_list',
            scene, 'nodesync_branch_index',
            rows=min(5, len(scene.nodesync_branch_list)),
        )


# ---------------------------------------------------------------------------
# Conflicts section (only visible when there are active conflicts)
# ---------------------------------------------------------------------------

class NODE_PT_nodesync_conflicts(bpy.types.Panel):
    bl_idname      = 'NODE_PT_nodesync_conflicts'
    bl_parent_id   = 'NODE_PT_nodesync'
    bl_label       = 'Merge Conflicts'
    bl_space_type  = 'NODE_EDITOR'
    bl_region_type = 'UI'

    @classmethod
    def poll(cls, context):
        return context.scene.nodesync_has_conflicts

    def draw(self, context):
        layout = self.layout
        scene  = context.scene

        total    = len(scene.nodesync_conflict_items)
        resolved = sum(1 for i in scene.nodesync_conflict_items if i.resolved)

        # Header warning
        box = layout.box()
        box.alert = True
        box.label(
            text=f"Resolve {total - resolved} of {total} conflict(s)",
            icon='ERROR',
        )

        layout.separator()

        # Per-file conflict rows
        for item in scene.nodesync_conflict_items:
            row = layout.row(align=True)
            if item.resolved:
                row.label(text=item.group_name, icon='CHECKMARK')
            else:
                row.label(text=item.group_name, icon='QUESTION')
                op_mine   = row.operator('nodesync.resolve_conflict',
                                         text='Keep Mine', icon='FILE_TICK')
                op_mine.filepath = item.filepath
                op_mine.strategy = 'ours'

                op_theirs = row.operator('nodesync.resolve_conflict',
                                          text='Use Remote', icon='IMPORT')
                op_theirs.filepath = item.filepath
                op_theirs.strategy = 'theirs'

        layout.separator()

        # Complete / Abort
        row = layout.row(align=True)
        row.scale_y = 1.3
        complete = row.operator('nodesync.complete_merge', icon='CHECKMARK')
        abort    = row.operator('nodesync.abort_merge',   icon='X')

        if resolved < total:
            layout.label(text='Resolve all conflicts to complete merge', icon='INFO')


# ---------------------------------------------------------------------------
# History section
# ---------------------------------------------------------------------------

class NODE_PT_nodesync_history(bpy.types.Panel):
    bl_idname      = 'NODE_PT_nodesync_history'
    bl_parent_id   = 'NODE_PT_nodesync'
    bl_label       = 'History'
    bl_space_type  = 'NODE_EDITOR'
    bl_region_type = 'UI'
    bl_options     = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        scene  = context.scene
        root   = _active_root(scene)

        if not root:
            layout.label(text='Initialize a project first', icon='ERROR')
            return

        row = layout.row(align=True)
        row.operator('nodesync.refresh_history', text='', icon='FILE_REFRESH')

        nt = getattr(context.space_data, 'node_tree', None)
        if nt:
            if scene.nodesync_history_filter_active:
                row.operator('nodesync.toggle_history_filter',
                             text='All commits', icon='X')
            else:
                short_name = nt.name[:18] + ('…' if len(nt.name) > 18 else '')
                row.operator('nodesync.toggle_history_filter',
                             text=f'{short_name} only', icon='FILTER')

        if scene.nodesync_history_filter_active:
            layout.label(
                text=f'Filtered: {scene.nodesync_history_filter_label}',
                icon='INFO',
            )

        if not scene.nodesync_commit_history:
            layout.label(text='No commits yet', icon='INFO')
            return

        layout.template_list(
            'NODESYNC_UL_history', '',
            scene, 'nodesync_commit_history',
            scene, 'nodesync_history_index',
            rows=min(6, len(scene.nodesync_commit_history)),
        )

        # Show selected commit detail
        idx = scene.nodesync_history_index
        if 0 <= idx < len(scene.nodesync_commit_history):
            item = scene.nodesync_commit_history[idx]
            box  = layout.box()
            col  = box.column(align=True)
            col.label(text=item.hash,    icon='FILE_TICK')
            col.label(text=item.subject, icon='NONE')
            col.label(text=f"{item.author}  {item.date}", icon='NONE')
            if item.decorations:
                col.label(text=item.decorations.replace(',', '  '), icon='BOOKMARKS')

            # Screenshot thumbnail — only shown when a preview PNG was saved
            icon_id = _get_commit_preview_icon(item.full_hash, root)
            if icon_id:
                col.separator()
                col.template_icon(icon_value=icon_id, scale=8.0)


# ---------------------------------------------------------------------------
# Registration list — ORDER MATTERS: parent panels before children
# ---------------------------------------------------------------------------

classes = [
    NODESYNC_UL_history,
    NODESYNC_UL_branches,
    NODE_PT_nodesync,
    NODE_PT_nodesync_project,
    NODE_PT_nodesync_vc,
    NODE_PT_nodesync_branches,
    NODE_PT_nodesync_conflicts,
    NODE_PT_nodesync_history,
]
