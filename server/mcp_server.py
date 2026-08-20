"""MCP server entry point: registers mesh-analysis tools and Fusion-360-bridge
tools with the Model Context Protocol, over stdio.

Run directly (`python -m server.mcp_server` or the `fusion-reconstruct-mcp`
console script) - an MCP client (Claude Desktop, Claude Code, etc.) launches
this as a subprocess per its `mcp.json`/`claude_desktop_config.json` entry.
See README.md for the exact config snippet.
"""

from __future__ import annotations

from mcp.server import MCPServer

from . import fusion_tools, mesh_tools

INSTRUCTIONS = """\
You reconstruct 3D-printable STL/3MF meshes (or a reference photo) as
parametric Fusion 360 features. Fusion 360 itself must be running with the
FusionReconstructBridge add-in started (fusion_ping tells you if it's not).

Recommended workflow for a mesh file:
1. mesh_summary - get bounding box / volume, sanity-check units (assume mm).
2. render_orthographic_views - open the PNGs to see the part's overall shape.
3. find_circular_holes / find_circular_faces - locate bolt holes, bosses,
   cylindrical pads; list_planar_facets for large flat regions (walls, ribs).
4. For each major shape, pick a base plane or use get_cross_section at the
   relevant Z (or other) height to get the exact 2D profile to sketch.
5. fusion_new_document, then rebuild feature by feature: fusion_create_sketch
   (reuse the origin/normal from get_cross_section for non-base planes) ->
   sketch_add_* -> fusion_list_sketch_profiles -> fusion_extrude/revolve ->
   fusion_add_fillet/chamfer -> fusion_pattern_* / fusion_mirror as needed.
   Build holes as a circle sketch + extrude(operation="cut"), not a separate
   hole tool.
6. fusion_export_stl the result and run mesh_tools.compare_meshes against the
   original to check surface distance before declaring the part done; iterate
   on the features that diverge most rather than starting over.

For a reference photo instead of a mesh: there is no dimension ground truth,
so state your assumptions (e.g. "assuming a 50mm base width"), build a first
pass, take a fusion_screenshot, compare it to the photo, and refine
interactively with the user rather than promising exact measurements.
"""

mcp = MCPServer("fusion-reconstruct-mcp", instructions=INSTRUCTIONS)

_MESH_TOOLS = [
    mesh_tools.mesh_summary,
    mesh_tools.list_planar_facets,
    mesh_tools.find_circular_holes,
    mesh_tools.find_circular_faces,
    mesh_tools.get_cross_section,
    mesh_tools.render_orthographic_views,
    mesh_tools.compare_meshes,
]

_FUSION_TOOLS = [
    fusion_tools.fusion_ping,
    fusion_tools.fusion_new_document,
    fusion_tools.fusion_create_sketch,
    fusion_tools.fusion_sketch_add_line,
    fusion_tools.fusion_sketch_add_rectangle,
    fusion_tools.fusion_sketch_add_circle,
    fusion_tools.fusion_sketch_add_arc_three_point,
    fusion_tools.fusion_list_sketch_profiles,
    fusion_tools.fusion_extrude,
    fusion_tools.fusion_revolve,
    fusion_tools.fusion_add_fillet,
    fusion_tools.fusion_add_chamfer,
    fusion_tools.fusion_pattern_rectangular,
    fusion_tools.fusion_pattern_circular,
    fusion_tools.fusion_mirror,
    fusion_tools.fusion_combine,
    fusion_tools.fusion_shell,
    fusion_tools.fusion_set_parameter,
    fusion_tools.fusion_list_parameters,
    fusion_tools.fusion_list_bodies,
    fusion_tools.fusion_get_body_info,
    fusion_tools.fusion_get_timeline,
    fusion_tools.fusion_export_stl,
    fusion_tools.fusion_screenshot,
    fusion_tools.fusion_fit_view,
]

for _fn in _MESH_TOOLS + _FUSION_TOOLS:
    mcp.tool()(_fn)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
