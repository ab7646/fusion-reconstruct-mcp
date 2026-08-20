"""Manual smoke test (not pytest) for mesh_tools against a synthetic mesh:
a 40x30x10 mm box with a 6mm through-hole and a 8mm-tall, 5mm-radius boss on
top. Run: .venv\\Scripts\\python.exe tests\\smoke_test_mesh_tools.py
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import trimesh

from server import mesh_tools


def build_test_part() -> trimesh.Trimesh:
    box = trimesh.creation.box(extents=[40, 30, 10])
    box.apply_translation([0, 0, 5])  # sit on Z=0

    hole = trimesh.creation.cylinder(radius=3, height=20, sections=48)
    hole.apply_translation([10, 5, 5])

    boss = trimesh.creation.cylinder(radius=5, height=8, sections=48)
    boss.apply_translation([-10, -5, 10 + 4])

    part = box.difference(hole)
    part = part.union(boss)
    part.remove_unreferenced_vertices()
    return part


def main() -> None:
    out_dir = os.path.join(os.path.dirname(__file__), "fixtures", "generated")
    os.makedirs(out_dir, exist_ok=True)
    stl_path = os.path.join(out_dir, "test_part.stl")

    part = build_test_part()
    part.export(stl_path)
    print(f"wrote {stl_path} watertight={part.is_watertight}")

    print("\n--- mesh_summary ---")
    print(json.dumps(mesh_tools.mesh_summary(stl_path), indent=2))

    print("\n--- list_planar_facets (top 5) ---")
    facets = mesh_tools.list_planar_facets(stl_path)
    print(json.dumps(facets[:5], indent=2))
    assert len(facets) > 0, "expected at least one planar facet"

    print("\n--- find_circular_holes ---")
    holes = mesh_tools.find_circular_holes(stl_path)
    print(json.dumps(holes, indent=2))
    assert any(abs(h["radius"] - 3.0) < 0.2 for h in holes), f"expected a ~3mm radius hole, got {holes}"

    print("\n--- find_circular_faces ---")
    faces = mesh_tools.find_circular_faces(stl_path)
    print(json.dumps(faces, indent=2))
    assert any(abs(f["radius"] - 5.0) < 0.2 for f in faces), f"expected a ~5mm radius circular face (boss top), got {faces}"

    print("\n--- get_cross_section at Z=5 ---")
    section = mesh_tools.get_cross_section(stl_path, plane_origin=[0, 0, 5], plane_normal=[0, 0, 1])
    print(json.dumps({k: v for k, v in section.items() if k != "polygons"}, indent=2))
    print(f"num_polygons={section['num_polygons']}")
    assert section["num_polygons"] >= 1
    poly0 = section["polygons"][0]
    print(f"outer points={len(poly0['outer'])} holes={len(poly0['holes'])}")
    assert len(poly0["holes"]) >= 1, "expected the through-hole to show up as an interior ring at Z=5"

    print("\n--- render_orthographic_views ---")
    views = mesh_tools.render_orthographic_views(stl_path)
    print(json.dumps(views, indent=2))
    for name, path in views["views"].items():
        assert os.path.isfile(path) and os.path.getsize(path) > 0, f"missing/empty render for {name}"

    print("\n--- compare_meshes (self vs self, expect ~0) ---")
    cmp = mesh_tools.compare_meshes(stl_path, stl_path)
    print(json.dumps(cmp, indent=2))
    assert cmp["surface_distance_mm"]["max_overall"] < 1e-6

    print("\nALL SMOKE TESTS PASSED")


if __name__ == "__main__":
    main()
