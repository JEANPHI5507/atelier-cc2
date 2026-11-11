# Command line

[← Back to the README](../../README.md) · 🇫🇷 [Français](../ligne-de-commande.md)

Everything goes through the `cc2` command, run with uv from the project folder (`uv run cc2 …`), or directly after
`source .venv/bin/activate`. `cc2 --help` and `cc2 <command> --help` list every option (the workshop's own commands
answer in French).

Commands that **change** the printer (start, stop, heat, light, file upload) need `--control`, right after `cc2`:
`cc2 --control light on`. Without it, everything is read-only.

## The workshop

| Command | Role |
|---|---|
| `cc2 --control dash` | the web workshop on http://localhost:8787/lab/ |
| `cc2 --control dash --reseau` | open to phone and tablet, over HTTPS on port 8443 (`--port-https`, `--sans-https`) |
| `cc2 simulateur` | a simulated CC2 with the workshop, on http://localhost:8788/lab/ (`--duree 120`: 2 min per print) |
| `cc2 --control service installer` | automatic start (systemd service, open to the network; `--local` otherwise) |
| `cc2 service etat` / `journal` / `retirer` | status, log, or remove the service |
| `cc2 code-acces` | change the phones' access code (they'll have to enter it again) |
| `cc2 doctor` | check `config.toml`, the printer and ComfyUI |

## The printer

These commands come from [pycentauri](https://github.com/bjan/pycentauri), pre-filled with the address and code from
`config.toml`.

| Command | Role |
|---|---|
| `cc2 status` | the state, once |
| `cc2 watch` | the state continuously (Ctrl+C to stop) |
| `cc2 attributes` | model, firmware, capabilities |
| `cc2 canvas` | the CANVAS spools |
| `cc2 files` / `cc2 history` / `cc2 disk` | files on the printer, history, free space |
| `cc2 snapshot photo.jpg` | a camera photo |
| `cc2 discover` | find printers on the network |
| `cc2 --control light on` | light (`on` / `off`) |
| `cc2 --control upload file.gcode` | upload a file |
| `cc2 --control delete file.gcode` | delete a file from the printer |
| `cc2 --control refill --on` | CANVAS auto-refill (`--off` to turn it off) |

## Prepare and slice

```bash
cc2 models list                                   # the library
cc2 models info model.glb                         # dimensions, watertight, does it fit on the plate?
cc2 models prepare model.glb --height 60          # repaired STL, laid on the plate, 60 mm high
cc2 colors model.3mf                              # colours found and the spool suggested for each
cc2 slice model.3mf                               # slice (multicolour mode Économie by default)
cc2 slice-profiles                                # available nozzles, qualities and filaments
```

`cc2 slice` options:

| Option | Role |
|---|---|
| `--height 80` | final height in mm |
| `--quality "0.16mm Optimal"` | quality profile (see `slice-profiles`) |
| `--filament PLA --filament "PLA Silk"` | filament of each spool, in order |
| `--slot 3:1` | put the model's colour 3 in spool 1 |
| `--infill 15` | infill in % |
| `--supports arbre` | `aucun` (none), `arbre` (tree), `arbre_fin`, `arbre_solide`, `colonnes` (columns); `--plateau-seul` (from plate only) |
| `--mode equilibre` | multicolour: `economie`, `equilibre`, `qualite`, `sans_purge` |
| `--decouper` | cut into pieces with dowels if too large |
| `--nozzle 0.6` | another nozzle (plain single-colour slicing) |
| `--upload --start` | upload then start (with `cc2 --control slice …`) |

Examples:

```bash
cc2 slice dragon.glb --height 300 --decouper --supports arbre
cc2 --control slice cube.stl --upload --start        # check the plate and filament first!
cc2 multicolor base.stl:1 top.stl:2 --filament PLA --filament "PLA Silk"   # one file per colour
```

## AI generation

```bash
cc2 gen trellis_texte_vers_3d --prompt "a small red dragon"
cc2 gen trellis_image_vers_3d --image photo.png --seed 42
```

See [AI generation with ComfyUI](comfyui.md).

## Other

| Command | Role |
|---|---|
| `cc2 server` | pycentauri's HTTP server alone (the workshop already includes it) |
| `cc2 mcp` | pycentauri's MCP server (to drive the printer from a compatible assistant) |
| `cc2 rtsp` | re-stream the camera as RTSP (H.264) with MediaMTX |
| `make test` | the automated tests |
| `make deploy SERVEUR=host` | send the code to a server over ssh and restart the workshop there |
