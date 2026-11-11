# Troubleshooting

[← Back to the README](../../README.md) · 🇫🇷 [Français](../depannage.md)

First step: `uv run cc2 doctor`, then the workshop's log (`uv run cc2 service journal`, or the console if you started it
by hand).

## The printer

| Problem | What to do |
|---|---|
| "Imprimante injoignable" (printer unreachable) | is it on, on the same network as the workshop? `ping <IP>`. The IP may have changed: fix it in the router. |
| Access code refused | read it again on the screen (Settings → Network); it changes after a reset. |
| Connection refused although everything looks right | is "LAN Only" mode on? |
| "Réglage refusé sur le réseau local" (refused over LAN) | normal for some commands (homing, temperature…): do it on the screen. |
| The CANVAS doesn't show my spools | spools must be pre-loaded or loaded; check on the screen. |

## Slicing

| Problem | What to do |
|---|---|
| "Slicer introuvable" (slicer not found) | `make slicer` |
| "missing host OpenGL runtime library" | headless server: install the libraries from [the installation guide](installation.md#on-a-headless-server). |
| "une partie flotterait sans support" (a part would float) | the workshop retries with tree supports; otherwise pick another position. |
| "Unsupported 3MF version" | the workshop rewrites recent 3MFs; if it persists, export as STL or 3MF from your software. |
| Too many colour changes | "Simplifier les couleurs", 0.24 mm layers, or merge two close colours. |
| Larger than the plate | lower the height, or enable "Découper en pièces" (cut into pieces). |

## Printing

| Problem | What to do |
|---|---|
| Marbled colours (one colour bleeds into another) | not enough purge: Équilibré or Qualité mode, and report it in the review. |
| Drops at colour changes | Équilibré mode: the nozzle wipes on a tower before going back to the part. |
| **Wipe tower knocked over** | pause, remove the tower, **don't put it back**, resume: a few strings will fall where it was. |
| Part came loose, corners lifting | wash the plate (hot water, dish soap, rinse, don't touch the surface); brim from the review. |
| The AI cries spaghetti wrongly | lower the sensitivity ("Surveillance par caméra" card); it goes quiet by itself at 98 %. |
| "Il semble rester quelque chose sur le plateau" (something seems to be on the plate) | remove the part, or "Le plateau est vide" if it's a shadow or a reflection. |

## Phone and tablet

| Problem | What to do |
|---|---|
| Security warning in the browser | the workshop's certificate isn't installed (or not "trusted" on iPhone): [guide](phone-and-tablet.md). |
| Nothing opens from the phone | is the workshop running with `--reseau`? same Wi-Fi? the address is printed at start-up. |
| Access code forgotten | `uv run cc2 code-acces` gives a new one. |
| "Trop d'essais" (too many attempts) | 5 mistakes: wait 5 minutes. |
| Away from home, it doesn't work | Tailscale on, on the phone and the machine? use the `…ts.net` address printed at start-up. |
| The camera doesn't show | printer light off ("Allumer" button on the picture); otherwise frozen camera: switch the printer off and on. |
| No notification with the app closed | is ntfy enabled (bell) and the ntfy app subscribed to the topic? "Envoyer un test". |

## ComfyUI

| Problem | What to do |
|---|---|
| `cc2 doctor`: ComfyUI unreachable | is ComfyUI running? with `--listen 0.0.0.0` if it's on another machine? right address in `[comfyui] url`? |
| "value not in list" | a model file is missing or named differently: [file list](comfyui.md#2-download-the-models). |
| Not enough video memory | close other software using the card; try `trellis_texte_vers_3d_rapide`. |
| The 3D model is poor | start from a clean image (single object, plain background), or go through `photo_vers_figurine_3d`. |
