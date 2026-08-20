"""Cwd-independent launcher for the MCP server.

`python -m server.mcp_server` only resolves the `server` package if the
process's working directory happens to be the repo root - fine from a
terminal where you've `cd`ed here, but MCP clients (Claude Desktop, etc.)
often spawn the command with their own working directory, not the one you'd
expect, and not every client's config schema supports overriding it. Running
this file *by its absolute path* sidesteps the whole issue: Python always
puts a script's own directory on sys.path, regardless of cwd.

MCP client config should point directly at this file, e.g.:
    "command": "C:\\...\\fusion-reconstruct-mcp\\.venv\\Scripts\\python.exe",
    "args": ["C:\\...\\fusion-reconstruct-mcp\\run_server.py"]
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from server.mcp_server import main

if __name__ == "__main__":
    main()
