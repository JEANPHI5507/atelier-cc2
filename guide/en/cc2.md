# What to know about the CC2

[← Back to the README](../../README.md) · 🇫🇷 [Français](../cc2.md)

What the workshop learned about the Centauri Carbon 2, and takes into account. Sources: the **official firmware source
code** ([elegooofficial/CentauriCarbon2](https://github.com/elegooofficial/CentauriCarbon2), GPL-3.0: error codes, CANVAS,
`M6211` macro), tests on a real CC2 (firmware 02.01.01.13), then owners' reports and release notes
([OpenCentauri](https://docs.opencentauri.cc/software/updates-cc2/),
[printer-hub.com](https://printer-hub.com/posts/elegoo-centauri-carbon-2-known-issues),
[printer-protocol-orchard](https://github.com/ChestnutLabs/printer-protocol-orchard/blob/main/protocols/elegoo.md)).

The firmware repository doesn't include the network layer: the protocol commands come from
[pycentauri](https://github.com/bjan/pycentauri) and are not confirmed by Elegoo.

## Local network

- **"LAN Only"** mode is required. It turns off Elegoo's cloud AI and video, which the workshop replaces.
- The printer talks **MQTT on port 1883** (state, commands) and serves its **camera as MJPEG on port 8080**, open to the
  whole local network.
- **Refused over the local network** (Elegoo's SDK): homing, moves, Z offset, calibrations, filament loading. The
  temperature setpoint is refused too (error 1003). These are done on the screen; the workshop says so when it can't.
- A finished print goes from ~97 % to "ready" with no "finished" state: the workshop reads the printer's history to know
  whether it finished or was stopped.
- During a **firmware update**, the printer reports a state of its own (9), then disconnects for about a minute: the
  workshop doesn't take it for a print.

## CANVAS and colour changes

- In the G-code, a colour change is the **`M6211 T<n> L<purge mm>`** macro (not a plain `T<n>`).
- The purge goes into the **chute at the back** (X52, Y264). The firmware **always pushes at least 23 mm + 6 mm** of
  filament per change, even if the slicer asks for less: shrinking the purge matrix further is useless. OrcaSlicer
  therefore underestimates the purge; the workshop recounts it like the firmware.
- Elegoo's macro purges at **240 °C**, then printing resumes at its own temperature: the nozzle comes back very fluid.
  With a wipe tower, the string curls into loops on it; the workshop lifts the nozzle 0.8 mm and widens the tower's base.
- CANVAS spools are numbered 0 to 3 internally; a channel is free (0), pre-loaded (1) or loaded (2).
- Without a mapping table sent at start, the CC2 prints T0 with spool 1, T1 with spool 2, and so on. The workshop always
  sends the table chosen in the start window.
- The **purge bin** fills up fast in multicolour: the workshop reminds you after each multicolour print.

## Slicing

- The CC2 refuses a G-code whose filament profiles don't carry its names: the workshop puts the official names back
  ("Elegoo PLA @ECC2").
- **Ramming disabled**, as in ElegooSlicer: enabled, it causes error 1243 (abnormal extrusion).
- The CC2 **always levels** before printing. The workshop keeps the slicer's levelling mesh (limited to the part's area,
  faster); removing it (`[tranchage] niveler = false`) makes it level the whole bed. On a small part it probes only
  that area (16 points, a 28 mm star); on a large area reaching the bed's edge (prime tower included) it has probed the
  whole bed (about 9 min). That choice is made by a closed Elegoo module.
- The firmware reads `EXCLUDE_OBJECT_DEFINE` like Klipper: with several copies, a failed part can be dropped and the
  others finished.
- `PAUSE` in the G-code works: the head parks above the bin and the nozzle drops to 100 °C.
- `SET_PRESSURE_ADVANCE` and `M221` (flow) are accepted: they are the "pressure advance" and "flow" advanced settings.
- No-print corner of the plate: 246-256 × 0-20 mm (front right). The workshop places nothing there.

## Known errors and defects

- The **34 error codes** of the firmware's official list are explained in the alerts with what to do: heating, sensors,
  fans, 704 levelling, 707 head cover detached, 801-803 links, 1101/1103 exhaust grille, 1210-1264 CANVAS (empty spool,
  filament cutter, loading, unloading, tangled filament).
- **Frozen camera** (firmware ≥ 01.03.01.89): it comes back after a full power-off. The workshop detects it, reports it,
  and pauses the AI and timelapse. It turns the light on at the start: with the light off, the camera is black.
- **Materials**: TPU (not through the CANVAS, no levelling at 60 °C), abrasive filaments (they wear the CANVAS sensor),
  high-temperature materials (loading at 250 °C), ABS/ASA (passive chamber, 35 to 45 °C): the workshop warns at start.

## Firmware

Only update to fix a problem: since 02.00.02.00, downgrading is blocked, and an update may change the network protocol
the workshop depends on.
