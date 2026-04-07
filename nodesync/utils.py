"""
Shared helpers for socket type handling and safe attribute access.
"""

import bpy

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
    'NodeFrame':                            ['shrink'],
    'NodeReroute':                          [],
}
