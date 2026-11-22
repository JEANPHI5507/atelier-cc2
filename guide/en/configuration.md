# Settings (`config.toml`)

[← Back to the README](../../README.md) · 🇫🇷 [Français](../configuration.md)

Settings live in `config.toml`, at the project root (ignored by git, readable by your user only). Most of them are
written from the workshop (Démarrage tab, Machine card, alert bell…): you don't need to edit it by hand.
`config.example.toml` is a starting point. After editing it by hand, restart the workshop.

```toml
[printer]
host = "192.168.1.42"       # the CC2's IP (fix it in your router: static DHCP lease)
access_code = "Ab12Cd"      # access code shown on the printer's screen (Settings → Network)
serial = "F01…"             # optional: serial number, saves a request at start-up

[dashboard]
port = 8787                 # the workshop's HTTP port (network HTTPS is on 8443: cc2 dash --port-https)

[alertes]
ntfy = "https://ntfy.sh/my-topic"   # phone notifications, app closed (see the Alerts guide); "" = off

[surveillance]              # "Surveillance par caméra" card of the Printer tab
ia = true                   # failed-print AI during the print
pause_auto = false          # pause when the AI is sure of a failure
sensibilite = 1.0           # from 0.5 (fewer alerts) to 2.0 (more alerts)
timelapse = true            # one photo per layer, video in the gallery

[lancement]                 # options sent to the CC2 at start ("Machine" card)
bedlevel_force = false      # level the whole bed before each print
printer_check = true        # the printer's own checks before starting
print_layout = "A"          # layout A or B
delay_video = false         # the printer's own timelapse

[assemblage]
jeu_mm = 0.15               # dowel clearance for cut parts (Démarrage tab, step 4)

[tranchage]
niveler = true              # false removes bed levelling from the G-code: not advised, the CC2 then levels the whole bed

[slicer]
path = ""                   # another OrcaSlicer-compatible slicer (default tools/orcaslicer, installed by make slicer)

[comfyui]
url = "http://127.0.0.1:8188"   # ComfyUI's address (see the ComfyUI guide)
hunyuan = false             # show the Hunyuan3D workflows (licence not valid in the EU)

[assistant]                 # the workshop's Assistant (chat panel, preparation step 4)
moteur = "cli"              # the brain: "cli" (default) runs the agent CLI installed on this machine, "api" = Mistral.
commande = "vibe"           # (moteur "cli") the CLI agent to run headless; its MCP servers (Blender…) stay available.
reflexion = "off"           # (moteur "cli") its thinking level: "off" (default, fast) to "high" (complex CAD, slower).
modele_cli = ""             # (moteur "cli") the CLI's model alias; empty = its usual model.
api_key = ""                # (moteur "api") Mistral key (console.mistral.ai), or the MISTRAL_API_KEY variable.
                            # With no CLI engine and no key the Assistant only says it misses one.
model = "mistral-large-latest"   # (moteur "api")

[acces]                     # written by the workshop: access-code fingerprint and session secret. Don't edit.
```

## Environment variables

They take precedence over `config.toml`, handy for a test or a second workshop:

| Variable | Replaces |
|---|---|
| `CC2_CONFIG` | the path of `config.toml` |
| `CC2_MODELS` | the library folder (`models/`) |
| `CC2_HOST`, `CC2_ACCESS_CODE`, `CC2_SERIAL` | `[printer]` |
| `CC2_DASH_PORT` | `[dashboard] port` |
| `COMFYUI_URL` | `[comfyui] url` |

## Where the data is

Everything is in `models/`, next to your files:

| File | Content |
|---|---|
| `.index.json` | each G-code's card (source model, duration, grams, colours) |
| `.bobines.json`, `.mes_bobines.json` | stock and names of your spools |
| `.galerie/` | one entry per print: photo, timelapse, alerts, review |
| `.photos/` | end-of-print photos and AI alert photos |
| `.events.json` | the alert log |
| `.queue.json` | the print queue |
| `.entretien.json` | the maintenance log |
| `.plateau_vide.jpg` | the reference photo of the empty plate |
| `.thumbs/`, `.repairs/`, `.retouches/` | thumbnails, repaired copies, brush touch-ups |
| `references/` | intermediate images of AI generations |

To back up: `models/`, `config.toml` and `.certs/` (the phones' certificate authority).
