"""
NodeSync — Git-backed version control for Blender Geometry Node trees.
"""

bl_info = {
    'name':        'NodeSync',
    'author':      'NodeSync',
    'version':     (1, 1, 0),
    'blender':     (4, 0, 0),
    'location':    'Geometry / Shader Node Editor > N-Panel > NodeSync',
    'description': 'Git-backed version control for Geometry and Shader Node trees',
    'category':    'Node',
}

import bpy
import os
from bpy.app.handlers import persistent

# Global preview collection — allocated on register, freed on unregister
_previews = None


# ---------------------------------------------------------------------------
# Addon Preferences — Git remote credential storage
# ---------------------------------------------------------------------------

class NodeSyncPreferences(bpy.types.AddonPreferences):
    bl_idname = __package__

    remote_username: bpy.props.StringProperty(
        name        = 'Remote Username',
        description = ('Username for HTTPS authentication with your Git '
                       'remote.  Service-specific values: leave blank for '
                       'GitHub or Azure DevOps; use "oauth2" for GitLab; '
                       '"x-token-auth" for Bitbucket; your account name '
                       'for Codeberg, Gitea, or self-hosted Forgejo'),
        default     = '',
    )

    remote_token: bpy.props.StringProperty(
        name        = 'Personal Access Token',
        description = ('Token for HTTPS authentication with your Git remote '
                       '(GitLab, Codeberg, Gitea, GitHub, Bitbucket, '
                       'self-hosted, etc.).  Leave blank if you authenticate '
                       'over SSH instead'),
        subtype     = 'PASSWORD',
        default     = '',
    )

    auto_push_on_commit: bpy.props.BoolProperty(
        name        = 'Auto-Push on Commit',
        description = ('Automatically push to the remote after every commit '
                       'when a remote URL is configured'),
        default     = False,
    )

    screenshot_on_commit: bpy.props.BoolProperty(
        name        = 'Screenshot Node Editor on Commit',
        description = ('Capture a screenshot of the Geometry Node editor when '
                       'committing and show it in the commit history panel'),
        default     = False,
    )

    track_textures: bpy.props.BoolProperty(
        name        = 'Track Shader Textures',
        description = ('On commit, copy every image used by a Shader Image '
                       'Texture node into the project textures/ folder and '
                       'commit it to Git'),
        default     = False,
    )

    def draw(self, context):
        layout = self.layout
        layout.label(text='Git Remote Authentication', icon='URL')
        box = layout.box()
        box.prop(self, 'remote_username')
        box.prop(self, 'remote_token')
        if not self.remote_token:
            box.label(text='Token required for HTTPS Push / Pull '
                           '(SSH URLs use your SSH agent instead)',
                      icon='INFO')
        col = box.column(align=True)
        col.scale_y = 0.85
        col.label(text='Username hints:', icon='QUESTION')
        col.label(text='  • GitHub / Azure DevOps — leave blank')
        col.label(text='  • GitLab — "oauth2"')
        col.label(text='  • Bitbucket — "x-token-auth"')
        col.label(text='  • Codeberg / Gitea / Forgejo — your account name')
        layout.separator()
        layout.label(text='Commit Behaviour', icon='FILE_TICK')
        layout.prop(self, 'auto_push_on_commit')
        layout.prop(self, 'screenshot_on_commit')
        layout.prop(self, 'track_textures')

# ---------------------------------------------------------------------------
# Module reload support (for addon development)
# ---------------------------------------------------------------------------

if 'props' in dir():
    import importlib
    from . import utils, serializer, deserializer, project, git_ops, props, operators, panels, diff
    from .git_ops import (
        exceptions as git_exceptions, base as git_base, state as git_state,
        history as git_history, checkout as git_checkout, diff as git_diff_mod,
        remote as git_remote, branches as git_branches, conflicts as git_conflicts,
    )
    from .operators import (
        helpers,
        project_ops, commit_ops, diff_ops, remote_ops, branch_ops, conflict_ops,
    )
    importlib.reload(utils)
    importlib.reload(serializer)
    importlib.reload(deserializer)
    importlib.reload(project)
    # Reload git_ops sub-modules in dependency order before the package init
    importlib.reload(git_exceptions)
    importlib.reload(git_base)
    importlib.reload(git_state)
    importlib.reload(git_history)
    importlib.reload(git_checkout)
    importlib.reload(git_diff_mod)
    importlib.reload(git_remote)
    importlib.reload(git_branches)
    importlib.reload(git_conflicts)
    importlib.reload(git_ops)
    importlib.reload(diff)
    importlib.reload(props)
    # Reload operator sub-modules in dependency order before the package init
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
# Auto-load hook — fires after a .blend file is opened
# ---------------------------------------------------------------------------

@persistent
def _nodesync_load_post(*args):
    try:
        scene = bpy.context.scene
        root  = getattr(scene, 'nodesync_project_root', '').strip()
        if not root or not os.path.isdir(root):
            return
        if not os.path.isfile(os.path.join(root, '.nodesync')):
            return
        from .project import NodeSyncProject
        from .operators.helpers import _refresh_history, _refresh_branches
        proj = NodeSyncProject(root)
        saved_url = proj.get_remote_url()
        if saved_url:
            scene.nodesync_remote_url = saved_url
        _refresh_branches(scene, root)
        _refresh_history(scene, root)
        print(f"[NodeSync] Auto-loaded project from {root}")
    except Exception as e:
        print(f"[NodeSync] Auto-load error: {e}")


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

    # 6. Load hook — auto-loads project when a .blend is opened
    if _nodesync_load_post not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_nodesync_load_post)

    print("[NodeSync] Addon registered")


def unregister():
    global _previews
    if _previews is not None:
        import bpy.utils.previews
        bpy.utils.previews.remove(_previews)
        _previews = None

    # Remove hooks first
    if _nodesync_save_post in bpy.app.handlers.save_post:
        bpy.app.handlers.save_post.remove(_nodesync_save_post)
    if _nodesync_load_post in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_nodesync_load_post)

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
