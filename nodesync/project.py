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
SHADER_SUBDIR   = 'shader'
MATERIALS_SUBDIR = 'materials'
WORLDS_SUBDIR    = 'worlds'
LIGHTS_SUBDIR    = 'lights'
TEXTURES_DIRNAME = 'textures'

TRACKED_TYPES = {'GEOMETRY', 'SHADER'}

# Embedded shader trees we mirror to disk.  Each tuple is
#   (collection_name_on_bpy_data, on-disk subdirectory under nodes/shader/)
EMBEDDED_SHADER_OWNERS = (
    ('materials', MATERIALS_SUBDIR),
    ('worlds',    WORLDS_SUBDIR),
    ('lights',    LIGHTS_SUBDIR),
)


class NodeSyncProject:
    def __init__(self, root: str):
        self.root          = os.path.normpath(root)
        self.config_path   = os.path.join(self.root, CONFIG_FILENAME)
        self.nodes_dir     = os.path.join(self.root, NODES_DIRNAME)
        self.shader_dir    = os.path.join(self.nodes_dir, SHADER_SUBDIR)
        self.materials_dir = os.path.join(self.shader_dir, MATERIALS_SUBDIR)
        self.worlds_dir    = os.path.join(self.shader_dir, WORLDS_SUBDIR)
        self.lights_dir    = os.path.join(self.shader_dir, LIGHTS_SUBDIR)
        self.textures_dir  = os.path.join(self.root, TEXTURES_DIRNAME)

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

    def ensure_shader_dir(self):
        os.makedirs(self.shader_dir, exist_ok=True)

    def ensure_textures_dir(self):
        os.makedirs(self.textures_dir, exist_ok=True)

    def node_file_path(self, group_name: str, tree_type: str = 'GeometryNodeTree') -> str:
        safe = group_name.replace('/', '_').replace('\\', '_')
        if tree_type == 'ShaderNodeTree':
            return os.path.join(self.shader_dir, safe + '.json')
        return os.path.join(self.nodes_dir, safe + '.json')

    def embedded_shader_file_path(self, owner_kind: str, owner_name: str) -> str:
        """
        File path for an embedded shader tree owned by a Material/World/Light.
        owner_kind is the bpy.data collection name ('materials', 'worlds', 'lights').
        """
        safe = owner_name.replace('/', '_').replace('\\', '_')
        subdir_map = dict(EMBEDDED_SHADER_OWNERS)
        subdir = subdir_map.get(owner_kind, owner_kind)
        return os.path.join(self.shader_dir, subdir, safe + '.json')

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
        tree_type = node_group.bl_idname
        if tree_type == 'ShaderNodeTree':
            self.ensure_shader_dir()
        data        = export_node_group(node_group)
        out_path    = self.node_file_path(node_group.name, tree_type)
        new_content = json.dumps(data, indent=2)

        if os.path.isfile(out_path):
            with open(out_path, 'r', encoding='utf-8') as f:
                if f.read() == new_content:
                    return out_path   # unchanged — skip write

        with open(out_path, 'w', encoding='utf-8') as f:
            f.write(new_content)
        return out_path

    def export_embedded_shader(self, owner, owner_kind: str) -> str | None:
        """
        Export the node tree embedded inside a Material / World / Light
        (owner.node_tree).  owner_kind is 'materials' / 'worlds' / 'lights'
        — used to route the file under nodes/shader/<owner_kind>/.
        Returns the file path written, or None if the owner has no node tree.
        """
        from .serializer import export_node_group
        if not getattr(owner, 'use_nodes', False):
            return None
        nt = getattr(owner, 'node_tree', None)
        if nt is None:
            return None

        self.ensure_nodes_dir()
        os.makedirs(os.path.dirname(
            self.embedded_shader_file_path(owner_kind, owner.name)
        ), exist_ok=True)

        data = export_node_group(nt)
        # Tag the file so the deserializer knows to attach it to a Material/World/Light
        data['owner_type'] = owner_kind
        data['owner_name'] = owner.name

        out_path    = self.embedded_shader_file_path(owner_kind, owner.name)
        new_content = json.dumps(data, indent=2)

        if os.path.isfile(out_path):
            with open(out_path, 'r', encoding='utf-8') as f:
                if f.read() == new_content:
                    return out_path

        with open(out_path, 'w', encoding='utf-8') as f:
            f.write(new_content)
        return out_path

    def export_all_groups(self) -> list:
        """
        Export every tracked node tree in bpy.data to JSON:
          Geometry node groups       → nodes/<name>.json
          Shader node groups         → nodes/shader/<name>.json
          Material shader trees      → nodes/shader/materials/<name>.json
          World shader trees         → nodes/shader/worlds/<name>.json
          Light shader trees         → nodes/shader/lights/<name>.json
        Returns a list of human-readable names that were exported.
        """
        import bpy
        exported = []

        # Standalone node groups (Geometry + Shader)
        for ng in bpy.data.node_groups:
            if ng.type not in TRACKED_TYPES:
                continue
            try:
                self.export_group(ng)
                exported.append(ng.name)
            except Exception as e:
                print(f"[NodeSync] Failed to export '{ng.name}': {e}")

        # Embedded shader trees (Material / World / Light)
        for collection_name, _subdir in EMBEDDED_SHADER_OWNERS:
            collection = getattr(bpy.data, collection_name, None)
            if collection is None:
                continue
            for owner in collection:
                try:
                    if self.export_embedded_shader(owner, collection_name):
                        exported.append(f'{collection_name[:-1]}:{owner.name}')
                except Exception as e:
                    print(f"[NodeSync] Failed to export "
                          f"{collection_name[:-1]} '{owner.name}': {e}")

        return exported

    def import_all_from_disk(self) -> list:
        """
        Read every JSON file under nodes/ (Geometry groups, Shader groups, and
        embedded Material/World/Light shader trees) and reconstruct them in
        bpy.data.  Standalone groups are imported first so that any embedded
        shader tree referencing them resolves correctly.
        Returns list of human-readable names that were successfully imported.
        """
        from .deserializer import reconstruct_node_group, reconstruct_embedded_shader
        if not os.path.isdir(self.nodes_dir):
            return []
        imported = []

        # Standalone node groups first (geometry + shader)
        group_paths = []
        for f in os.listdir(self.nodes_dir):
            if f.endswith('.json'):
                group_paths.append(os.path.join(self.nodes_dir, f))
        if os.path.isdir(self.shader_dir):
            for f in os.listdir(self.shader_dir):
                if f.endswith('.json'):
                    group_paths.append(os.path.join(self.shader_dir, f))

        for path in group_paths:
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                ng = reconstruct_node_group(data, self.root)
                if ng:
                    imported.append(ng.name)
            except Exception as e:
                print(f"[NodeSync] Failed to import '{path}': {e}")

        # Embedded shader trees (materials, worlds, lights)
        for _collection_name, subdir in EMBEDDED_SHADER_OWNERS:
            owner_dir = os.path.join(self.shader_dir, subdir)
            if not os.path.isdir(owner_dir):
                continue
            for f in os.listdir(owner_dir):
                if not f.endswith('.json'):
                    continue
                path = os.path.join(owner_dir, f)
                try:
                    with open(path, 'r', encoding='utf-8') as fh:
                        data = json.load(fh)
                    owner = reconstruct_embedded_shader(data, self.root)
                    if owner is not None:
                        imported.append(f"{data.get('owner_type', '')[:-1]}:{owner.name}")
                except Exception as e:
                    print(f"[NodeSync] Failed to import '{path}': {e}")

        return imported

    def import_specific_from_disk(self, repo_relative_paths: list) -> list:
        """
        Reconstruct only the trees whose JSON files are listed in
        repo_relative_paths (e.g. ['nodes/Foo.json',
        'nodes/shader/materials/Stone.json']).  Routes embedded shader
        trees to the embedded reconstructor based on `owner_type` in the JSON.
        Returns list of successfully imported names.
        """
        from .deserializer import reconstruct_node_group, reconstruct_embedded_shader
        imported = []
        for rel_path in repo_relative_paths:
            abs_path = os.path.join(self.root, rel_path)
            if not os.path.isfile(abs_path):
                continue
            try:
                with open(abs_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                if data.get('owner_type') in {'materials', 'worlds', 'lights'}:
                    owner = reconstruct_embedded_shader(data, self.root)
                    if owner is not None:
                        imported.append(owner.name)
                else:
                    ng = reconstruct_node_group(data, self.root)
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
    # Texture asset tracking (preference-gated; called from commit operator)
    # ------------------------------------------------------------------

    def collect_shader_textures(self) -> list:
        """
        Copy every image used by a Shader Image Texture node — across
        standalone shader groups AND embedded Material/World/Light trees —
        into the textures/ folder.  Packed/generated images are written via
        image.save_render; external images are copied verbatim.
        Returns absolute paths written.
        """
        import bpy
        import shutil

        written = []
        seen    = set()

        def _save_image(img):
            if img is None or img.name in seen:
                return
            seen.add(img.name)

            safe_name = img.name.replace('/', '_').replace('\\', '_')
            if not os.path.splitext(safe_name)[1]:
                safe_name += '.png'

            self.ensure_textures_dir()
            dest = os.path.join(self.textures_dir, safe_name)

            try:
                if img.packed_file is not None or img.source == 'GENERATED':
                    img.save_render(filepath=dest)
                else:
                    src = bpy.path.abspath(img.filepath, library=img.library)
                    if src and os.path.isfile(src):
                        shutil.copy2(src, dest)
                    else:
                        img.save_render(filepath=dest)
                written.append(dest)
            except Exception as e:
                print(f"[NodeSync] Could not save texture '{img.name}': {e}")

        def _walk_tree(nt):
            if nt is None:
                return
            for node in nt.nodes:
                if node.bl_idname == 'ShaderNodeTexImage':
                    _save_image(getattr(node, 'image', None))

        # Standalone shader groups
        for ng in bpy.data.node_groups:
            if ng.type == 'SHADER':
                _walk_tree(ng)

        # Embedded shader trees
        for collection_name, _subdir in EMBEDDED_SHADER_OWNERS:
            collection = getattr(bpy.data, collection_name, None)
            if collection is None:
                continue
            for owner in collection:
                if getattr(owner, 'use_nodes', False):
                    _walk_tree(getattr(owner, 'node_tree', None))

        return written

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
