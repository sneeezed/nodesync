"""
PropertyGroup types and scene-level properties for NodeSync.
"""

import bpy


class NodeSyncCommitItem(bpy.types.PropertyGroup):
    """One row in the commit history list."""
    full_hash   : bpy.props.StringProperty()
    hash        : bpy.props.StringProperty()
    subject     : bpy.props.StringProperty()
    author      : bpy.props.StringProperty()
    date        : bpy.props.StringProperty()
    decorations : bpy.props.StringProperty()  # comma-separated branch names


class NodeSyncBranchItem(bpy.types.PropertyGroup):
    """One branch with a user-assigned display color."""
    name  : bpy.props.StringProperty()
    color : bpy.props.FloatVectorProperty(
        subtype = 'COLOR',
        size    = 3,
        min     = 0.0, max = 1.0,
        default = (0.2, 0.6, 1.0),
    )


class NodeSyncConflictItem(bpy.types.PropertyGroup):
    """One conflicted file during a merge."""
    filepath   : bpy.props.StringProperty()   # relative git path, e.g. nodes/Foo.json
    group_name : bpy.props.StringProperty()   # human-readable node group name
    resolved   : bpy.props.BoolProperty(default=False)


# Scene properties registered/unregistered by __init__.py
SCENE_PROPS = {
    'nodesync_project_root': bpy.props.StringProperty(
        name        = 'Project Root',
        description = 'Folder containing the .nodesync config and nodes/ directory',
        subtype     = 'DIR_PATH',
        default     = '',
    ),
    'nodesync_commit_message': bpy.props.StringProperty(
        name        = 'Commit Message',
        description = 'Message for the next Git commit',
        default     = '',
    ),
    'nodesync_commit_history': bpy.props.CollectionProperty(
        type        = NodeSyncCommitItem,
    ),
    'nodesync_history_index': bpy.props.IntProperty(
        default     = 0,
    ),
    'nodesync_status_message': bpy.props.StringProperty(
        name        = 'Status',
        default     = '',
    ),
    'nodesync_diff_active': bpy.props.BoolProperty(
        name        = 'Diff Mode Active',
        description = 'Whether the visual diff overlay is currently shown',
        default     = False,
    ),
    # Clone workflow
    'nodesync_clone_url': bpy.props.StringProperty(
        name        = 'Clone URL',
        description = 'GitHub repository HTTPS URL to clone from',
        default     = '',
    ),
    'nodesync_clone_dir': bpy.props.StringProperty(
        name        = 'Clone Into',
        description = 'Local folder to clone the repository into',
        subtype     = 'DIR_PATH',
        default     = '',
    ),
    # GitHub / remote
    'nodesync_remote_url': bpy.props.StringProperty(
        name        = 'Remote URL',
        description = 'GitHub repository HTTPS URL',
        default     = '',
    ),
    'nodesync_sync_status': bpy.props.StringProperty(
        name        = 'Sync Status',
        default     = '',
    ),
    # Branches
    'nodesync_current_branch': bpy.props.StringProperty(
        name        = 'Current Branch',
        default     = '',
    ),
    'nodesync_branch_list': bpy.props.CollectionProperty(
        type        = NodeSyncBranchItem,
    ),
    'nodesync_branch_index': bpy.props.IntProperty(
        default     = 0,
    ),
    'nodesync_new_branch_name': bpy.props.StringProperty(
        name        = 'Branch Name',
        description = 'Name for the new branch',
        default     = '',
    ),
    'nodesync_new_branch_color': bpy.props.FloatVectorProperty(
        name        = 'Branch Color',
        subtype     = 'COLOR',
        size        = 3,
        min         = 0.0, max = 1.0,
        default     = (0.2, 0.6, 1.0),
    ),
    # Conflicts
    'nodesync_has_conflicts': bpy.props.BoolProperty(
        name        = 'Has Conflicts',
        default     = False,
    ),
    'nodesync_conflict_items': bpy.props.CollectionProperty(
        type        = NodeSyncConflictItem,
    ),
    'nodesync_conflict_index': bpy.props.IntProperty(
        default     = 0,
    ),
}


classes = [NodeSyncCommitItem, NodeSyncBranchItem, NodeSyncConflictItem]
