"""Every action the bridge exposes, implemented against the Fusion 360 API.

Runs on Fusion's main thread only (dispatched there by thread_bridge.py).
Every function takes plain-JSON-compatible kwargs and returns a
plain-JSON-compatible dict - these are the exact params/results that cross
the HTTP boundary to the MCP server.

Units: the Fusion API's own length unit is always centimeters, regardless of
the document's display units. Every function here accepts/returns
millimeters (matching STL/3D-printing convention) and converts at the
boundary - see _mm_to_cm / _cm_to_mm. Distances/angles that become
*parametric* feature inputs (extrude distance, fillet radius, pattern
spacing...) are passed to Fusion as ValueInput.createByString("<n> mm"/"deg")
instead of raw cm floats, so they show up as ordinary, editable expressions
in the timeline - not the point-geometry calls (sketch lines/circles/points),
which take raw cm floats because they are not parametric dimensions.

Bodies/sketches/features are identified across HTTP calls by Fusion's own
`entityToken` (a stable string id for any design entity, resolvable back to
the live object via Design.findEntityByToken) - there is no separate id
registry to keep in sync or that can go stale across an undo.
"""

import math

import adsk.core
import adsk.fusion

MM_PER_CM = 10.0


def _v_sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _v_add(a, b):
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _v_scale(a, s):
    return (a[0] * s, a[1] * s, a[2] * s)


def _v_cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _v_norm(a):
    length = math.sqrt(a[0] ** 2 + a[1] ** 2 + a[2] ** 2)
    if length < 1e-12:
        raise ValueError("zero-length vector")
    return (a[0] / length, a[1] / length, a[2] / length)


def _mm_to_cm(value_mm: float) -> float:
    return value_mm / MM_PER_CM


def _cm_to_mm(value_cm: float) -> float:
    return value_cm * MM_PER_CM


def _point_mm(x_mm: float, y_mm: float, z_mm: float = 0.0) -> adsk.core.Point3D:
    return adsk.core.Point3D.create(_mm_to_cm(x_mm), _mm_to_cm(y_mm), _mm_to_cm(z_mm))


def _app() -> adsk.core.Application:
    return adsk.core.Application.get()


def _design() -> adsk.fusion.Design:
    design = adsk.fusion.Design.cast(_app().activeProduct)
    if design is None:
        raise RuntimeError("No active Fusion design. Call fusion_new_document first (or open a design in Fusion).")
    return design


def _root() -> adsk.fusion.Component:
    return _design().rootComponent


def _resolve(token: str):
    ents = _design().findEntityByToken(token)
    if not ents:
        raise ValueError(f"Entity not found for token (deleted, or wrong document active?): {token}")
    return ents[0]


def _resolve_sketch(sketch_id: str) -> adsk.fusion.Sketch:
    ent = _resolve(sketch_id)
    sketch = adsk.fusion.Sketch.cast(ent)
    if sketch is None:
        raise ValueError(f"Entity {sketch_id} is not a sketch")
    return sketch


def _resolve_body(body_id: str) -> adsk.fusion.BRepBody:
    ent = _resolve(body_id)
    body = adsk.fusion.BRepBody.cast(ent)
    if body is None:
        raise ValueError(f"Entity {body_id} is not a solid body")
    return body


def _op_enum(operation: str):
    mapping = {
        "new_body": adsk.fusion.FeatureOperations.NewBodyFeatureOperation,
        "join": adsk.fusion.FeatureOperations.JoinFeatureOperation,
        "cut": adsk.fusion.FeatureOperations.CutFeatureOperation,
        "intersect": adsk.fusion.FeatureOperations.IntersectFeatureOperation,
    }
    if operation not in mapping:
        raise ValueError(f"operation must be one of {sorted(mapping)}, got {operation!r}")
    return mapping[operation]


def _base_plane(name: str) -> adsk.fusion.ConstructionPlane:
    root = _root()
    mapping = {"XY": root.xYConstructionPlane, "XZ": root.xZConstructionPlane, "YZ": root.yZConstructionPlane}
    if name not in mapping:
        raise ValueError(f"plane must be one of {sorted(mapping)}, got {name!r}")
    return mapping[name]


def _axis(name: str) -> adsk.fusion.ConstructionAxis:
    root = _root()
    mapping = {"x": root.xConstructionAxis, "y": root.yConstructionAxis, "z": root.zConstructionAxis}
    if name not in mapping:
        raise ValueError(f"axis must be one of {sorted(mapping)}, got {name!r}")
    return mapping[name]


def _body_summary(body: adsk.fusion.BRepBody) -> dict:
    bbox = body.boundingBox
    return {
        "body_id": body.entityToken,
        "name": body.name,
        "volume_mm3": body.volume * (MM_PER_CM**3),
        "is_visible": body.isVisible,
        "bounding_box_mm": {
            "min": [_cm_to_mm(bbox.minPoint.x), _cm_to_mm(bbox.minPoint.y), _cm_to_mm(bbox.minPoint.z)],
            "max": [_cm_to_mm(bbox.maxPoint.x), _cm_to_mm(bbox.maxPoint.y), _cm_to_mm(bbox.maxPoint.z)],
        },
    }


def _edge_midpoint_mm(edge: adsk.fusion.BRepEdge) -> list[float]:
    p1 = edge.startVertex.geometry
    p2 = edge.endVertex.geometry
    return [_cm_to_mm((p1.x + p2.x) / 2), _cm_to_mm((p1.y + p2.y) / 2), _cm_to_mm((p1.z + p2.z) / 2)]


def _select_edges(body: adsk.fusion.BRepBody, edge_selector: dict) -> adsk.core.ObjectCollection:
    kind = (edge_selector or {}).get("kind", "all_edges")
    edges = adsk.core.ObjectCollection.create()

    if kind == "all_edges":
        for edge in body.edges:
            edges.add(edge)
        return edges

    if kind == "near_points":
        points_mm = edge_selector["points"]
        max_d = edge_selector.get("max_distance_mm", 1.0)
        for edge in body.edges:
            mid = _edge_midpoint_mm(edge)
            for px, py, pz in points_mm:
                d = ((mid[0] - px) ** 2 + (mid[1] - py) ** 2 + (mid[2] - pz) ** 2) ** 0.5
                if d <= max_d:
                    edges.add(edge)
                    break
        return edges

    raise ValueError(f"edge_selector.kind must be 'all_edges' or 'near_points', got {kind!r}")


# --------------------------------------------------------------------------
# Actions (registered in ACTIONS at the bottom of this file)
# --------------------------------------------------------------------------


def ping() -> dict:
    app = _app()
    design = adsk.fusion.Design.cast(app.activeProduct)
    return {
        "status": "ok",
        "fusion_version": app.version,
        "active_document": app.activeDocument.name if app.activeDocument else None,
        "has_active_design": design is not None,
    }


def new_document(name: str = None) -> dict:
    doc = _app().documents.add(adsk.core.DocumentTypes.FusionDesignDocumentType)
    if name:
        try:
            doc.name = name
        except Exception:
            pass  # Fusion may refuse to rename an unsaved document; not fatal
    return {"document_name": doc.name}


def create_sketch(
    plane: str = "XY",
    offset_mm: float = 0.0,
    origin: list = None,
    normal: list = None,
    name: str = None,
) -> dict:
    root = _root()
    planes = root.constructionPlanes

    if origin is not None and normal is not None:
        # Build an arbitrary plane from an origin point + normal via three
        # points (Fusion has no direct "point + normal" plane constructor).
        # This basis convention (ref axis, u = n x ref, v = n x u) matches
        # mesh_tools._plane_basis() on the MCP-server side, so a plane built
        # from get_cross_section()'s origin/normal lines up the same way.
        o = tuple(origin)
        n = _v_norm(tuple(normal))
        ref = (1.0, 0.0, 0.0) if abs(n[0]) < 0.9 else (0.0, 1.0, 0.0)
        u = _v_norm(_v_cross(n, ref))
        v = _v_cross(n, u)
        p1 = o
        p2 = _v_add(o, _v_scale(u, 10.0))
        p3 = _v_add(o, _v_scale(v, 10.0))
        plane_input = planes.createInput()
        plane_input.setByThreePoints(_point_mm(*p1), _point_mm(*p2), _point_mm(*p3))
        construction_plane = planes.add(plane_input)
        sketch = root.sketches.add(construction_plane)
    elif offset_mm:
        base = _base_plane(plane)
        plane_input = planes.createInput()
        plane_input.setByOffset(base, adsk.core.ValueInput.createByString(f"{offset_mm} mm"))
        construction_plane = planes.add(plane_input)
        sketch = root.sketches.add(construction_plane)
    else:
        sketch = root.sketches.add(_base_plane(plane))

    if name:
        sketch.name = name

    return {"sketch_id": sketch.entityToken, "name": sketch.name}


def sketch_add_line(sketch_id: str, x1: float, y1: float, x2: float, y2: float) -> dict:
    sketch = _resolve_sketch(sketch_id)
    line = sketch.sketchCurves.sketchLines.addByTwoPoints(_point_mm(x1, y1), _point_mm(x2, y2))
    return {"curve_id": line.entityToken}


def sketch_add_rectangle(sketch_id: str, x1: float, y1: float, x2: float, y2: float) -> dict:
    sketch = _resolve_sketch(sketch_id)
    lines = sketch.sketchCurves.sketchLines.addTwoPointRectangle(_point_mm(x1, y1), _point_mm(x2, y2))
    return {"curve_ids": [line.entityToken for line in lines]}


def sketch_add_circle(sketch_id: str, cx: float, cy: float, radius_mm: float) -> dict:
    sketch = _resolve_sketch(sketch_id)
    circle = sketch.sketchCurves.sketchCircles.addByCenterRadius(_point_mm(cx, cy), _mm_to_cm(radius_mm))
    return {"curve_id": circle.entityToken}


def sketch_add_arc_three_point(
    sketch_id: str, x1: float, y1: float, x2: float, y2: float, x3: float, y3: float
) -> dict:
    """x1,y1 = start; x2,y2 = end; x3,y3 = a point on the arc between them."""
    sketch = _resolve_sketch(sketch_id)
    arc = sketch.sketchCurves.sketchArcs.addByThreePoints(_point_mm(x1, y1), _point_mm(x3, y3), _point_mm(x2, y2))
    return {"curve_id": arc.entityToken}


def list_sketch_profiles(sketch_id: str) -> dict:
    sketch = _resolve_sketch(sketch_id)
    profiles = []
    for i in range(sketch.profiles.count):
        profile = sketch.profiles.item(i)
        props = profile.areaProperties()
        profiles.append(
            {
                "profile_index": i,
                "area_mm2": props.area * (MM_PER_CM**2),
                "centroid_mm": [_cm_to_mm(props.centroid.x), _cm_to_mm(props.centroid.y)],
            }
        )
    return {"sketch_id": sketch_id, "profiles": profiles}


def extrude(
    sketch_id: str,
    profile_index: int,
    distance_mm: float,
    operation: str = "new_body",
    target_body_id: str = None,
    symmetric: bool = False,
    taper_angle_deg: float = 0.0,
) -> dict:
    sketch = _resolve_sketch(sketch_id)
    if profile_index < 0 or profile_index >= sketch.profiles.count:
        raise ValueError(f"sketch {sketch_id} has {sketch.profiles.count} profile(s), no index {profile_index}")
    profile = sketch.profiles.item(profile_index)

    extrudes = _root().features.extrudeFeatures
    ext_input = extrudes.createInput(profile, _op_enum(operation))
    if operation != "new_body":
        if not target_body_id:
            raise ValueError(f"operation={operation!r} requires target_body_id")
        # participantBodies binds to a std::vector, not an ObjectCollection -
        # a plain Python list is required here.
        ext_input.participantBodies = [_resolve_body(target_body_id)]
    if taper_angle_deg:
        ext_input.taperAngle = adsk.core.ValueInput.createByString(f"{taper_angle_deg} deg")
    ext_input.setDistanceExtent(symmetric, adsk.core.ValueInput.createByString(f"{distance_mm} mm"))

    feature = extrudes.add(ext_input)
    body = feature.bodies.item(0) if feature.bodies.count else None
    return {
        "feature_id": feature.entityToken,
        "body_id": body.entityToken if body else target_body_id,
    }


def revolve(
    sketch_id: str,
    profile_index: int,
    axis_start: list,
    axis_end: list,
    angle_deg: float = 360.0,
    operation: str = "new_body",
    target_body_id: str = None,
) -> dict:
    sketch = _resolve_sketch(sketch_id)

    # Add the axis line *before* looking up the profile: adding any new curve
    # to a sketch makes Fusion recompute its profiles collection, which
    # invalidates a Profile object obtained beforehand ("invalid profile(s)
    # for Revolve Feature"). profile_index still refers to the same region
    # afterwards, since a construction line doesn't add a new bounded region.
    axis_line = sketch.sketchCurves.sketchLines.addByTwoPoints(
        _point_mm(axis_start[0], axis_start[1]), _point_mm(axis_end[0], axis_end[1])
    )
    axis_line.isConstruction = True

    if profile_index < 0 or profile_index >= sketch.profiles.count:
        raise ValueError(f"sketch {sketch_id} has {sketch.profiles.count} profile(s), no index {profile_index}")
    profile = sketch.profiles.item(profile_index)

    revolves = _root().features.revolveFeatures
    rev_input = revolves.createInput(profile, axis_line, _op_enum(operation))
    if operation != "new_body":
        if not target_body_id:
            raise ValueError(f"operation={operation!r} requires target_body_id")
        rev_input.participantBodies = [_resolve_body(target_body_id)]
    rev_input.setAngleExtent(False, adsk.core.ValueInput.createByString(f"{angle_deg} deg"))

    feature = revolves.add(rev_input)
    body = feature.bodies.item(0) if feature.bodies.count else None
    return {
        "feature_id": feature.entityToken,
        "body_id": body.entityToken if body else target_body_id,
    }


def add_fillet(body_id: str, edge_selector: dict, radius_mm: float) -> dict:
    body = _resolve_body(body_id)
    edges = _select_edges(body, edge_selector)
    if edges.count == 0:
        raise ValueError("edge_selector matched no edges")

    fillets = _root().features.filletFeatures
    fillet_input = fillets.createInput()
    fillet_input.edgeSetInputs.addConstantRadiusEdgeSet(edges, adsk.core.ValueInput.createByString(f"{radius_mm} mm"), True)
    feature = fillets.add(fillet_input)
    return {"feature_id": feature.entityToken, "edges_affected": edges.count}


def add_chamfer(body_id: str, edge_selector: dict, distance_mm: float) -> dict:
    body = _resolve_body(body_id)
    edges = _select_edges(body, edge_selector)
    if edges.count == 0:
        raise ValueError("edge_selector matched no edges")

    chamfers = _root().features.chamferFeatures
    chamfer_input = chamfers.createInput(edges, True)
    chamfer_input.setToEqualDistance(adsk.core.ValueInput.createByString(f"{distance_mm} mm"))
    feature = chamfers.add(chamfer_input)
    return {"feature_id": feature.entityToken, "edges_affected": edges.count}


def pattern_rectangular(
    feature_id: str, quantity_x: int = 1, spacing_x_mm: float = 0.0, quantity_y: int = 1, spacing_y_mm: float = 0.0
) -> dict:
    root = _root()
    entities = adsk.core.ObjectCollection.create()
    entities.add(_resolve(feature_id))

    patterns = root.features.rectangularPatternFeatures
    pat_input = patterns.createInput(
        entities,
        root.xConstructionAxis,
        adsk.core.ValueInput.createByReal(quantity_x),
        adsk.core.ValueInput.createByString(f"{spacing_x_mm} mm"),
        adsk.fusion.PatternDistanceType.SpacingPatternDistanceType,
    )
    if quantity_y > 1:
        pat_input.directionTwoEntity = root.yConstructionAxis
        pat_input.quantityTwo = adsk.core.ValueInput.createByReal(quantity_y)
        pat_input.distanceTwo = adsk.core.ValueInput.createByString(f"{spacing_y_mm} mm")

    feature = patterns.add(pat_input)
    return {"feature_id": feature.entityToken}


def pattern_circular(feature_id: str, axis: str = "z", quantity: int = 4, total_angle_deg: float = 360.0) -> dict:
    root = _root()
    entities = adsk.core.ObjectCollection.create()
    entities.add(_resolve(feature_id))

    patterns = root.features.circularPatternFeatures
    pat_input = patterns.createInput(entities, _axis(axis))
    pat_input.quantity = adsk.core.ValueInput.createByReal(quantity)
    pat_input.totalAngle = adsk.core.ValueInput.createByString(f"{total_angle_deg} deg")
    pat_input.isSymmetric = False

    feature = patterns.add(pat_input)
    return {"feature_id": feature.entityToken}


def mirror(feature_id: str, plane: str = "YZ") -> dict:
    root = _root()
    entities = adsk.core.ObjectCollection.create()
    entities.add(_resolve(feature_id))

    mirrors = root.features.mirrorFeatures
    mirror_input = mirrors.createInput(entities, _base_plane(plane))
    feature = mirrors.add(mirror_input)
    return {"feature_id": feature.entityToken}


def combine(target_body_id: str, tool_body_ids: list, operation: str = "join", keep_tools: bool = False) -> dict:
    root = _root()
    target = _resolve_body(target_body_id)
    tools = adsk.core.ObjectCollection.create()
    for tool_id in tool_body_ids:
        tools.add(_resolve_body(tool_id))

    combines = root.features.combineFeatures
    combine_input = combines.createInput(target, tools)
    combine_input.operation = _op_enum(operation if operation != "new_body" else "join")
    combine_input.isKeepToolBodies = keep_tools
    feature = combines.add(combine_input)
    return {"feature_id": feature.entityToken, "body_id": target.entityToken}


def set_parameter(name: str, expression: str) -> dict:
    params = _design().userParameters
    param = params.itemByName(name)
    if param is None:
        param = params.add(name, adsk.core.ValueInput.createByReal(0), "mm", "")
    param.expression = expression
    return {"name": param.name, "expression": param.expression, "value_mm": _cm_to_mm(param.value)}


def list_parameters() -> dict:
    params = _design().userParameters
    return {
        "parameters": [
            {"name": p.name, "expression": p.expression, "value_mm": _cm_to_mm(p.value), "comment": p.comment}
            for p in params
        ]
    }


def list_bodies() -> dict:
    return {"bodies": [_body_summary(b) for b in _root().bRepBodies]}


def get_body_info(body_id: str) -> dict:
    body = _resolve_body(body_id)
    faces = []
    for i in range(body.faces.count):
        face = body.faces.item(i)
        faces.append({"face_index": i, "area_mm2": face.area * (MM_PER_CM**2)})

    edges = []
    for i in range(body.edges.count):
        edge = body.edges.item(i)
        edges.append(
            {
                "edge_index": i,
                "edge_id": edge.entityToken,
                "length_mm": _cm_to_mm(edge.length),
                "midpoint_mm": _edge_midpoint_mm(edge),
            }
        )

    summary = _body_summary(body)
    summary["faces"] = faces
    summary["edges"] = edges
    return summary


def get_timeline() -> dict:
    timeline = _design().timeline
    items = []
    for i in range(timeline.count):
        item = timeline.item(i)
        items.append({"index": i, "name": item.name, "is_suppressed": item.isSuppressed})
    return {"timeline": items}


def export_stl(body_id: str, file_path: str) -> dict:
    body = _resolve_body(body_id)
    export_mgr = _design().exportManager
    options = export_mgr.createSTLExportOptions(body, file_path)
    options.meshRefinement = adsk.fusion.MeshRefinementSettings.MeshRefinementMedium
    export_mgr.execute(options)
    return {"file_path": file_path}


def screenshot(file_path: str) -> dict:
    ok = _app().activeViewport.saveAsImageFile(file_path, 1000, 1000)
    return {"file_path": file_path, "ok": bool(ok)}


def fit_view() -> dict:
    _app().activeViewport.fit()
    return {"ok": True}


ACTIONS = {
    "ping": ping,
    "new_document": new_document,
    "create_sketch": create_sketch,
    "sketch_add_line": sketch_add_line,
    "sketch_add_rectangle": sketch_add_rectangle,
    "sketch_add_circle": sketch_add_circle,
    "sketch_add_arc_three_point": sketch_add_arc_three_point,
    "list_sketch_profiles": list_sketch_profiles,
    "extrude": extrude,
    "revolve": revolve,
    "add_fillet": add_fillet,
    "add_chamfer": add_chamfer,
    "pattern_rectangular": pattern_rectangular,
    "pattern_circular": pattern_circular,
    "mirror": mirror,
    "combine": combine,
    "set_parameter": set_parameter,
    "list_parameters": list_parameters,
    "list_bodies": list_bodies,
    "get_body_info": get_body_info,
    "get_timeline": get_timeline,
    "export_stl": export_stl,
    "screenshot": screenshot,
    "fit_view": fit_view,
}
