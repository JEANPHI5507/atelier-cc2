# Prepare and print

[← Back to the README](../../README.md) · 🇫🇷 [Français](../preparer-et-imprimer.md)

Everything happens in the **Atelier** (workshop) tab, in three guided steps to the right of the 3D view:
**1. Couleurs** (colours), **2. Taille et réglages** (size and settings), **3. Trancher** (slice), then **Imprimer**
(print). The same operations exist on the command line ([Command line](command-line.md)).

## The library

On the left: your models and the files ready to print.

- **Add**: drag and drop (or click) STL, 3MF, OBJ, GLB, GLTF, PLY or G-code files, or **Importer depuis un lien**
  (import from a link). The link can point to a file, a zip of models, or a public page that offers a file to download.
  Sites that only give their files to a signed-in account (MakerWorld for example) don't work by link: download the
  file, then drop it in. An added file never replaces an existing one ("model (2).stl").
- **Views**: Tout (all), Modèles (models), **Prêts** (ready: the G-codes, grouped under the model they come from).
  Sorting and search in the "⋯" menu.
- **G-code card**: source model, quality, duration, grams, cost, colours, and "sur la CC2" if it is already on the
  printer.
- **Rename**, **select several files**, **clean up** (technical files and orphan G-codes, with the space saved):
  "⋯" menu.
- **Percer ou ajouter une forme** (drill or add a shape, cube button at the top of the model card): a cylinder, box or
  ball, drilled through the model (a hole for a screw, a magnet, a string), added to it (a peg, a base, in one of the
  model's colours or a new one) or kept alone (what the shape and the model share). The shape shows see-through on the
  model while you set it (size, direction, offset from its centre). The model's colours are kept; a new file is
  created, the original stays untouched.

## The 3D view

The model is shown **at the size it will be printed**, on the CC2's build plate (Elegoo's official markings), in the
colour of the spool that will print it.

- Views **3D**, **Face** (front), **Dessus** (top), **Côté** (side), **Plateau** (whole plate), re-centre, full screen.
- **Surplombs** (overhangs): live red colouring of the areas that will need supports.
- **Cotes** (dimensions): sizes at print scale.
- The CC2's **no-print corner** (front right, 10 × 20 mm) is shown in red: the workshop never puts anything there.
- After slicing, the **Tranchage** (slicing) tab shows the real toolpaths layer by layer (slider, playback, single
  layer, supports in orange, wipe tower), each can be hidden.

## 1. Colours

The workshop reads the model's colours (painted 3MFs from MakerWorld, Printables, OrcaSlicer or Bambu Studio;
GLB/GLTF; OBJ+MTL; coloured PLY) and **maps them to the spools actually loaded in the CANVAS**: each colour gets the
spool closest to the eye, without leaving a spool idle while two colours share one. Everything stays editable: colour by
colour, or **Modifier** (edit).

- More than 4 colours: close shades are merged.
- A model **without colour** prints with the spool already engaged in the CANVAS (no useless change).
- A colour far from every spool, or a PLA + PETG mix, is flagged.
- **Assembler** (assemble, at the top of the library): a model shipped as several files, one per colour, becomes a
  single multicolour model.
- **Pinceau** (brush, 3D view, GLB, OBJ, PLY models): touch up the colours by hand.
- **Supports** (3D view, every model): paint "Support ici" (support here, green), "Jamais de support ici" (never support
  here, red) and "Couture ici" (seam here, blue: where each layer starts); the eraser clears. Supports painted without
  asking for supports: there are some only there. The areas are kept beside the model, the file itself does not change.

## 2. Size and settings

### Optimiser pour la CC2 (optimise for the CC2)

The big button at the top does in one go what a file needs to print well on the CC2: it repairs the mesh if it is open
(on a copy), gives a real size to a unit-less AI model, picks the best face to lay down, then applies the advice
(supports, brim, cutting). Each change is explained; **Annuler l'optimisation** (undo) puts everything back.

### What is the part for?

| Choice | What it changes |
|---|---|
| **Décoratif** (decorative, default) | same look, lighter inside ("lightning" infill 8 %): up to −55 % filament |
| **Solide** (strong) | 4 walls, gyroid infill; suggested for boxes, hooks, organisers |
| **Détaillé** (detailed) | 0.12 mm layers |
| **Rapide** (fast) | 0.24 mm layers |
| **Profil Elegoo** | the original profile, unchanged |

Measured: a 95 mm figurine goes from 62 g / 3 h 35 (Elegoo profile) to 26 g / 2 h 13 in Décoratif.

### The rest of the step

- **Hauteur finale** (final height) in mm (empty: original size; 60 mm suggested for a unit-less AI model). Below the
  positions: **miroir** (mirror, left ↔ right) and per-axis scale (X, Y, Z in %).
- **Comment poser la pièce** (how to lay the part): six thumbnails (as is, lying forwards or backwards, on a side, upside
  down); the **recommended** position has the fewest overhangs and a real footprint. "Tourner sur le plateau" turns it
  flat on the plate.
- **Découper en pièces** (cut into pieces) if it is larger than the plate: cuts at the thinnest places (neck, waist…),
  Ø 5 mm dowel holes on both sides, one G-code per piece plus one for the dowels. "voir la découpe" shows the pieces in
  an exploded view. The dowel clearance is set in the Démarrage tab.
- **Plateau** (build plate): textured PEI (shipped with the CC2, 60 °C for PLA) by default; smooth PEI, cool or
  engineering plate on request.
- **Supports**: none, tree (organic, easy to remove), thin tree, strong tree, or columns; "seulement depuis le plateau"
  (only from the plate) so that nothing rests on the part.
- **Pause à la hauteur** (pause at height, mm): the CC2 pauses at that height, to insert a magnet, a nut, or change
  colour by hand. Several heights separated by ";". The head parks and the nozzle drops to 100 °C; resume from the
  workshop or the screen.
- **Exemplaires** (copies) on the plate (up to 50, in a grid). Each part is labelled in the G-code: if one fails, it can
  be dropped and the others finished.
- **Réglages avancés** (advanced settings; empty = CC2 profile value): walls, solid layers, infill pattern, top
  surface pattern, only one wall on top surfaces (already on in the CC2 profile), variable layer height (thinner
  layers where the surface slopes gently, for smoother domes and curves), precise outer wall (true dimensions for
  parts that fit together), seam, ironing, brim, raft, support angle, temperatures, pressure advance, flow… Each value
  is checked before going to the slicer.

### Multicolour

| Mode | Principle | When |
|---|---|---|
| **Économie** (default) | no wipe tower, purge sized per colour change | most parts |
| **Équilibré** (balanced) | wipe tower + sized purge | if drops or smears appear at colour changes |
| **Qualité** (quality) | tower + OrcaSlicer's original purge | very contrasting colours, maximum cleanliness |
| **Sans purge** (no purge) | spool change only | experiments; visible colour mixing |

The purge happens in the CANVAS chute. It is sized **in real volume** for each colour transition (red to white needs more
than white to red), which avoids marbling. Measured on a 60 mm four-colour parrot: 13 h 13 and ≈ 200 g in Qualité,
8 h 26 and ≈ 38 g in Économie.

In Équilibré and Qualité, the tower has an 8 mm brim and the nozzle lifts 0.8 mm when travelling over it: with Silk PLA,
the string that oozes after each purge curls into loops on the tower, and the nozzle used to catch them until it knocked
the tower over.

**Simplifier les couleurs** (simplify colours: Non, Léger, Fort): a colour patch that is almost absent from a layer
(under 3 %, or 10 % in Fort) takes that layer's dominant colour. Fewer changes, less purge, no visible difference in Léger.

What really counts: **fewer changes** (thicker layers, simplified colours) and **several parts per plate**, because
changes happen layer by layer for all parts at once. The result warns above 150 changes.

## 3. Slice

**Trancher** runs OrcaSlicer with Elegoo's CC2 profiles. The result gives the duration, grams and cost (purge included)
per spool, the number of colour changes, and what to watch.

- The **advisor** looks at the part as it will be printed and warns before you waste a spool: walls too thin, little
  contact with the plate, overhangs without support, a floating piece, a tall thin part, an open mesh. Each point has a
  button that applies the fix.
- **Comparer les options** (compare options) slices several variants in the background (quality, use) and shows the
  difference in filament, cost and time; "Choisir" (choose) applies one.
- If OrcaSlicer refuses a part that would float without support, the workshop tries again with tree supports and says so.

## Print

**Imprimer** opens the start window:

- **Quelle bobine pour chaque couleur** (which spool for each colour): suggested from the G-code's colours and the
  CANVAS, editable. This is what is sent to the CC2 (without it, the CC2 would print T0 with spool 1, T1 with spool 2…).
- **Plate checked by the camera**: when the plate is empty, click "Le plateau est vide : mémoriser" (the plate is empty:
  remember it) once. Then, before each print, the workshop compares the front of the plate with that photo (with the
  light turned on for it) and blocks the start if a part is still there. "Le plateau est vide" updates the reference
  when in doubt (shadow, reflection).
- **Machine options**: level the bed first, printer checks, the printer's own timelapse, layout A/B. Defaults are set in
  the "Machine" card of the Printer tab.
- Grams and cost, with a warning if a spool won't be enough.

If the printer is already printing, **Ajouter à la file d'attente** (add to queue) keeps the file for later. In the
Printer tab, the **File d'attente** (queue) card offers "Plateau vidé : lancer la suivante" (plate cleared: start the
next one) as soon as the previous part is removed.

## Create without CAD

The **Créer** (create) button (top of the library) makes custom parts, with a 3D preview that follows every setting:

| Part | Settings |
|---|---|
| Box with lid | length, width, height, walls, lid clearance, rounded corners |
| Raised label (2 colours) | text (several lines), letter height, relief, margin, hanging hole |
| Wall hook | width, back height, depth, thickness, screw diameter |
| Compartment organiser | dimensions, number of cells each way, dividers, bottom |
| Gridfinity bin | size in 42 mm cells, height in 7 mm units, compartments, 6 × 2 mm magnets, stacking lip |
| Gridfinity baseplate | size in cells, magnets |
| Phone stand | width, angle, device thickness (case included), back, cable slot |
| Cable organiser | number and diameter of cables, screw tabs or adhesive |
| Screw, nut, washer, spacer | ISO metric thread from M3 to M10, length, print clearance |
| Spur gear | number of teeth, module, thickness, bore, pressure angle |
| Name keychain (2 colours) | name, lettering, letter height, relief |
| Christmas ornament with a name | bauble, star or tree, name, size, relief |
| Photo lithophane | your photo, width, light and dark thickness, frame (printed upright, 100 % infill) |

The created part lands in the library, ready for the three steps.

## After the print

The **review** (gallery, or the button in the end-of-print notification) records what went wrong; the fix is offered
the next time you prepare the same model. See [Monitor a print](monitoring.md).
