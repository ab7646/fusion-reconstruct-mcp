# Reconstruction strategy

This is the workflow an LLM (or a human following along) should use when driving these
tools. It's also embedded as the MCP server's `instructions` field
(`server/mcp_server.py`), so a connected client sees a condensed version of this
automatically.

## Scope

This project targets **mechanical / functional parts** - the overwhelming majority of
what people actually reprint and modify: enclosures, brackets, mounts, plates with bolt
holes, bosses, ribs. It rebuilds shapes from primitives (extrude, revolve, fillet,
chamfer, pattern, mirror, boolean combine). Free-form organic/sculpted surfaces are out
of scope - there's no surface-fitting step here, and forcing one through sketches would
produce a worse, less editable result than just leaving the mesh as a mesh.

## Workflow

1. **`mesh_summary`** - bounding box, volume, watertightness. Sanity-check the size
   (assume mm; if the numbers look absurd, the source file probably used a different
   unit) before doing anything else.
2. **`render_orthographic_views`** - open the four PNGs (front/top/right/iso) with a
   vision-capable read. This is the fastest way to understand what you're building
   before drowning in numbers.
3. **`find_circular_holes`** / **`find_circular_faces`** - locate bolt holes and
   cylindrical bosses/pads. **`list_planar_facets`** - locate large flat regions (walls,
   plates, ribs) worth sketching directly.
4. For each major shape, get its exact profile with **`get_cross_section`** at the
   relevant plane. Reuse its `origin`/`normal` output directly as `fusion_create_sketch`'s
   `origin`/`normal` params - they use the same plane-basis convention, so the sketch
   lands exactly where the mesh was sliced.
5. **`fusion_new_document`**, then rebuild feature by feature:
   `fusion_create_sketch` → `sketch_add_*` → `fusion_list_sketch_profiles` (to pick the
   right `profile_index` when a sketch has more than one closed region) →
   `fusion_extrude` / `fusion_revolve` → `fusion_add_fillet` / `fusion_add_chamfer` →
   `fusion_pattern_rectangular` / `fusion_pattern_circular` / `fusion_mirror` as needed.
   Holes are a circle sketch + `fusion_extrude(operation="cut")`, not a separate tool.
6. **`fusion_export_stl`** the result, then **`compare_meshes`** it against the original.
   `verdict: "needs_refinement"` plus a large `surface_distance_mm.max_overall` tells you
   *that* something's off; cross-reference against `render_orthographic_views` /
   `fusion_screenshot` to see *what*. Iterate on the specific feature that's diverging,
   don't restart. **Check `volume_delta_pct` too, not just surface distance** - a body
   that's mostly the right shape but has one region solid where the original doesn't (or
   vice versa) can still score a deceptively low surface distance while being tens of
   percent off in volume, because that error is buried inside the shape rather than on
   its visible boundary.

### Don't assume constant/smoothly-tapering cross-sections

`get_cross_section` only traces the *outer* boundary at the one plane you asked for. It
will not warn you if the shape actually steps, or has a fully-enclosed internal void,
between two heights you didn't sample - it'll just look like a smooth trend if you only
sample every 10-50mm. Concretely, on a real bracket this produced: (a) a step from 60mm
to 35mm to 18mm that looked smooth-ish when sampled every ~7-49mm apart, leading to a
wrong loft that split the difference everywhere in between; and (b) an apparent
fully-enclosed cavity that turned out to be a duplicate-face artifact at one exact Y
value, indistinguishable from a real cavity without an independent check.

Before committing to "this region is solid/constant between height A and B":
- Sample `get_cross_section` at several closely-spaced heights (every 2-5mm across a
  suspect span, not just at the two ends) - a sudden area jump between adjacent samples
  is a step, not noise.
- Use **`check_solid`** to spot-check a handful of 3D points inside the volume you're
  about to fill (or believe is hollow). It uses ray-casting (`trimesh`'s `contains`),
  independent of `get_cross_section`'s boundary-tracing, so it won't share the same
  blind spots. If a single point gives a surprising answer, check a second point offset
  by a fraction of a mm - a ray fired exactly through a mesh edge/vertex can mis-count.

For a **reference photo** instead of a mesh: there is no dimension ground truth. State
your assumptions explicitly ("assuming a 50 mm base width"), build a first pass, take a
`fusion_screenshot`, compare it side-by-side with the photo, and refine interactively
with the user - don't present estimated dimensions as measured fact.

## Worked example

`tests/smoke_test_mesh_tools.py` builds a synthetic test part: a 40x30x10 mm box with a
6 mm-diameter through-hole and an 8 mm-tall, 10 mm-diameter boss on top. Reconstructing
it looks like this:

```text
mesh_summary("box.stl")
  -> bounding_box.size = [40, 30, 10], is_watertight = true

find_circular_holes("box.stl")
  -> [{ center: [10, 5, 0], radius: 3.0, normal: [0,0,-1] }]   # the through-hole

find_circular_faces("box.stl")
  -> [{ center: [-10, -5, 18], radius: 5.0, normal: [0,0,1] }] # the boss top

fusion_new_document()
fusion_create_sketch(plane="XY")                          # sketch_id S1
fusion_sketch_add_rectangle(S1, -20, -15, 20, 15)
fusion_list_sketch_profiles(S1)                            # -> profile_index 0
fusion_extrude(S1, 0, distance_mm=10, operation="new_body")  # body_id B1: the base plate

fusion_create_sketch(plane="XY", offset_mm=0)               # or reuse S1 for the hole
fusion_sketch_add_circle(S1, cx=10, cy=5, radius_mm=3)
fusion_list_sketch_profiles(S1)                             # -> the new circle is profile_index 1
fusion_extrude(S1, 1, distance_mm=10, operation="cut", target_body_id=B1)

fusion_create_sketch(plane="XY", offset_mm=10)               # top face, sketch_id S2
fusion_sketch_add_circle(S2, cx=-10, cy=-5, radius_mm=5)
fusion_extrude(S2, 0, distance_mm=8, operation="join", target_body_id=B1)

fusion_export_stl(B1, "candidate.stl")
compare_meshes("box.stl", "candidate.stl")
  -> verdict: "close_match"
```

(Numbers above are illustrative of the shape of the workflow - always confirm
`profile_index` with `fusion_list_sketch_profiles` rather than assuming it, since it
depends on how many closed regions already exist in that sketch.)
