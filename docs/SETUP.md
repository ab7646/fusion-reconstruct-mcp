# Setup

Two things need to be installed: the **MCP server** (talks to your LLM client) and the
**Fusion 360 add-in** (talks to Fusion). They communicate over `http://127.0.0.1:6172`,
so both have to be running on the same machine.

## 1. MCP server

```bash
git clone https://github.com/<your-username>/fusion-reconstruct-mcp.git
cd fusion-reconstruct-mcp
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

pip install -r requirements.txt
```

Sanity-check it (no Fusion needed for this part). The smoke test builds its own
synthetic test part via a boolean op, which needs one extra dependency beyond the
runtime requirements:

```bash
pip install -r requirements-dev.txt
python tests/smoke_test_mesh_tools.py
python tests/smoke_test_mcp_server.py
```

## 2. Fusion 360 add-in

Copy the whole `fusion_addin/FusionReconstructBridge` folder into Fusion's `AddIns`
directory:

- **Windows**: `%APPDATA%\Autodesk\Autodesk Fusion 360\API\AddIns\`
- **macOS**: `~/Library/Application Support/Autodesk/Autodesk Fusion 360/API/AddIns/`

(Both paths already exist once you've opened Fusion's Scripts and Add-Ins dialog at
least once - `Utilities` tab > `Add-Ins` > `Scripts and Add-Ins` icon.)

In Fusion:

1. `Utilities` > `Add-Ins` > `Scripts and Add-Ins...`
2. `Add-Ins` tab > select **FusionReconstructBridge** > `Run`
   (tick `Run on Startup` if you want it always available)
3. You should see a message box confirming it's listening on
   `http://127.0.0.1:6172`.

If Fusion complains about the manifest not being recognized (this can happen across
Fusion versions), the reliable fallback is: click the green `+` in the Add-Ins tab to
create a new add-in from Fusion's own template first (this generates a manifest Fusion
is guaranteed to accept), then replace the generated `.py` file's contents with this
repo's `FusionReconstructBridge.py` (and copy the `lib/` folder alongside it).

## 3. Point your MCP client at the server

Add an entry to your client's MCP config. For Claude Code, run:

```bash
claude mcp add fusion-reconstruct -- /absolute/path/to/.venv/bin/python -m server.mcp_server
```

(On Windows, use the `.venv\Scripts\python.exe` path.) Or add it by hand to
`claude_desktop_config.json` / your client's `mcp.json`:

```json
{
  "mcpServers": {
    "fusion-reconstruct": {
      "command": "/absolute/path/to/fusion-reconstruct-mcp/.venv/bin/python",
      "args": ["-m", "server.mcp_server"],
      "cwd": "/absolute/path/to/fusion-reconstruct-mcp"
    }
  }
}
```

## 4. Try it

With Fusion running (add-in started) and your MCP client connected, ask it something
like:

> Reconstruct `~/Downloads/bracket.stl` as a parametric Fusion 360 model.

The LLM will call `mesh_summary`, look at `render_orthographic_views`, find holes/bosses,
then drive `fusion_*` tools to rebuild the part feature by feature. See
[RECONSTRUCTION_STRATEGY.md](RECONSTRUCTION_STRATEGY.md) for the intended workflow and a
worked example.

## Configuration

Both sides read the same two environment variables (must match if you change them):

| Variable | Default | Meaning |
|---|---|---|
| `FUSION_BRIDGE_HOST` | `127.0.0.1` | host the add-in's HTTP server binds/the client connects to |
| `FUSION_BRIDGE_PORT` | `6172` | port, ditto |
| `FUSION_BRIDGE_TIMEOUT_S` | `30` | MCP-server-side HTTP timeout per call |

The add-in currently hardcodes host/port in `FusionReconstructBridge.py` (Fusion's
embedded Python can't read your shell's environment the same way) - edit `HOST`/`PORT`
there directly if you need to change them.
