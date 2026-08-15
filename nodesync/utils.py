"""
Shared helpers for socket type handling and safe attribute access.
"""

import hashlib
import os
import re
import tempfile

import bpy


# ---------------------------------------------------------------------------
# Filesystem-safe names
# ---------------------------------------------------------------------------

# DOS device names that are illegal as a whole file component on Windows,
# regardless of extension (CON.json is still refused).
_WIN_RESERVED = {
    'CON', 'PRN', 'AUX', 'NUL',
    *(f'COM{i}' for i in range(1, 10)),
    *(f'LPT{i}' for i in range(1, 10)),
}

# Path separators, the characters Windows forbids in a filename, and control
# characters.  Blender happily allows all of these in a data-block name.
_ILLEGAL_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

# Separates a cleaned name from its disambiguating hash.  Legal on every
# filesystem we target, and not a shell or git metacharacter.
_HASH_MARKER = '~'

# Prefix for the scratch files used by atomic_write_text().  Anything matching
# this is a crash leftover and is safe to delete.
TEMP_FILE_PREFIX = '.nodesync-tmp-'

# Extensions we recognise as a real image extension.  Anything else — most
# importantly Blender's '.001' duplicate suffix — is treated as part of the
# name so that '.png' still gets appended.
_IMAGE_EXTENSIONS = {
    '.png', '.jpg', '.jpeg', '.jp2', '.j2c', '.bmp', '.tga', '.tif', '.tiff',
    '.exr', '.hdr', '.dds', '.webp', '.psd', '.dpx', '.cin', '.sgi', '.rgb',
    '.rgba', '.iff', '.pdd', '.psb',
}


def _name_hash(name: str) -> str:
    """Short, stable, cross-platform digest of a data-block name."""
    return hashlib.sha1(name.encode('utf-8')).hexdigest()[:8]


def _clean_component(name: str) -> str:
    """
    The cleaning half of safe_filename(), without the disambiguating hash.
    Split out so safe_texture_filename() can clean a name's stem while keeping
    the extension out of the way, and so migrate.py can reuse the exact same
    rules when rescuing a ghost file.
    """
    cleaned = _ILLEGAL_FILENAME_CHARS.sub('_', name)
    cleaned = cleaned.strip().rstrip(' .')
    stem = cleaned.rsplit('.', 1)[0]
    if cleaned.upper() in _WIN_RESERVED or stem.upper() in _WIN_RESERVED:
        cleaned = '_' + cleaned
    return cleaned


def safe_filename(name: str, fallback: str = '_unnamed') -> str:
    """
    Turn an arbitrary Blender data-block name into a single path component that
    is safe to create, look up and delete on Windows, macOS and Linux.

    Blender lets names contain '/', ':', trailing spaces, trailing dots, etc.
    Written to disk verbatim these produce files the OS mangles: most painfully,
    a component ending in a space or a dot becomes an un-addressable "ghost"
    file on Windows that Explorer and `del` cannot touch.  We therefore:
      * replace path separators, reserved characters and control chars with '_'
      * strip leading/trailing whitespace and trailing dots (the ghost-file cause)
      * side-step the reserved DOS device names (CON, PRN, COM1 ...)
      * never return an empty string

    Cleaning is lossy, so two different data-blocks can clean to the same
    string ('A/B' and 'A:B' both give 'A_B') and would then silently overwrite
    each other's JSON.  To prevent that, ANY name that had to be changed gets a
    short hash of its ORIGINAL name appended: 'A/B' -> 'A_B~1a2b3c4d'.  Names
    that need no cleaning are left completely alone, so the common case still
    produces a readable filename.  A name that already contains the marker is
    hashed too, so a literal 'A_B~1a2b3c4d' can never collide with the cleaned
    form of 'A/B'.  The mapping is a pure function of the name, which matters
    because the write path (project.py) and the git-relative path
    (operators/helpers.py) compute it independently, on different machines.

    The real data-block name is stored inside the JSON, so aggressive cleaning
    of the *filename* never affects round-tripping - it only changes the label
    on disk.  Every site that maps a name to a path MUST route through here so
    the written path and the looked-up path always agree.
    """
    cleaned = _clean_component(name) or fallback
    if cleaned != name or _HASH_MARKER in cleaned:
        cleaned = f'{cleaned}{_HASH_MARKER}{_name_hash(name)}'
    return cleaned


def safe_texture_filename(image_name: str) -> str:
    """
    Filesystem-safe name for a texture written under the project's textures/
    directory.  Preserves an existing image extension and defaults to .png when
    the name carries none.  Used by BOTH the exporter (write) and the
    deserializer (read) so the two never disagree on the on-disk path.

    The extension is split off the ORIGINAL name and re-attached at the very
    end.  Doing it any later goes wrong: safe_filename() appends its hash to
    the whole string, which hides the extension from splitext and gets a second
    one appended — 'Wood/Bar.png' came out as 'Wood_Bar.png~<hash>.png', and
    'Wood:Bar.jpg' stranded the real .jpg in the middle of the name.

    Only genuine image extensions count: Blender names duplicates 'Wood.001',
    and splitext happily calls '.001' an extension, which would otherwise
    produce a file Blender could not reliably reload.

    Synthesising an extension is lossy in the same way cleaning is — 'Wood' and
    'Wood.png' both want 'Wood.png' — so the hash is applied whenever the
    result is not character-for-character the image name.
    """
    trimmed = image_name.strip()
    stem, ext = os.path.splitext(trimmed)
    if ext.lower() not in _IMAGE_EXTENSIONS:
        stem, ext = trimmed, '.png'

    safe_stem = _clean_component(stem) or '_texture'
    candidate = safe_stem + ext
    if candidate != image_name or _HASH_MARKER in candidate:
        candidate = f'{safe_stem}{_HASH_MARKER}{_name_hash(image_name)}{ext}'
    return candidate


# ---------------------------------------------------------------------------
# Crash-safe file writing
# ---------------------------------------------------------------------------

def atomic_write_text(path: str, content: str, encoding: str = 'utf-8'):
    """
    Write `content` to `path` without ever leaving a half-written file behind.

    The data goes to a scratch file in the same directory and is then renamed
    over the target, which is atomic on POSIX and on Windows via os.replace.
    If anything fails mid-write the scratch file is removed and any existing
    target is left untouched — previously a write that died partway (disk full,
    Blender crash, permission loss) left a truncated JSON on disk that then
    failed every subsequent import, with no way for the user to tell why.
    """
    directory = os.path.dirname(path) or '.'
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=TEMP_FILE_PREFIX)
    try:
        with os.fdopen(fd, 'w', encoding=encoding) as f:
            f.write(content)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def sweep_temp_files(directory: str):
    """
    Delete scratch files left in `directory` by an interrupted
    atomic_write_text (a hard crash between mkstemp and os.replace).  Without
    this they would accumulate and get picked up by `git add nodes/`.
    """
    try:
        entries = os.listdir(directory)
    except OSError:
        return
    for entry in entries:
        if entry.startswith(TEMP_FILE_PREFIX):
            try:
                os.remove(os.path.join(directory, entry))
            except OSError:
                pass


# Socket types that have no default_value (geometry, data-block links, etc.)
NO_DEFAULT_VALUE_SOCKETS = {
    'NodeSocketGeometry',
    'NodeSocketObject',
    'NodeSocketImage',
    'NodeSocketCollection',
    'NodeSocketMaterial',
    'NodeSocketTexture',
    'NodeSocketShader',
    # Blender 4.x names
    'NodeSocketMenu',
}

# Socket types whose default_value is a mathutils object — must be list()'d
VECTOR_SOCKET_TYPES = {
    'NodeSocketVector',
    'NodeSocketVectorXYZ',
    'NodeSocketVectorTranslation',
    'NodeSocketVectorDirection',
    'NodeSocketVectorEuler',
    'NodeSocketVectorAcceleration',
    'NodeSocketVectorVelocity',
    'NodeSocketVectorOffset',
}

COLOR_SOCKET_TYPES = {
    'NodeSocketColor',
}

ROTATION_SOCKET_TYPES = {
    'NodeSocketRotation',
}


def serialize_default_value(socket):
    """
    Read socket.default_value and return a JSON-safe representation.
    Returns None if the socket type has no default value.
    """
    bl_idname = socket.bl_idname

    if bl_idname in NO_DEFAULT_VALUE_SOCKETS:
        return None

    if not hasattr(socket, 'default_value'):
        return None

    try:
        val = socket.default_value
    except Exception:
        return None

    if bl_idname in VECTOR_SOCKET_TYPES:
        return list(val)

    if bl_idname in COLOR_SOCKET_TYPES:
        return list(val)  # RGBA 4-float

    if bl_idname in ROTATION_SOCKET_TYPES:
        return list(val)  # Euler 3-float

    if bl_idname == 'NodeSocketMatrix':
        try:
            return [list(row) for row in val]
        except Exception:
            return None

    # Scalar, bool, int, string — JSON-safe directly
    if isinstance(val, (int, float, bool, str)):
        return val

    # Fallback: try to convert to a basic type
    try:
        return list(val)
    except Exception:
        return None


def deserialize_default_value(socket_bl_idname, value):
    """
    Convert a stored JSON value back to the correct Python type for assignment
    to socket.default_value. Returns the value ready for setattr.
    """
    if value is None:
        return None

    if socket_bl_idname in VECTOR_SOCKET_TYPES:
        return value  # Blender accepts a list/tuple for vector sockets

    if socket_bl_idname in COLOR_SOCKET_TYPES:
        return value

    if socket_bl_idname in ROTATION_SOCKET_TYPES:
        return value

    return value


# Per-node type: list of attribute names that form its "type_specific" settings.
# Extend this as more node types are needed.
TYPE_SPECIFIC_PROPS = {
    'ShaderNodeMath':                       ['operation', 'use_clamp'],
    'ShaderNodeVectorMath':                 ['operation'],
    'ShaderNodeMixRGB':                     ['blend_type', 'use_clamp'],
    'ShaderNodeMix':                        ['data_type', 'blend_type', 'clamp_factor',
                                             'clamp_result', 'factor_mode'],
    'FunctionNodeCompare':                  ['data_type', 'mode', 'operation'],
    'FunctionNodeBooleanMath':              ['operation'],
    'FunctionNodeFloatToInt':               ['rounding_mode'],
    'FunctionNodeRotateEuler':              ['type', 'space'],
    'FunctionNodeAlignEulerToVector':       ['axis', 'pivot_axis'],
    'GeometryNodeSwitch':                   ['input_type'],
    'GeometryNodeAttributeStatistic':       ['data_type', 'domain'],
    'GeometryNodeStoreNamedAttribute':      ['data_type', 'domain'],
    'GeometryNodeInputNamedAttribute':      ['data_type'],
    'GeometryNodeCaptureAttribute':         ['data_type', 'domain'],
    'GeometryNodeSampleNearestSurface':     ['data_type'],
    'GeometryNodeRaycast':                  ['data_type', 'mapping'],
    'GeometryNodeMeshCircle':               ['fill_type'],
    'GeometryNodeMeshCone':                 ['fill_type'],
    'GeometryNodeMeshCylinder':             ['fill_type'],
    'GeometryNodeCurveToMesh':              [],
    'GeometryNodeSubdivideMesh':            [],
    'GeometryNodeTriangulate':              ['quad_method', 'ngon_method'],
    'GeometryNodeExtrudeMesh':              ['mode'],
    'GeometryNodeMergeByDistance':          ['mode'],
    'GeometryNodeDeleteGeometry':           ['domain', 'mode'],
    'GeometryNodeSeparateGeometry':         ['domain'],
    'GeometryNodeDuplicateElements':        ['domain'],
    'GeometryNodeScaleElements':            ['domain', 'scale_mode'],
    'GeometryNodeFlipFaces':                [],
    'GeometryNodeSplitEdges':               [],
    'GeometryNodeSubdivisionSurface':       ['uv_smooth', 'boundary_smooth'],
    'GeometryNodeSetPosition':              [],
    'GeometryNodeSetCurveRadius':           [],
    'GeometryNodeSetCurveTilt':             [],
    'GeometryNodeResampleCurve':            ['mode'],
    'GeometryNodeFillCurve':                ['mode'],
    'GeometryNodeCurvePrimitiveBezierSegment': ['mode'],
    'GeometryNodeCurvePrimitiveCircle':     ['mode'],
    'GeometryNodeCurvePrimitiveLine':       ['mode'],
    'GeometryNodeCurveStar':                [],
    'GeometryNodeCurveSpiral':              [],
    'GeometryNodeCurveLength':              [],
    'GeometryNodeSplineLength':             [],
    'GeometryNodeSplineParameter':          [],
    'GeometryNodeInstanceOnPoints':         [],
    'GeometryNodeRealizeInstances':         ['legacy_behavior'],
    'GeometryNodeRotateInstances':          [],
    'GeometryNodeScaleInstances':           [],
    'GeometryNodeTranslateInstances':       [],
    'GeometryNodeInputPosition':            [],
    'GeometryNodeInputIndex':               [],
    'GeometryNodeInputNormal':              [],
    'GeometryNodeInputID':                  [],
    'GeometryNodeAccumulateField':          ['data_type', 'domain'],
    'GeometryNodeFieldAtIndex':             ['data_type', 'domain'],
    'GeometryNodeViewer':                   ['data_type', 'domain'],
    'GeometryNodeGroup':                    [],  # node_tree_ref handled separately

    # Shader nodes
    'ShaderNodeBsdfPrincipled':             ['distribution', 'subsurface_method'],
    'ShaderNodeBsdfGlass':                  ['distribution'],
    'ShaderNodeBsdfRefraction':             ['distribution'],
    'ShaderNodeBsdfAnisotropic':            ['distribution'],
    'ShaderNodeBsdfHair':                   ['component'],
    'ShaderNodeSubsurfaceScattering':       ['falloff'],
    'ShaderNodeTexImage':                   ['interpolation', 'projection', 'extension'],
    'ShaderNodeTexEnvironment':             ['interpolation', 'projection'],
    'ShaderNodeTexNoise':                   ['noise_dimensions'],
    'ShaderNodeTexVoronoi':                 ['voronoi_dimensions', 'feature', 'distance'],
    'ShaderNodeTexMusgrave':                ['musgrave_dimensions', 'musgrave_type'],
    'ShaderNodeTexWave':                    ['wave_type', 'bands_direction',
                                             'rings_direction', 'wave_profile'],
    'ShaderNodeTexGradient':                ['gradient_type'],
    'ShaderNodeTexSky':                     ['sky_type'],
    'ShaderNodeMapping':                    ['vector_type'],
    'ShaderNodeNormalMap':                  ['space', 'uv_map'],
    'ShaderNodeBump':                       ['invert'],
    'ShaderNodeTangent':                    ['direction_type', 'axis'],
    'ShaderNodeUVMap':                      ['uv_map', 'from_instancer'],
    'ShaderNodeAttribute':                  ['attribute_name', 'attribute_type'],
    'ShaderNodeSeparateColor':              ['mode'],
    'ShaderNodeCombineColor':               ['mode'],
    'ShaderNodeAmbientOcclusion':           ['inside', 'only_local', 'samples'],
    'ShaderNodeOutputMaterial':             ['target'],
    'ShaderNodeOutputLight':                ['target'],
    'ShaderNodeOutputWorld':                ['target'],
    'ShaderNodeVectorTransform':            ['vector_type', 'convert_from', 'convert_to'],
    'ShaderNodeVertexColor':                ['layer_name'],
    'ShaderNodeDisplacement':               ['space'],
    'ShaderNodeVectorDisplacement':         ['space'],
    'ShaderNodeGroup':                      [],  # node_tree_ref handled separately

    'NodeFrame':                            ['shrink'],
    'NodeReroute':                          [],
}
