"""MCP tool wrappers around the Fusion 360 bridge add-in.

Every function here is a thin call into fusion_client.call(action, **params);
the actual Fusion API work happens in
fusion_addin/FusionReconstructBridge/lib/handlers.py on the other end of the
HTTP bridge. Keep the action name and parameter names in sync between the two
files - they are the wire protocol.

Design choice: holes are not a dedicated Fusion "hole feature". They are built
the same way a person reconstructing a part by hand would: sketch a circle,
then extrude(operation="cut"). That keeps the tool surface small while still
producing a fully parametric, editable result (the circle's diameter and the
cut depth are both ordinary sketch/feature parameters).
"""

from __future__ import annotations

from .fusion_client import call


def fusion_ping() -> dict:
    """Check whether Fusion 360 is running with the bridge add-in started."""
    return call("ping")


def fusion_new_document(name: str | None = None) -> dict:
    """Create a new, empty Fusion design document to reconstruct the part in."""
    return call("new_document", name=name)


def fusion_create_sketch(
    plane: str = "XY",
    offset_mm: float = 0.0,
    origin: list[float] | None = None,
    normal: list[float] | None = None,
    name: str | None = None,
) -> dict:
    """Create a sketch on a plane.

    Either pass `plane` ("XY", "XZ" or "YZ", optionally with `offset_mm` along
    its normal) to sketch on/parallel to a base plane, or pass an explicit
    `origin` + `normal` (both length-3 lists, mm) for an arbitrary plane -
    typically taken straight from mesh_tools.get_cross_section()'s "origin"
    and "normal" fields so the sketch lines up exactly with a mesh
    cross-section.
    """
    return call("create_sketch", plane=plane, offset_mm=offset_mm, origin=origin, normal=normal, name=name)


def fusion_sketch_add_line(sketch_id: str, x1: float, y1: float, x2: float, y2: float) -> dict:
    """Add a straight line segment to a sketch, in the sketch's own mm coordinates."""
    return call("sketch_add_line", sketch_id=sketch_id, x1=x1, y1=y1, x2=x2, y2=y2)


def fusion_sketch_add_rectangle(sketch_id: str, x1: float, y1: float, x2: float, y2: float) -> dict:
    """Add a rectangle to a sketch defined by two opposite corners (mm)."""
    return call("sketch_add_rectangle", sketch_id=sketch_id, x1=x1, y1=y1, x2=x2, y2=y2)


def fusion_sketch_add_circle(sketch_id: str, cx: float, cy: float, radius_mm: float) -> dict:
    """Add a circle to a sketch, center (cx, cy) and radius in mm."""
    return call("sketch_add_circle", sketch_id=sketch_id, cx=cx, cy=cy, radius_mm=radius_mm)


def fusion_sketch_add_arc_three_point(
    sketch_id: str, x1: float, y1: float, x2: float, y2: float, x3: float, y3: float
) -> dict:
    """Add a 3-point arc (start, end, point-on-arc) to a sketch, in mm."""
    return call("sketch_add_arc_three_point", sketch_id=sketch_id, x1=x1, y1=y1, x2=x2, y2=y2, x3=x3, y3=y3)


def fusion_list_sketch_profiles(sketch_id: str) -> dict:
    """List the closed regions (profiles) Fusion has found in a sketch, with
    their index, area and centroid - use this to pick the right
    `profile_index` for extrude()/revolve() when a sketch has more than one
    closed region."""
    return call("list_sketch_profiles", sketch_id=sketch_id)


def fusion_extrude(
    sketch_id: str,
    profile_index: int,
    distance_mm: float,
    operation: str = "new_body",
    target_body_id: str | None = None,
    symmetric: bool = False,
    taper_angle_deg: float = 0.0,
) -> dict:
    """Extrude a sketch profile.

    operation: "new_body" | "join" | "cut" | "intersect". "join"/"cut"/
    "intersect" combine into `target_body_id` (required for those three).
    """
    return call(
        "extrude",
        sketch_id=sketch_id,
        profile_index=profile_index,
        distance_mm=distance_mm,
        operation=operation,
        target_body_id=target_body_id,
        symmetric=symmetric,
        taper_angle_deg=taper_angle_deg,
    )


def fusion_revolve(
    sketch_id: str,
    profile_index: int,
    axis_start: list[float],
    axis_end: list[float],
    angle_deg: float = 360.0,
    operation: str = "new_body",
    target_body_id: str | None = None,
) -> dict:
    """Revolve a sketch profile around an axis line given by two 2D points in
    the sketch's own coordinate system (mm)."""
    return call(
        "revolve",
        sketch_id=sketch_id,
        profile_index=profile_index,
        axis_start=axis_start,
        axis_end=axis_end,
        angle_deg=angle_deg,
        operation=operation,
        target_body_id=target_body_id,
    )


def fusion_add_fillet(body_id: str, edge_selector: dict, radius_mm: float) -> dict:
    """Round edges with a fillet.

    edge_selector: {"kind": "all_edges"} for every edge of the body, or
    {"kind": "near_points", "points": [[x,y,z], ...], "max_distance_mm": 1.0}
    to select edges whose midpoint lies within max_distance_mm of any given
    point (get candidate points from mesh_tools.find_circular_holes/faces or
    fusion_get_body_info).
    """
    return call("add_fillet", body_id=body_id, edge_selector=edge_selector, radius_mm=radius_mm)


def fusion_add_chamfer(body_id: str, edge_selector: dict, distance_mm: float) -> dict:
    """Chamfer edges. Same edge_selector format as fusion_add_fillet."""
    return call("add_chamfer", body_id=body_id, edge_selector=edge_selector, distance_mm=distance_mm)


def fusion_pattern_rectangular(
    feature_id: str,
    quantity_x: int = 1,
    spacing_x_mm: float = 0.0,
    quantity_y: int = 1,
    spacing_y_mm: float = 0.0,
) -> dict:
    """Rectangular pattern of the body/feature produced by feature_id, along
    the body's own X and Y directions."""
    return call(
        "pattern_rectangular",
        feature_id=feature_id,
        quantity_x=quantity_x,
        spacing_x_mm=spacing_x_mm,
        quantity_y=quantity_y,
        spacing_y_mm=spacing_y_mm,
    )


def fusion_pattern_circular(
    feature_id: str,
    axis: str = "z",
    quantity: int = 4,
    total_angle_deg: float = 360.0,
) -> dict:
    """Circular pattern of the body/feature produced by feature_id, around
    the given base-plane axis ("x", "y" or "z")."""
    return call("pattern_circular", feature_id=feature_id, axis=axis, quantity=quantity, total_angle_deg=total_angle_deg)


def fusion_mirror(feature_id: str, plane: str = "YZ") -> dict:
    """Mirror the body/feature produced by feature_id across a base plane
    ("XY", "XZ" or "YZ")."""
    return call("mirror", feature_id=feature_id, plane=plane)


def fusion_combine(target_body_id: str, tool_body_ids: list[str], operation: str = "join", keep_tools: bool = False) -> dict:
    """Boolean-combine bodies: operation "join" | "cut" | "intersect"."""
    return call("combine", target_body_id=target_body_id, tool_body_ids=tool_body_ids, operation=operation, keep_tools=keep_tools)


def fusion_shell(body_id: str, thickness_mm: float, remove_face_indices: list[int] | None = None, direction: str = "inside") -> dict:
    """Hollow out a solid body into a shell. Pass remove_face_indices (from
    fusion_get_body_info's face_index, matched by its normal/point_on_face_mm)
    to leave those faces open - e.g. remove the top face of a box to turn it
    into an open-top container. Omit for a fully closed hollow shell.
    direction: "inside" | "outside" | "both" - which way the wall thickness
    is measured from the original surface."""
    return call(
        "shell", body_id=body_id, remove_face_indices=remove_face_indices, thickness_mm=thickness_mm, direction=direction
    )


def fusion_set_parameter(name: str, expression: str) -> dict:
    """Create (or update) a Fusion user parameter, e.g. name="wall_thickness",
    expression="3 mm". Reference it in later calls' numeric fields is not
    supported over this bridge (those stay plain numbers) - this is for
    keeping the design's parameter table meaningful for a human opening it
    afterwards."""
    return call("set_parameter", name=name, expression=expression)


def fusion_list_parameters() -> dict:
    """List all user parameters currently defined in the design."""
    return call("list_parameters")


def fusion_list_bodies() -> dict:
    """List all solid bodies in the design with their id, name, volume and
    bounding box - use this to get a body_id for combine/fillet/export."""
    return call("list_bodies")


def fusion_get_body_info(body_id: str) -> dict:
    """Detailed geometry of one body: every face (type, area) and every edge
    (type, length, midpoint) - use the edge midpoints to build an
    edge_selector for fusion_add_fillet/fusion_add_chamfer."""
    return call("get_body_info", body_id=body_id)


def fusion_get_timeline() -> dict:
    """List the feature timeline (creation order, name, type, suppressed
    state) - Fusion's own record of every feature created so far."""
    return call("get_timeline")


def fusion_export_stl(body_id: str, file_path: str) -> dict:
    """Export one body to an STL file, e.g. so mesh_tools.compare_meshes()
    can check the reconstruction against the original."""
    return call("export_stl", body_id=body_id, file_path=file_path)


def fusion_screenshot(file_path: str) -> dict:
    """Save a screenshot of the current Fusion viewport to file_path (PNG)."""
    return call("screenshot", file_path=file_path)


def fusion_fit_view() -> dict:
    """Zoom/fit the Fusion viewport to the visible geometry (call before
    fusion_screenshot for a useful picture)."""
    return call("fit_view")
