"""Cross-thread bridge into Fusion's API.

The Fusion 360 API is only safe to call from the main UI thread. Our HTTP
server (server.py) runs on a background thread, so every request has to be
handed off to the main thread and waited on. The standard Autodesk-documented
way to do that is a registered CustomEvent: firing it from any thread causes
Fusion to invoke our handler's notify() on the main thread on its next event
loop tick.

queue.Queue makes this safe even if two requests overlap: each call to
run_on_main_thread() enqueues its own (action, kwargs, result box, done
event) tuple and fires one event; notify() dequeues and executes exactly one
of them per firing.
"""

import queue
import threading
import traceback

import adsk.core

_EVENT_ID = "FusionReconstructBridge_dispatch"
_app = None
_custom_event = None
_handler = None
_request_queue: "queue.Queue" = queue.Queue()


class _DispatchHandler(adsk.core.CustomEventHandler):
    def notify(self, args):
        try:
            action_fn, kwargs, result_box, done_event = _request_queue.get_nowait()
        except queue.Empty:
            return
        try:
            result_box["result"] = action_fn(**kwargs)
            result_box["ok"] = True
        except Exception:
            result_box["ok"] = False
            result_box["error"] = traceback.format_exc()
        finally:
            done_event.set()


def start(app: adsk.core.Application) -> None:
    global _app, _custom_event, _handler
    _app = app
    _custom_event = app.registerCustomEvent(_EVENT_ID)
    _handler = _DispatchHandler()
    _custom_event.add(_handler)


def stop(app: adsk.core.Application) -> None:
    global _custom_event, _handler
    if _custom_event is not None and _handler is not None:
        _custom_event.remove(_handler)
    if app is not None:
        try:
            app.unregisterCustomEvent(_EVENT_ID)
        except Exception:
            pass  # already unregistered, e.g. add-in reload during development
    _custom_event = None
    _handler = None


def run_on_main_thread(action_fn, kwargs: dict, timeout_s: float = 25.0):
    """Call from the HTTP worker thread. Blocks until action_fn(**kwargs) has
    run on Fusion's main thread, then returns its result or re-raises its
    exception (with the original traceback text) here."""
    if _app is None:
        raise RuntimeError("thread_bridge.start() was not called - add-in did not initialize correctly")

    result_box: dict = {}
    done_event = threading.Event()
    _request_queue.put((action_fn, kwargs, result_box, done_event))
    _app.fireCustomEvent(_EVENT_ID, "")

    if not done_event.wait(timeout_s):
        raise TimeoutError(f"Fusion main-thread action '{action_fn.__name__}' timed out after {timeout_s}s")
    if not result_box.get("ok"):
        raise RuntimeError(result_box.get("error", "unknown error on Fusion main thread"))
    return result_box["result"]
