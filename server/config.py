"""Shared configuration for the MCP server and the Fusion bridge HTTP client."""

import os

# Must match fusion_addin/FusionReconstructBridge/lib/server.py.
FUSION_BRIDGE_HOST = os.environ.get("FUSION_BRIDGE_HOST", "127.0.0.1")
FUSION_BRIDGE_PORT = int(os.environ.get("FUSION_BRIDGE_PORT", "6172"))
FUSION_BRIDGE_URL = f"http://{FUSION_BRIDGE_HOST}:{FUSION_BRIDGE_PORT}"

# Feature creation (extrude, fillet, pattern...) can take a while inside Fusion,
# especially on complex bodies, so this is longer than a typical HTTP timeout.
FUSION_BRIDGE_TIMEOUT_S = float(os.environ.get("FUSION_BRIDGE_TIMEOUT_S", "30"))

# Renders / exports written by mesh_tools.py so the LLM (via its own vision, not
# this server) or the user can inspect them.
SCRATCH_DIR = os.environ.get(
    "FUSION_RECONSTRUCT_SCRATCH",
    os.path.join(os.path.expanduser("~"), ".fusion-reconstruct-mcp", "scratch"),
)
