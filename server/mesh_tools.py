"""STL / 3MF mesh analysis.

These functions never touch Fusion 360 - they only read a mesh file and turn
it into numbers and shapes an LLM can reason about (bounding box, cross-section
profiles, candidate holes/bosses, orthographic renders). The intended usage
pattern (see docs/RECONSTRUCTION_STRATEGY.md) is:

    1. mesh_summary()            - get overall size / units sanity check
    2. render_orthographic_views - look at the part
    3. find_circular_holes / find_circular_faces - locate holes, bosses, pads
    4. get_cross_section()       - get the exact 2D profile to sketch, on any plane
    5. drive the fusion_* tools to rebuild it feature by feature
    6. compare_meshes() against the reconstructed export to check the result

All STL files are unitless; we assume millimeters throughout (Fusion 360's
default), which matches the overwhelming majority of 3D-printing STL/3MF
sources. If a mesh's bounding box comes back absurdly large or tiny, that is
usually a sign the source file used a different unit.
"""

from __future__ import annotations

import os
import uuid
from typing import Any

import numpy as np
import trimesh

from . import config


def _to_native(obj: Any) -> Any:
    """Recursively convert numpy scalars/arrays to plain Python/JSON types."""
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, dict):
        return {k: _to_native(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_native(v) for v in obj]
    return obj


def _load_mesh(file_path: str) -> trimesh.Trimesh:
    if not os.path.isfile(file_path):
        raise FileNotFoundError(f"No such mesh file: {file_path}")

    loaded = trimesh.load(file_path, force="mesh")

    if isinstance(loaded, trimesh.Scene):
        if len(loaded.geometry) == 0:
            raise ValueError(f"{file_path} contains no geometry")
        loaded = trimesh.util.concatenate(
            [g for g in loaded.geometry.values() if isinstance(g, trimesh.Trimesh)]
        )

    if not isinstance(loaded, trimesh.Trimesh):
        raise ValueError(f"{file_path} did not load as a triangle mesh")

    return loaded


def _plane_basis(normal: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Return two unit vectors u, v spanning the plane perpendicular to normal."""
    n = normal / np.linalg.norm(normal)
    ref = np.array([1.0, 0.0, 0.0]) if abs(n[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
    u = np.cross(n, ref)
    u /= np.linalg.norm(u)
    v = np.cross(n, u)
    return u, v


def _fit_circle_2d(points: np.ndarray) -> dict:
    """Algebraic (Kasa) least-squares circle fit. Returns center, radius, and a
    circularity_error (stdev of point-to-center distance / radius - 0 is a
    perfect circle, above ~0.03 it is probably not a circle)."""
    x = points[:, 0]
    y = points[:, 1]
    A = np.column_stack([2 * x, 2 * y, np.ones_like(x)])
    b = x**2 + y**2
    sol, *_ = np.linalg.lstsq(A, b, rcond=None)
    cx, cy, c = sol
    r_sq = c + cx**2 + cy**2
    if r_sq <= 0:
        return {"center": [cx, cy], "radius": 0.0, "circularity_error": 1.0}
    r = float(np.sqrt(r_sq))
    dists = np.sqrt((x - cx) ** 2 + (y - cy) ** 2)
    circularity_error = float(np.std(dists) / r) if r > 1e-9 else 1.0
    return {"center": [float(cx), float(cy)], "radius": r, "circularity_error": circularity_error}


def mesh_summary(file_path: str) -> dict:
    """Overall size, volume and sanity-check info for an STL/3MF file."""
    mesh = _load_mesh(file_path)
    bbox_min, bbox_max = mesh.bounds
    size = bbox_max - bbox_min
    return _to_native(
        {
            "file": file_path,
            "assumed_units": "mm",
            "bounding_box": {
                "min": bbox_min,
                "max": bbox_max,
                "size_x": size[0],
                "size_y": size[1],
                "size_z": size[2],
            },
            "volume": mesh.volume if mesh.is_watertight else None,
            "surface_area": mesh.area,
            "center_of_mass": mesh.center_mass if mesh.is_watertight else mesh.centroid,
            "is_watertight": mesh.is_watertight,
            "euler_number": mesh.euler_number,
            "num_vertices": len(mesh.vertices),
            "num_faces": len(mesh.faces),
            "num_planar_facets": len(mesh.facets),
            "symmetry": {
                "x_extent_over_y": float(size[0] / size[1]) if size[1] > 1e-9 else None,
            },
            "warning": None
            if mesh.is_watertight
            else "Mesh is not watertight (has holes/gaps in the surface) - "
            "volume is unavailable and boolean operations in Fusion may need repair first.",
        }
    )


def list_planar_facets(file_path: str, min_area: float = 1.0) -> list[dict]:
    """List coplanar face groups (flat regions) large enough to matter, each
    with its normal, area and in-plane footprint size - useful for spotting
    the flat faces that become sketch planes (top/bottom/side walls, bosses,
    counterbore floors)."""
    mesh = _load_mesh(file_path)
    results = []
    for i, facet in enumerate(mesh.facets):
        area = float(mesh.facets_area[i])
        if area < min_area:
            continue
        normal = mesh.facets_normal[i]
        face_verts = mesh.vertices[np.unique(mesh.faces[facet])]
        centroid = face_verts.mean(axis=0)
        u, v = _plane_basis(normal)
        proj = np.column_stack([(face_verts - centroid) @ u, (face_verts - centroid) @ v])
        extent = proj.max(axis=0) - proj.min(axis=0)
        results.append(
            {
                "facet_id": i,
                "num_faces": int(len(facet)),
                "area": area,
                "normal": normal,
                "centroid": centroid,
                "in_plane_extent_u": float(extent[0]),
                "in_plane_extent_v": float(extent[1]),
            }
        )
    results.sort(key=lambda d: -d["area"])
    return _to_native(results)


def find_circular_holes(
    file_path: str, min_radius: float = 0.3, max_circularity_error: float = 0.04, min_loop_points: int = 8
) -> list[dict]:
    """Detect circular through-holes / blind-hole rims sitting inside a flat
    facet (e.g. a bolt hole in a plate). Each result is one inner boundary
    loop of a facet that fits a circle well.

    min_loop_points guards against a false positive that is easy to fall
    into: any rectangle's 4 corners lie exactly on a circle (a rectangle is a
    cyclic quadrilateral), so a plain 4-sided quad facet can look like a
    perfect circle fit. Real circular boundaries coming from a tessellated
    mesh have one segment per tessellation facet (a few dozen, typically),
    so requiring at least min_loop_points boundary vertices filters out
    straight-edged quads/triangles while keeping genuine circles.
    """
    mesh = _load_mesh(file_path)
    found = []
    for i, facet in enumerate(mesh.facets):
        normal = mesh.facets_normal[i]
        try:
            path3d = mesh.outline(facet)
        except Exception:
            continue
        loops = path3d.discrete
        if len(loops) < 2:
            continue  # need an outer loop + at least one inner (hole) loop

        u, v = _plane_basis(normal)
        loop_info = []
        for loop in loops:
            pts2d = np.column_stack([loop @ u, loop @ v])
            area = float(0.5 * abs(np.sum(pts2d[:-1, 0] * pts2d[1:, 1] - pts2d[1:, 0] * pts2d[:-1, 1])))
            loop_info.append((area, loop, pts2d))
        loop_info.sort(key=lambda t: -t[0])
        outer_area = loop_info[0][0]

        for area, loop, pts2d in loop_info[1:]:
            if area < 1e-6 or area / outer_area > 0.9 or len(loop) < min_loop_points:
                continue
            fit = _fit_circle_2d(pts2d)
            if fit["radius"] < min_radius or fit["circularity_error"] > max_circularity_error:
                continue
            center_2d = np.array(fit["center"])
            centroid_3d = loop.mean(axis=0)
            center_3d = centroid_3d + (center_2d[0] - (pts2d[:, 0]).mean()) * u + (
                center_2d[1] - (pts2d[:, 1]).mean()
            ) * v
            found.append(
                {
                    "type": "circular_hole",
                    "host_facet_id": i,
                    "center": center_3d,
                    "radius": fit["radius"],
                    "diameter": fit["radius"] * 2,
                    "normal": normal,
                    "circularity_error": fit["circularity_error"],
                }
            )
    return _to_native(found)


def find_circular_faces(
    file_path: str, min_radius: float = 0.3, max_circularity_error: float = 0.04, min_loop_points: int = 8
) -> list[dict]:
    """Detect facets whose *entire* boundary is itself a circle - typically the
    flat top of a cylindrical boss/pad, or the flat bottom of a blind hole.

    See find_circular_holes' docstring for why min_loop_points matters: a
    plain quad's corners always lie on some circle, so a low point-count
    "circle" is almost always a false positive from mesh tessellation, not a
    real curved feature.
    """
    mesh = _load_mesh(file_path)
    found = []
    for i, facet in enumerate(mesh.facets):
        normal = mesh.facets_normal[i]
        try:
            path3d = mesh.outline(facet)
        except Exception:
            continue
        loops = path3d.discrete
        if len(loops) != 1 or len(loops[0]) < min_loop_points:
            continue
        loop = loops[0]
        u, v = _plane_basis(normal)
        pts2d = np.column_stack([loop @ u, loop @ v])
        fit = _fit_circle_2d(pts2d)
        if fit["radius"] < min_radius or fit["circularity_error"] > max_circularity_error:
            continue
        found.append(
            {
                "type": "circular_face",
                "facet_id": i,
                "center": loop.mean(axis=0),
                "radius": fit["radius"],
                "diameter": fit["radius"] * 2,
                "normal": normal,
                "area": float(mesh.facets_area[i]),
                "circularity_error": fit["circularity_error"],
            }
        )
    return _to_native(found)


def get_cross_section(file_path: str, plane_origin: list[float], plane_normal: list[float]) -> dict:
    """Slice the mesh with a plane and return the resulting 2D profile(s) -
    exactly what you need to know to draw the matching Fusion sketch on that
    plane. Each polygon has an outer loop and zero or more hole loops, given
    as 2D points in the plane's own (u, v) coordinate system, plus the 3x3
    rotation + origin needed to place that plane in 3D (matches Fusion's
    "construction plane from point + normal" convention)."""
    mesh = _load_mesh(file_path)
    origin = np.array(plane_origin, dtype=float)
    normal = np.array(plane_normal, dtype=float)
    normal /= np.linalg.norm(normal)

    section = mesh.section(plane_origin=origin, plane_normal=normal)
    if section is None:
        return _to_native({"origin": origin, "normal": normal, "polygons": [], "note": "Plane does not intersect the mesh."})

    planar, transform = section.to_planar()
    u, v = _plane_basis(normal)

    polygons = []
    for poly in planar.polygons_full:
        polygons.append(
            {
                "area": float(poly.area),
                "outer": np.array(poly.exterior.coords),
                "holes": [np.array(ring.coords) for ring in poly.interiors],
            }
        )

    return _to_native(
        {
            "origin": origin,
            "normal": normal,
            "plane_u_axis": u,
            "plane_v_axis": v,
            "num_polygons": len(polygons),
            "polygons": polygons,
        }
    )


def render_orthographic_views(file_path: str, out_dir: str | None = None) -> dict:
    """Render front/top/right/isometric silhouette views to PNG files so a
    vision-capable LLM can look at the part's overall shape before deciding
    how to reconstruct it. Returns paths, not image bytes - open them with
    a file-reading / vision tool."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from mpl_toolkits.mplot3d.art3d import Poly3DCollection

    mesh = _load_mesh(file_path)
    out_dir = out_dir or os.path.join(config.SCRATCH_DIR, f"views_{uuid.uuid4().hex[:8]}")
    os.makedirs(out_dir, exist_ok=True)

    views = {
        "front": (0, -90),
        "top": (90, -90),
        "right": (0, 0),
        "iso": (25, -135),
    }
    bbox_min, bbox_max = mesh.bounds
    center = (bbox_min + bbox_max) / 2
    radius = float(np.linalg.norm(bbox_max - bbox_min)) / 2 or 1.0

    paths = {}
    for name, (elev, azim) in views.items():
        fig = plt.figure(figsize=(5, 5), dpi=150)
        ax = fig.add_subplot(111, projection="3d")
        collection = Poly3DCollection(mesh.triangles, facecolor="#c9c9c9", edgecolor="#404040", linewidths=0.15)
        ax.add_collection3d(collection)
        ax.set_xlim(center[0] - radius, center[0] + radius)
        ax.set_ylim(center[1] - radius, center[1] + radius)
        ax.set_zlim(center[2] - radius, center[2] + radius)
        ax.view_init(elev=elev, azim=azim)
        ax.set_box_aspect((1, 1, 1))
        ax.set_axis_off()
        out_path = os.path.join(out_dir, f"{name}.png")
        fig.savefig(out_path, bbox_inches="tight", pad_inches=0.1)
        plt.close(fig)
        paths[name] = out_path

    return {"out_dir": out_dir, "views": paths}


def compare_meshes(original_path: str, candidate_path: str, sample_count: int = 5000) -> dict:
    """Compare a reconstructed model (exported from Fusion as STL) against the
    original mesh: volume/bounding-box deltas plus an approximate two-sided
    surface distance (mean and max, in mm) computed by sampling points on one
    surface and measuring distance to the nearest point on the other."""
    original = _load_mesh(original_path)
    candidate = _load_mesh(candidate_path)

    o_min, o_max = original.bounds
    c_min, c_max = candidate.bounds
    bbox_delta = (c_max - c_min) - (o_max - o_min)

    volume_delta_pct = None
    if original.is_watertight and candidate.is_watertight and original.volume > 1e-9:
        volume_delta_pct = float((candidate.volume - original.volume) / original.volume * 100)

    def _one_sided(src: trimesh.Trimesh, dst: trimesh.Trimesh) -> dict:
        points, _ = trimesh.sample.sample_surface(src, sample_count)
        _, distances, _ = dst.nearest.on_surface(points)
        return {"mean": float(np.mean(distances)), "max": float(np.max(distances)), "p95": float(np.percentile(distances, 95))}

    original_to_candidate = _one_sided(original, candidate)
    candidate_to_original = _one_sided(candidate, original)

    return _to_native(
        {
            "bounding_box_delta_mm": bbox_delta,
            "volume_delta_pct": volume_delta_pct,
            "surface_distance_mm": {
                "original_to_candidate": original_to_candidate,
                "candidate_to_original": candidate_to_original,
                "max_overall": max(original_to_candidate["max"], candidate_to_original["max"]),
            },
            "verdict": "close_match"
            if max(original_to_candidate["max"], candidate_to_original["max"]) < 0.5
            else "needs_refinement",
        }
    )
