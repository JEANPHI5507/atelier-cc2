# First connection to the CC2

[← Back to the README](../../README.md) · 🇫🇷 [Français](../premiere-connexion.md)

The workshop talks to the printer over the local network, like Elegoo's software, but without the cloud. It needs
three things: the printer in **local network mode**, its **IP address** and its **access code**.

## 1. Prepare the printer

1. On the CC2's screen: **Settings → Network**. Connect it to your home Wi-Fi (or cable) if it isn't already, then
   enable **"LAN Only"**.
   This mode turns off Elegoo's online services (app, AI and video in the cloud): the workshop replaces them.
2. On the same screen, write down the **IP address** (like `192.168.1.42`) and the **access code** (6 characters).
3. Recommended: in your router's settings, give the printer a **fixed address** (static DHCP lease). Otherwise the
   address can change after a power cut, and the workshop won't find it any more.

## 2. The "Démarrage" (setup) tab

Start the workshop (`uv run cc2 --control dash`) and open the **Démarrage** tab. It guides you in four steps.

1. **Connecter l'imprimante** (connect the printer). Enter the IP and access code, then **Tester la connexion** (test
   the connection). The test checks, in order, that the printer answers on the network, that the code is right and
   that LAN mode is on; for each failure, it says what to fix. **Enregistrer** (save) writes `config.toml`. Then restart
   the workshop so it connects (or `systemctl --user restart cc2-atelier` if it runs as a service).
2. **Charger le CANVAS** (load the CANVAS). Four PLA spools of clearly different colours for the tests. The workshop
   reads the CANVAS (colour and material of each spool): check in the Printer tab that all four show up with the right
   material.
3. **Imprimer les pièces de test** (print the test parts), generated and sliced on demand, each with what to look at:
   first layer (5 squares, 3 min), 20 mm cube (14 min), 4-colour CANVAS test (42 min), dowel fit (43 min).
4. **Régler l'assemblage** (set up assembly). From the dowel test, pick the clearance that fits well. It is then used
   for every cut part (0.15 mm by default).

## 3. From the command line

```bash
uv run cc2 doctor          # checks config.toml, the printer (MQTT, port 1883) and ComfyUI
uv run cc2 status          # the printer's state, once (read-only)
uv run cc2 canvas          # the CANVAS spools
```

Commands that **change** something (start, stop, heat, light) need `--control`: `uv run cc2 --control light on`.

## If it doesn't connect

- **"injoignable"** (unreachable): is the printer on, on the same network as the workshop's machine? Try `ping <IP>`.
  A guest network or an "isolated" Wi-Fi on the router stops devices from seeing each other.
- **Code refused**: the code changes if the printer is reset; read it again on the screen.
- **LAN mode off**: without "LAN Only", the CC2 refuses local connections.
- **The IP changed**: redo step 1 in the Démarrage tab, then fix the address in the router.

More cases: [Troubleshooting](troubleshooting.md).
