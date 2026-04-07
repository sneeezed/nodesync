"""
Blender UI panels for NodeSync — shown in the Geometry Node editor N-panel.
"""

import bpy
import os


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
            row.label(text=f"{item.hash}", icon='FILE_TICK')
            col = row.column()
            col.label(text=item.subject[:35] + ('…' if len(item.subject) > 35 else ''))
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

        # Action buttons
        row = layout.row(align=True)
        row.operator('nodesync.init_project', text='Init Project', icon='NEWFOLDER')

        # Status — only show once a valid project is set
        if root and os.path.isdir(root):
            box = layout.box()
            col = box.column(align=True)

            # Show blend file link if saved
            blend = bpy.data.filepath
            if blend:
                col.label(text=os.path.basename(blend), icon='FILE_BLEND')
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

        layout.operator('nodesync.refresh_history', icon='FILE_REFRESH')

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


# ---------------------------------------------------------------------------
# Registration list — ORDER MATTERS: parent panels before children
# ---------------------------------------------------------------------------

classes = [
    NODESYNC_UL_history,
    NODE_PT_nodesync,
    NODE_PT_nodesync_project,
    NODE_PT_nodesync_vc,
    NODE_PT_nodesync_history,
]
