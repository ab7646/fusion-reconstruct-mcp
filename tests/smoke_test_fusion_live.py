"""Manual smoke test against a REAL running Fusion 360 + FusionReconstructBridge
add-in (not run in CI - there's no headless Fusion). Rebuilds the same
40x30x10mm box + hole + boss shape as smoke_test_mesh_tools.py, feature by
feature, then exports and compares against that STL.

Run: .venv\\Scripts\\python.exe tests\\smoke_test_fusion_live.py
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server import fusion_tools, mesh_tools


def show(label, result):
    print(f"\n--- {label} ---")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return result


def main() -> None:
    show("ping", fusion_tools.fusion_ping())
    show("new_document", fusion_tools.fusion_new_document("smoke_test_fusion_live"))

    sk1 = show("create_sketch (base plate)", fusion_tools.fusion_create_sketch(plane="XY"))["sketch_id"]
    show("sketch_add_rectangle", fusion_tools.fusion_sketch_add_rectangle(sk1, -20, -15, 20, 15))
    profiles = show("list_sketch_profiles", fusion_tools.fusion_list_sketch_profiles(sk1))["profiles"]
    assert len(profiles) == 1

    ext1 = show("extrude base plate", fusion_tools.fusion_extrude(sk1, 0, distance_mm=10, operation="new_body"))
    body_id = ext1["body_id"]

    show("sketch_add_circle (hole)", fusion_tools.fusion_sketch_add_circle(sk1, cx=10, cy=5, radius_mm=3))
    profiles = show("list_sketch_profiles (after circle)", fusion_tools.fusion_list_sketch_profiles(sk1))["profiles"]
    assert len(profiles) == 2, f"expected 2 profiles (plate minus circle split), got {len(profiles)}"
    # the smaller-area profile is the circle itself (the other is the plate minus the circle)
    hole_profile_index = min(range(len(profiles)), key=lambda i: profiles[i]["area_mm2"])

    show(
        "extrude hole (cut)",
        fusion_tools.fusion_extrude(sk1, hole_profile_index, distance_mm=10, operation="cut", target_body_id=body_id),
    )

    sk2 = show("create_sketch (boss, offset 10mm)", fusion_tools.fusion_create_sketch(plane="XY", offset_mm=10))["sketch_id"]
    show("sketch_add_circle (boss)", fusion_tools.fusion_sketch_add_circle(sk2, cx=-10, cy=-5, radius_mm=5))
    show(
        "extrude boss (join)",
        fusion_tools.fusion_extrude(sk2, 0, distance_mm=8, operation="join", target_body_id=body_id),
    )

    bodies = show("list_bodies", fusion_tools.fusion_list_bodies())["bodies"]
    assert len(bodies) == 1, f"expected 1 body after joins/cuts, got {len(bodies)}"

    body_info = show("get_body_info", fusion_tools.fusion_get_body_info(body_id))
    assert len(body_info["edges"]) > 0

    show("get_timeline", fusion_tools.fusion_get_timeline())
    show("list_parameters (should be empty)", fusion_tools.fusion_list_parameters())
    show("set_parameter", fusion_tools.fusion_set_parameter("plate_thickness", "10 mm"))

    show("fit_view", fusion_tools.fusion_fit_view())

    out_dir = os.path.join(os.path.dirname(__file__), "fixtures", "generated")
    os.makedirs(out_dir, exist_ok=True)
    stl_out = os.path.join(out_dir, "fusion_live_candidate.stl")
    png_out = os.path.join(out_dir, "fusion_live_screenshot.png")
    show("export_stl", fusion_tools.fusion_export_stl(body_id, stl_out))
    show("screenshot", fusion_tools.fusion_screenshot(png_out))

    original_stl = os.path.join(out_dir, "test_part.stl")
    if os.path.isfile(original_stl):
        show("compare_meshes vs the trimesh-built original", mesh_tools.compare_meshes(original_stl, stl_out))
    else:
        print(f"\n(skipping compare_meshes - run smoke_test_mesh_tools.py first to generate {original_stl})")

    print("\nALL LIVE FUSION SMOKE TESTS PASSED")


if __name__ == "__main__":
    main()
