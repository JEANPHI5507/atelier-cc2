# Blender and MCP (optional)

Blender is **not required** to use the workshop (everything works with OrcaSlicer alone). It extends step 4
**Assistant**: when Blender is open with its MCP bridge, the assistant can do real CAD — free-form shapes,
sculpting, complex fillets, anything the workshop's own tools cannot do.

## What is installed on this machine

- **Blender 4.5 LTS** in `~/tools/blender` (official tarball, no administrator rights); the `blender` command is
  on the PATH (`~/.local/bin/blender`).
- The **MCP for Blender** add-on (ahujasid/mcp-for-blender) in `~/.config/blender/4.5/scripts/addons`, enabled
  for good. As soon as Blender opens, its bridge waits for commands on `localhost:9876`.
- The **blender** MCP server registered with the agent CLI: `vibe mcp add blender --transport stdio --command
  uvx --arg blender-mcp`.

## When to use it

- The assistant's own tools (repair, resize, turn, drill, slice, orientation) cover the common cases: they stay
  faster and run through the same code as the page's buttons.
- Free-form modelling, chained holes, embossed text, varied shapes: open Blender. The assistant **imports the
  fiche's part first** (the one shown in the workshop) into the scene, does the requested work on it, then
  **exports it as PLY into the `models/` library**, so it shows up in the workshop right away and is printable.

## Watching the assistant in Blender

The assistant edits the scene in small Python blocks: between two calls the 3D view refreshes; during a call
(for instance importing a large part) the window freezes for a few seconds, then jumps to the result — that is
normal. It re-centres the view on the part after every step that changes it: just keep the Blender window in
front (not minimised) to follow along.

## Starting Blender

```bash
blender &            # the window opens; the MCP bridge starts on its own (N panel → MCP for Blender)
```

The 3D view shows the assistant working live. An assistant turn that goes through Blender can take a minute
(each message relaunches the headless agent and Blender runs the requested code): that is normal.

## The fallback engine

Without the `vibe` CLI (or with `[assistant] moteur = "api"` in `config.toml`), the assistant falls back to the
Mistral API — which needs a key (`api_key`, see Configuration) and loses access to Blender.
