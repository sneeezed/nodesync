"""
NodeSync — Git-backed version control for Blender Geometry Node trees.
"""

bl_info = {
    'name':        'NodeSync',
    'author':      'NodeSync',
    'version':     (0, 2, 0),
    'blender':     (4, 0, 0),
    'location':    'Geometry Node Editor > N-Panel > NodeSync',
    'description': 'Git-backed version control for Geometry Node trees',
    'category':    'Node',
}

import bpy
import os
from bpy.app.handlers import persistent

# Global preview collection — allocated on register, freed on unregister
_previews = None


# ---------------------------------------------------------------------------
# Addon Preferences — GitHub token storage
# ---------------------------------------------------------------------------

class NodeSyncPreferences(bpy.types.AddonPreferences):
    bl_idname = __name__

    github_token: bpy.props.StringProperty(
        name        = 'GitHub Personal Access Token',
        description = ('Classic PAT with repo scope from github.com → '
                       'Settings → Developer settings → Personal access tokens'),
        subtype     = 'PASSWORD',
        default     = '',
    )

    auto_push_on_commit: bpy.props.BoolProperty(
        name        = 'Auto-Push on Commit',
        description = ('Automatically push to the remote after every commit '
                       'when a GitHub remote URL is configured'),
        default     = False,
    )

    screenshot_on_commit: bpy.props.BoolProperty(
        name        = 'Screenshot Node Editor on Commit',
        description = ('Capture a screenshot of the Geometry Node editor when '
                       'committing and show it in the commit history panel'),
        default     = False,
    )

    def draw(self, context):
        layout = self.layout
        layout.label(text='GitHub Authentication', icon='URL')
        box = layout.box()
        box.prop(self, 'github_token')
        if not self.github_token:
            box.label(text='Token required for Push / Pull', icon='ERROR')
        layout.separator()
        layout.label(text='Commit Behaviour', icon='FILE_TICK')
        layout.prop(self, 'auto_push_on_commit')
        layout.prop(self, 'screenshot_on_commit')

# ---------------------------------------------------------------------------
# Module reload support (for addon development)
# ---------------------------------------------------------------------------

if 'props' in dir():
    import importlib
    from . import utils, serializer, deserializer, project, git_ops, props, operators, panels, diff
    from .operators import (
        modifier_links, helpers,
        project_ops, commit_ops, diff_ops, remote_ops, branch_ops, conflict_ops,
    )
    importlib.reload(utils)
    importlib.reload(serializer)
    importlib.reload(deserializer)
    importlib.reload(project)
    importlib.reload(git_ops)
    importlib.reload(diff)
    importlib.reload(props)
    # Reload operator sub-modules in dependency order before the package init
    importlib.reload(modifier_links)
    importlib.reload(helpers)
    importlib.reload(project_ops)
    importlib.reload(commit_ops)
    importlib.reload(diff_ops)
    importlib.reload(remote_ops)
    importlib.reload(branch_ops)
    importlib.reload(conflict_ops)
    importlib.reload(operators)
    importlib.reload(panels)
else:
    from . import props, operators, panels, diff


# ---------------------------------------------------------------------------
# Auto-export save hook
# ---------------------------------------------------------------------------

@persistent
def _nodesync_save_post(*args):
    """
    Called by Blender after a .blend file is saved.
    Exports all tracked node groups to JSON in the project folder.
    *args absorbs the filepath argument in Blender 4.x and the scene
    argument in older versions.
    """
    try:
        scene = bpy.context.scene
        root  = getattr(scene, 'nodesync_project_root', '').strip()
        if not root or not os.path.isdir(root):
            return

        from .project import NodeSyncProject
        proj     = NodeSyncProject(root)
        exported = proj.export_all_groups()
        if exported:
            print(f"[NodeSync] Auto-exported {len(exported)} group(s): "
                  f"{', '.join(exported)}")
    except Exception as e:
        # Never let an exception crash Blender's save operation
        print(f"[NodeSync] Auto-export error: {e}")


# ---------------------------------------------------------------------------
# Register / Unregister
# ---------------------------------------------------------------------------

def register():
    global _previews
    import bpy.utils.previews
    _previews = bpy.utils.previews.new()

    # 0. Addon preferences (must be first)
    bpy.utils.register_class(NodeSyncPreferences)

    # 1. PropertyGroup types first (scene props reference them)
    for cls in props.classes:
        bpy.utils.register_class(cls)

    # 2. Scene-level properties
    for attr, prop in props.SCENE_PROPS.items():
        setattr(bpy.types.Scene, attr, prop)

    # 3. Operators
    for cls in operators.classes:
        bpy.utils.register_class(cls)

    # 4. UIList and Panels (parent panels must come before their children)
    for cls in panels.classes:
        bpy.utils.register_class(cls)

    # 5. Save hook
    if _nodesync_save_post not in bpy.app.handlers.save_post:
        bpy.app.handlers.save_post.append(_nodesync_save_post)

    print("[NodeSync] Addon registered")


def unregister():
    global _previews
    if _previews is not None:
        import bpy.utils.previews
        bpy.utils.previews.remove(_previews)
        _previews = None

    # Remove save hook first
    if _nodesync_save_post in bpy.app.handlers.save_post:
        bpy.app.handlers.save_post.remove(_nodesync_save_post)

    # Unregister in reverse order
    for cls in reversed(panels.classes):
        bpy.utils.unregister_class(cls)

    for cls in reversed(operators.classes):
        bpy.utils.unregister_class(cls)

    # Remove scene properties
    for attr in props.SCENE_PROPS:
        if hasattr(bpy.types.Scene, attr):
            delattr(bpy.types.Scene, attr)

    for cls in reversed(props.classes):
        bpy.utils.unregister_class(cls)

    bpy.utils.unregister_class(NodeSyncPreferences)

    print("[NodeSync] Addon unregistered")
