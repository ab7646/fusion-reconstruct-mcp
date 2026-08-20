"""Second live-Fusion smoke test, covering the actions
smoke_test_fusion_live.py doesn't touch: fillet, chamfer, mirror,
rectangular/circular pattern, revolve, and an explicit combine on two
separately-created bodies. Each check uses its own fresh document to avoid
geometry collisions between unrelated features.

Run: .venv\\Scripts\\python.exe tests\\smoke_test_fusion_live_features.py
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server import fusion_tools as ft


def show(label, result):
    print(f"\n--- {label} ---")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return result


def test_fillet_and_chamfer():
    ft.fusion_new_document("smoke_fillet_chamfer")
    sk = show("create_sketch", ft.fusion_create_sketch(plane="XY"))["sketch_id"]
    ft.fusion_sketch_add_rectangle(sk, -10, -10, 10, 10)
    ext = show("extrude box", ft.fusion_extrude(sk, 0, distance_mm=10, operation="new_body"))
    body_id = ext["body_id"]

    fillet = show("add_fillet (all_edges)", ft.fusion_add_fillet(body_id, {"kind": "all_edges"}, radius_mm=1.0))
    assert fillet["edges_affected"] == 12, f"expected 12 edges on a box, got {fillet['edges_affected']}"

    info = show("get_body_info after fillet", ft.fusion_get_body_info(body_id))
    top_edges = [e for e in info["edges"] if abs(e["midpoint_mm"][2] - 9) < 2]
    assert top_edges, "expected some edges near the top face after filleting"
    near_point = top_edges[0]["midpoint_mm"]

    chamfer = show(
        "add_chamfer (near_points)",
        ft.fusion_add_chamfer(body_id, {"kind": "near_points", "points": [near_point], "max_distance_mm": 3.0}, distance_mm=0.5),
    )
    assert chamfer["edges_affected"] >= 1


def test_mirror_and_pattern():
    ft.fusion_new_document("smoke_mirror_pattern")
    sk = show("create_sketch", ft.fusion_create_sketch(plane="XY"))["sketch_id"]
    ft.fusion_sketch_add_circle(sk, cx=15, cy=0, radius_mm=2)
    ext = show("extrude peg", ft.fusion_extrude(sk, 0, distance_mm=5, operation="new_body"))

    mirrored = show("mirror across YZ", ft.fusion_mirror(ext["feature_id"], plane="YZ"))
    bodies = show("list_bodies after mirror", ft.fusion_list_bodies())["bodies"]
    assert len(bodies) == 2, f"expected 2 bodies (original + mirrored peg), got {len(bodies)}"

    patterned = show(
        "pattern_circular (4x around Z)",
        ft.fusion_pattern_circular(mirrored["feature_id"], axis="z", quantity=4, total_angle_deg=360.0),
    )
    bodies = show("list_bodies after circular pattern", ft.fusion_list_bodies())["bodies"]
    assert len(bodies) == 5, f"expected 5 bodies (2 + 3 more instances), got {len(bodies)}"


def test_revolve():
    ft.fusion_new_document("smoke_revolve")
    sk = show("create_sketch", ft.fusion_create_sketch(plane="XY"))["sketch_id"]
    ft.fusion_sketch_add_rectangle(sk, 5, -5, 10, 5)  # offset from the Y axis -> a ring when revolved
    profiles = show("list_sketch_profiles", ft.fusion_list_sketch_profiles(sk))["profiles"]
    assert len(profiles) == 1
    rev = show(
        "revolve 360deg around Y axis",
        ft.fusion_revolve(sk, 0, axis_start=[0, -20], axis_end=[0, 20], angle_deg=360.0, operation="new_body"),
    )
    info = show("get_body_info of the revolved ring", ft.fusion_get_body_info(rev["body_id"]))
    assert info["volume_mm3"] > 0


def test_combine_two_bodies():
    ft.fusion_new_document("smoke_combine")
    sk = show("create_sketch", ft.fusion_create_sketch(plane="XY"))["sketch_id"]
    ft.fusion_sketch_add_rectangle(sk, -10, -10, 10, 10)
    body_a = show("extrude body A", ft.fusion_extrude(sk, 0, distance_mm=5, operation="new_body"))["body_id"]

    sk2 = show("create_sketch (offset)", ft.fusion_create_sketch(plane="XY", offset_mm=5))["sketch_id"]
    ft.fusion_sketch_add_circle(sk2, cx=0, cy=0, radius_mm=5)
    body_b = show("extrude body B (separate)", ft.fusion_extrude(sk2, 0, distance_mm=5, operation="new_body"))["body_id"]

    bodies = show("list_bodies before combine", ft.fusion_list_bodies())["bodies"]
    assert len(bodies) == 2

    combined = show("combine (join)", ft.fusion_combine(body_a, [body_b], operation="join"))
    bodies = show("list_bodies after combine", ft.fusion_list_bodies())["bodies"]
    assert len(bodies) == 1, f"expected 1 body after join, got {len(bodies)}"


def main() -> None:
    show("ping", ft.fusion_ping())
    test_fillet_and_chamfer()
    test_mirror_and_pattern()
    test_revolve()
    test_combine_two_bodies()
    print("\nALL LIVE FUSION FEATURE TESTS PASSED")


if __name__ == "__main__":
    main()
