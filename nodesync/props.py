"""
PropertyGroup types and scene-level properties for NodeSync.
"""

import bpy


class NodeSyncCommitItem(bpy.types.PropertyGroup):
    """One row in the commit history list."""
    full_hash : bpy.props.StringProperty()
    hash      : bpy.props.StringProperty()
    subject   : bpy.props.StringProperty()
    author    : bpy.props.StringProperty()
    date      : bpy.props.StringProperty()


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
}


classes = [NodeSyncCommitItem]
