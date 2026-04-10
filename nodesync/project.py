"""
Project initialization and config management.

A NodeSync project is a folder containing:
    .nodesync          JSON config file
    nodes/             One JSON file per tracked node group
    .git/              Managed by Git
"""

import os
import json


CONFIG_FILENAME = '.nodesync'
NODES_DIRNAME   = 'nodes'


class NodeSyncProject:
    def __init__(self, root: str):
        self.root        = os.path.normpath(root)
        self.config_path = os.path.join(self.root, CONFIG_FILENAME)
        self.nodes_dir   = os.path.join(self.root, NODES_DIRNAME)

    # ------------------------------------------------------------------
    # Config
    # ------------------------------------------------------------------

    def config_exists(self) -> bool:
        return os.path.isfile(self.config_path)

    def load_config(self) -> dict:
        if not self.config_exists():
            return {'version': '1.0', 'tracked_groups': []}
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {'version': '1.0', 'tracked_groups': []}

    def save_config(self, cfg: dict):
        with open(self.config_path, 'w', encoding='utf-8') as f:
            json.dump(cfg, f, indent=2)

    def get_tracked_groups(self) -> list:
        return self.load_config().get('tracked_groups', [])

    def set_tracked_groups(self, names: list):
        cfg = self.load_config()
        cfg['tracked_groups'] = list(names)
        self.save_config(cfg)

    def toggle_tracked(self, name: str) -> bool:
        """Add or remove name. Returns True if now tracked, False if removed."""
        cfg  = self.load_config()
        lst  = cfg.get('tracked_groups', [])
        if name in lst:
            lst.remove(name)
            tracked = False
        else:
            lst.append(name)
            tracked = True
        cfg['tracked_groups'] = lst
        self.save_config(cfg)
        return tracked

    def get_remote_url(self) -> str:
        return self.load_config().get('remote_url', '')

    def set_remote_url(self, url: str):
        cfg = self.load_config()
        cfg['remote_url'] = url
        self.save_config(cfg)

    def get_branch_colors(self) -> dict:
        """Return dict of branch_name → [r, g, b]."""
        return self.load_config().get('branch_colors', {})

    def set_branch_color(self, branch_name: str, color):
        """Save a branch color (list or tuple of 3 floats) to config."""
        cfg = self.load_config()
        if 'branch_colors' not in cfg:
            cfg['branch_colors'] = {}
        cfg['branch_colors'][branch_name] = list(color)
        self.save_config(cfg)

    # ------------------------------------------------------------------
    # Paths
    # ------------------------------------------------------------------

    def ensure_nodes_dir(self):
        os.makedirs(self.nodes_dir, exist_ok=True)

    def node_file_path(self, group_name: str) -> str:
        safe = group_name.replace('/', '_').replace('\\', '_')
        return os.path.join(self.nodes_dir, safe + '.json')

    # ------------------------------------------------------------------
    # Export / Import helpers (called by operators and the save hook)
    # ------------------------------------------------------------------

    def export_group(self, node_group) -> str:
        """Export one node group to JSON. Returns the file path written.

        Skips the write if the serialized content is identical to what is
        already on disk so that git only sees files that actually changed.
        """
        from .serializer import export_node_group
        self.ensure_nodes_dir()
        data        = export_node_group(node_group)
        out_path    = self.node_file_path(node_group.name)
        new_content = json.dumps(data, indent=2)

        if os.path.isfile(out_path):
            with open(out_path, 'r', encoding='utf-8') as f:
                if f.read() == new_content:
                    return out_path   # unchanged — skip write

        with open(out_path, 'w', encoding='utf-8') as f:
            f.write(new_content)
        return out_path

    def export_all_groups(self) -> list:
        """
        Export every Geometry node group in bpy.data to JSON.
        Returns list of group names that were successfully exported.
        """
        import bpy
        exported = []
        for ng in bpy.data.node_groups:
            if ng.type != 'GEOMETRY':
                continue
            try:
                self.export_group(ng)
                exported.append(ng.name)
            except Exception as e:
                print(f"[NodeSync] Failed to export '{ng.name}': {e}")
        return exported

    def import_all_from_disk(self) -> list:
        """
        Read every JSON file in nodes/ and reconstruct it in bpy.data.
        Returns list of group names that were successfully imported.
        """
        from .deserializer import reconstruct_node_group
        if not os.path.isdir(self.nodes_dir):
            return []
        imported = []
        # Collect all json files
        json_files = [
            f for f in os.listdir(self.nodes_dir)
            if f.endswith('.json')
        ]
        for filename in json_files:
            path = os.path.join(self.nodes_dir, filename)
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                ng = reconstruct_node_group(data)
                if ng:
                    imported.append(ng.name)
            except Exception as e:
                print(f"[NodeSync] Failed to import '{filename}': {e}")
        return imported

    def import_specific_from_disk(self, repo_relative_paths: list) -> list:
        """
        Reconstruct only the node groups whose JSON files are listed in
        repo_relative_paths (e.g. ['nodes/Foo.json', 'nodes/Bar.json']).
        Returns list of successfully imported group names.
        """
        from .deserializer import reconstruct_node_group
        imported = []
        for rel_path in repo_relative_paths:
            abs_path = os.path.join(self.root, rel_path)
            if not os.path.isfile(abs_path):
                continue
            try:
                with open(abs_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                ng = reconstruct_node_group(data)
                if ng:
                    imported.append(ng.name)
            except Exception as e:
                print(f"[NodeSync] Failed to import '{rel_path}': {e}")
        return imported

    def load_group_data_from_disk(self, repo_relative_paths: list) -> list:
        """
        Read JSON files and return their parsed dicts without importing into
        Blender.  Used to preview group names before showing a confirmation
        dialog.  Silently skips unreadable files.
        """
        result = []
        for rel_path in repo_relative_paths:
            abs_path = os.path.join(self.root, rel_path)
            if not os.path.isfile(abs_path):
                continue
            try:
                with open(abs_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                result.append((data.get('name', rel_path), rel_path))
            except Exception:
                pass
        return result

    # ------------------------------------------------------------------
    # Class method helpers
    # ------------------------------------------------------------------

    @classmethod
    def find_for_blend(cls, blend_path: str):
        """
        Walk up from blend_path's directory until a .nodesync file is found.
        Returns a NodeSyncProject or None.
        """
        directory = os.path.dirname(os.path.abspath(blend_path))
        while True:
            if os.path.isfile(os.path.join(directory, CONFIG_FILENAME)):
                return cls(directory)
            parent = os.path.dirname(directory)
            if parent == directory:
                break
            directory = parent
        return None
