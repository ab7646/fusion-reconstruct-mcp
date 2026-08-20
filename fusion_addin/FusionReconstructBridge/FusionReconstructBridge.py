"""Fusion 360 add-in entry point.

Install: copy this whole FusionReconstructBridge folder into Fusion's AddIns
directory (see ../../docs/SETUP.md for the exact path per OS), then in
Fusion: Utilities > Add-Ins > Scripts and Add-Ins > Add-Ins tab > select
FusionReconstructBridge > Run (and tick "Run on Startup" if you want it
always available).

Once running it listens on http://127.0.0.1:6172 for the MCP server
(server/fusion_client.py) to talk to - see lib/server.py and
lib/thread_bridge.py for how requests get from that background HTTP thread
onto Fusion's main thread safely.
"""

import traceback

import adsk.core

from .lib import handlers, server, thread_bridge

app = None
ui = None

HOST = "127.0.0.1"
PORT = 6172


def run(context):
    global app, ui
    try:
        app = adsk.core.Application.get()
        ui = app.userInterface
        thread_bridge.start(app)
        server.start(HOST, PORT)
        ui.messageBox(
            f"FusionReconstructBridge is listening on http://{HOST}:{PORT}\n"
            f"({len(handlers.ACTIONS)} actions available)"
        )
    except Exception:
        if ui:
            ui.messageBox(f"FusionReconstructBridge failed to start:\n{traceback.format_exc()}")


def stop(context):
    global app, ui
    try:
        server.stop()
        thread_bridge.stop(app)
    except Exception:
        if ui:
            ui.messageBox(f"FusionReconstructBridge failed to stop cleanly:\n{traceback.format_exc()}")
