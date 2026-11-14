# Monitor a print

[← Back to the README](../../README.md) · 🇫🇷 [Français](../suivre.md)

## The "Imprimante" (printer) tab

- **Impression** (print): name, state, progress, layer, time left, end time; pause, resume, stop (with confirmation).
  When idle: "Mettre au repos" (rest) turns heaters, fans and light off.
- **Current and upcoming colour**: the spool actually engaged in the CANVAS, then the next changes with their layer and
  estimated delay ("Silk Or · couche 81 · dans 2 min", i.e. layer 81, in 2 min), and the number of changes left. When a
  layer holds several changes, the engaged spool tells where the print is within the layer.
- **Caméra**: live, picture by picture (always the latest, even on a slow connection), with the light.
- **Couche par couche** (layer by layer): the part in 3D, printed in colour, the rest in grey; it moves on by itself.
- **Températures** (nozzle, bed, chamber) with PLA, PETG, ABS presets and "Refroidir" (cool down).
- **Position de la buse** (nozzle position): X, Y, Z in mm, every second, and the plate seen from above with the last
  moves; "À la goulotte" (at the chute) when it goes to purge at a colour change.
- **Bobines CANVAS** (spools): colour, material, grams left, auto-refill. Clicking a spool corrects its weight, the
  weight of a full spool and its price per kilo.
- **Fichiers sur l'imprimante** (files on the printer) and **Historique** (history), folded; "Interface avancée" opens
  pycentauri's own interface.

Layer-by-layer tracking and upcoming colours need the G-code in the library: a print started from the CC2's screen,
with a file from elsewhere, only gets the camera and progress.

## The camera and the failed-print AI

During the print, one image every 10 seconds goes through **Obico**'s free model (The Spaghetti Detective,
AGPL-3.0), **on the workshop's machine**: no image leaves your home. It compares each image with this print's
"normal" and waits for 30 images (5 minutes) before judging.

- A doubt: "Impression suspecte" (suspicious print) alert with the framed photo.
- A certainty: "Raté détecté" (failure detected), and an **automatic pause** if you enabled it.
- After a resume, the AI starts afresh. It stops at 98 %: the last moves and the fine details of a finished part look
  too much like spaghetti.
- Settings ("Surveillance par caméra" card): AI, automatic pause, sensitivity, timelapse. The model (200 MB) installs with
  one click or with `make ia`.

The camera itself is watched too: a frozen picture (a known defect of some firmware versions, cleared by switching the
printer fully off) is reported, and the AI and timelapse pause instead of judging a frozen picture.

## Timelapse and gallery

One photo per new layer, turned into a video at the end (needs `ffmpeg`). The **Galerie** (gallery) tab keeps every
print: video, end photo, duration, grams, cost, outcome (finished, stopped, error) and the AI's alerts with their photos.
**Réimprimer** (reprint) starts the same G-code again, with the spool check. The last 200 are kept.

## The review

After a print (**Bilan** button in the gallery, or **Faire le bilan** in the end-of-print notification):

1. The workshop reminds you what to do now, depending on the part: wait for the plate to cool, remove the supports,
   empty the purge bin after a multicolour print, don't sand Silk PLA…
2. You tick what went wrong: part came loose, strings, rough top, visible seam, fragile part, supports hard to remove,
   sagging overhangs, thin lines, colours bleeding, drops at colour changes, wipe tower knocked over, elephant's foot,
   shifted layers.
3. For each defect: the likely cause, what to do on this part, and the fix for next time, computed from the print's real
   settings (a nozzle at 230 °C that strings goes to 220 °C, not "10 °C below the profile").

The fixes are kept on the model: the next time you prepare it, the workshop offers them in one click.

## The cold plate

After a finished print, the workshop waits for the plate to drop below 35 °C: at that temperature a PLA part comes off
the PEI almost by itself. It then tells you ("Plateau froid : tu peux retirer la pièce"), on the page and on the phone.
If the plate doesn't cool within 3 hours, it gives up.

## Spools and costs

Each CANVAS spool has a stock (1 kg and €20/kg by default, editable). When slicing: grams and cost per spool, purge
included. At the end of a print (or when stopped, pro rata), the filament is taken off the right spools; "bobine presque
vide" (spool almost empty) under 100 g. A spool taken out of the CANVAS keeps what is left on it: put back later, in
any tray, it takes that weight again ("Bobine remise" alert). A spool never seen before (other chip, colour or material)
starts full; for a new spool of the same colour as an old one, press "Je viens de mettre une bobine neuve" (I just put on
a new spool). The month's total is shown under the spools.

## The maintenance log

In the Printer tab, based on real print hours and the calendar: wash the PEI plate (30 h), the wiper and purge chute
(50 h), rods and belts (250 h or 90 days), filter (90 days), filament cutter and hood magnets (150 h). An alert warns when
a task is due; "Fait" (done) resets it.
