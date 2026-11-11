# Installation

[← Back to the README](../../README.md) · 🇫🇷 [Français](../installation.md)

The workshop is a web server written in Python. It runs on a **Linux x86-64** machine at home, on the same network as
the printer, and you open it in a browser: on that machine, on a phone or on a tablet. The machine must stay on during
prints to watch the camera and send alerts (the print itself carries on even if the workshop stops: it runs on the CC2).

## Requirements

| | Minimum | Comfortable |
|---|---|---|
| System | Linux x86-64 (tested on Ubuntu 24.04 and later) | |
| CPU | 2 cores | 4 cores or more: slicing is faster |
| Memory | 4 GB | 8 GB |
| Disk | 3 GB (workshop + OrcaSlicer + AI model) | more for your library and timelapses |
| Network | same local network as the printer | |

Measured: slicing a 60 mm four-colour figurine (300 layers) takes 5 s on a recent mini-PC and 17 s on a 2015 i5. The
camera AI analyses one image in 0.1 to 0.2 s, once every 10 s.

Software:

- **Python 3.12** and **[uv](https://docs.astral.sh/uv/)** (Python package manager). If your system has another
  Python version, uv installs the right one separately: `uv python install 3.12`.
- **git**, **make**, **curl** (often already there).
- **ffmpeg** to turn timelapses into a video: `sudo apt install ffmpeg`. Without it, the per-layer photos are kept, but
  not the video.

## Install

```bash
git clone https://github.com/JEANPHI5507/atelier-cc2
cd atelier-cc2
uv sync                 # creates .venv/ with all dependencies
make slicer             # downloads OrcaSlicer 2.4.2, checks its SHA-256, extracts it into tools/
make ia                 # optional: Obico's failed-print detection model (≈ 200 MB), checked too
```

`make slicer` also copies the CC2 build plate model and markings shipped with OrcaSlicer (`make plateau` does it on
its own). Without them, the 3D view shows a plain plate.

The AI model can also be installed later with one click, from the Printer tab ("Surveillance par caméra" card).

### On a headless server

OrcaSlicer loads graphics libraries even when slicing from the command line. On a server without a desktop, install
them (Ubuntu / Debian):

```bash
sudo apt update
sudo apt install -y libatk1.0-0t64 libcairo2 libcairo-gobject2 libegl1 libfontconfig1 libgdk-pixbuf-2.0-0 libgl1 \
  libglu1-mesa libglx0 libgstreamer-plugins-base1.0-0 libgtk-3-0t64 libharfbuzz0b libice6 libjavascriptcoregtk-4.1-0 \
  libopengl0 libpango-1.0-0 libpangocairo-1.0-0 libpangoft2-1.0-0 libsecret-1-0 libsm6 libsoup-3.0-0 \
  libwayland-client0 libwayland-egl1 libwayland-server0 libwebkit2gtk-4.1-0
```

To see what is missing: `ldd tools/orcaslicer/squashfs-root/bin/orca-slicer | grep "not found"`. If slicing fails with
"missing host OpenGL runtime library", this is the reason.

## First start

```bash
uv run cc2 --control dash
```

Open http://localhost:8787/lab/ on the machine. The **Démarrage** (setup) tab guides the connection to the printer:
see [First connection](first-connection.md). Settings are written to `config.toml` (ignored by git, readable by you
only); you can also start from `config.example.toml`.

- Without `--control`, the workshop is **read-only**: it shows everything but doesn't start, stop or heat anything.
- By default it only listens on the machine itself (`127.0.0.1`). To open it to your phone and tablet, add `--reseau`:
  see [Phone, tablet, away from home](phone-and-tablet.md).

You can try everything first without a printer with `uv run cc2 simulateur` (http://localhost:8788/lab/).

## Automatic start

```bash
uv run cc2 --control service installer
```

The workshop becomes a systemd service of your user: it starts with the machine, even with nobody logged in, and
restarts on its own if it stops. It is open to the network (`--reseau`) by default; `--local` keeps it on the machine.

```bash
uv run cc2 service etat       # is it running?
uv run cc2 service journal    # its latest messages
uv run cc2 service retirer    # remove it
```

Don't run `cc2 dash` by hand at the same time: the ports would already be taken. If the service doesn't start without
a login session, enable lingering once: `sudo loginctl enable-linger $USER`.

## Update

```bash
cd atelier-cc2
git pull
uv sync
make slicer                     # does nothing if OrcaSlicer is already the right version
systemctl --user restart cc2-atelier
```

Your library (`models/`), `config.toml` and certificates (`.certs/`) are never touched by an update. Phones and the
tablet show the new interface the next time they open it.

Restarting the workshop during a print is safe for the print: the workshop picks up its monitoring mid-way (the camera
AI starts afresh and judges again after 5 minutes).

## Running on a server, coding elsewhere

If the workshop runs on a home server and you edit the code on another PC, `make deploy` sends the code over ssh and
restarts the service:

```bash
make deploy SERVEUR=my-server      # "my-server": a host from your ~/.ssh/config; folder ~/elegoo on the server
```

It only sends the code (`src/`, `pyproject.toml`, `uv.lock`…): the server's library, `config.toml`, `.certs/` and
`tools/` stay its own.

## Moving the workshop to another machine

Everything lives in the project folder. To keep your history, copy along with the code:

- `models/`: library, gallery, spools, alerts, queue, reviews;
- `config.toml`: printer, access code, alerts;
- `.certs/`: the certificate authority your phones already trust (without it, you'll have to reinstall the certificate
  on each device).

Stop the workshop on the old machine before copying, then install the service on the new one.
