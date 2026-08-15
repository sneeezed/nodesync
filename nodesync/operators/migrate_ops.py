"""
Operator for the one-shot filename migration of pre-1.3.1 projects.

Temporary — remove together with nodesync/migrate.py once the user base has
rolled forward.  See that module's docstring for the background.
"""

import bpy

from .helpers import _get_project, _refresh_migration_status


# How many individual changes to spell out in the confirm dialog before
# collapsing the rest into a "+N more" line.
_MAX_LISTED = 12


class NODESYNC_OT_migrate_filenames(bpy.types.Operator):
    bl_idname      = 'nodesync.migrate_filenames'
    bl_label       = 'Migrate Project Files'
    bl_description = ('Rename files written by older NodeSync versions to the '
                      'current naming scheme, and repair files whose names the '
                      'operating system cannot delete')
    bl_options     = {'REGISTER'}

    def invoke(self, context, event):
        from .. import migrate

        proj = _get_project(context.scene)
        if proj is None:
            self.report({'ERROR'}, "No active NodeSync project")
            return {'CANCELLED'}

        self._actions = migrate.scan(proj)
        if not self._actions:
            _refresh_migration_status(context.scene, proj.root)
            self.report({'INFO'},
                        "Nothing to migrate — all filenames are already current")
            return {'FINISHED'}

        return context.window_manager.invoke_props_dialog(self, width=560)

    def draw(self, context):
        from .. import migrate

        layout  = self.layout
        proj    = _get_project(context.scene)
        root    = proj.root if proj else ''
        actions = getattr(self, '_actions', [])

        renames    = sum(1 for a in actions if a['kind'] == migrate.RENAME)
        supersedes = sum(1 for a in actions if a['kind'] == migrate.SUPERSEDE)
        rescues    = sum(1 for a in actions if a['kind'] == migrate.RESCUE)

        col = layout.column(align=True)
        col.label(text=f'{len(actions)} file(s) will be changed:', icon='FILE_REFRESH')
        if renames:
            col.label(text=f'    {renames} renamed to the current scheme')
        if rescues:
            col.label(text=f'    {rescues} repaired (name the OS cannot delete)')
        if supersedes:
            col.label(text=f'    {supersedes} deleted (a correct copy already exists)')

        layout.separator()
        box = layout.column(align=True)
        for action in actions[:_MAX_LISTED]:
            box.label(text=migrate.describe(action, root))
        if len(actions) > _MAX_LISTED:
            box.label(text=f'    … and {len(actions) - _MAX_LISTED} more')

        layout.separator()
        warn = layout.box().column(align=True)
        warn.label(text='This edits files in your project folder.', icon='ERROR')
        warn.label(text='Commit or stash any work in progress first.')
        warn.label(text='If others share this repository, everyone must')
        warn.label(text='update NodeSync before you push the result —')
        warn.label(text='an older version will recreate the old names.')

    def execute(self, context):
        from .. import migrate

        proj = _get_project(context.scene)
        if proj is None:
            self.report({'ERROR'}, "No active NodeSync project")
            return {'CANCELLED'}

        # Re-scan rather than trusting the plan built in invoke(): the dialog
        # may have been open for a while, and applying a stale plan would act
        # on paths that no longer mean what they meant when it was drawn.
        actions = migrate.scan(proj)
        if not actions:
            _refresh_migration_status(context.scene, proj.root)
            self.report({'INFO'}, "Nothing to migrate")
            return {'FINISHED'}

        applied, errors = migrate.apply(actions)

        # Stage the result so the next commit records it as renames rather than
        # a pile of unexplained deletions.  Purely a convenience — a failure
        # here does not undo the migration itself.
        if applied:
            try:
                from ..git_ops import GitRepo
                repo = GitRepo(proj.root)
                if repo.is_repo():
                    for path in ('nodes/', 'textures/'):
                        try:
                            repo.add(path)
                        except Exception:
                            pass
            except Exception as e:
                print(f"[NodeSync] Could not stage migrated files: {e}")

        _refresh_migration_status(context.scene, proj.root)

        if errors:
            self.report(
                {'WARNING'},
                f"Migrated {len(applied)} file(s); {len(errors)} failed "
                f"({errors[0]}). See Window > Toggle System Console.")
        else:
            self.report(
                {'INFO'},
                f"Migrated {len(applied)} file(s) — commit to record the change")
        return {'FINISHED'}


classes = [
    NODESYNC_OT_migrate_filenames,
]
