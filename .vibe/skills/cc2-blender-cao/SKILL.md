---
name: cc2-blender-cao
description: La vraie CAO dans Blender avec le pont MCP « blender » — lorsque les outils de l'atelier (cylindre, pavé, boule) ne suffisent pas : congés, biseaux, gravure à effacer, forme libre, réparation fine. Contient la marche à suivre complète, de l'import à l'export vérifié.
user-invocable: false
---

# CAO Blender — workflow complet via le pont MCP « blender »

Outils MCP du serveur `blender` : `get_scene_info`, `execute_code`, `look` (capture de la vue 3D), et les sous-outils d'édition. Blender doit tourner ; si le pont ne répond plus, dis-le en une phrase et demande de cliquer « Start MCP Server » dans Blender.

## 1. Import

- L'atelier prépare une copie PLY avec les couleurs (le chemin est dans le message du début : « copie PLY préparée par l'atelier »). Importe CELLE-LÀ — Blender n'a pas d'importeur 3MF.
- Supprime le cube, la lumière et la caméra par défaut.
- FACE COLORS : `bpy.ops.import_scene.ply(filepath=...)` garde les couleurs par face du PLY.

## 2. Mesurer AVANT de couper

Un seul appel `execute_code` compact qui importe le tout, trouve l'objet, affiche les bornes (`obj.bound_box` en monde) et, pour effacer une gravure :
- la profondeur du creux (échantillonne les sommets dans la boîte visée, compare au z moyen de la surface alentour) ;
- la boîte englobante exacte du texte (min/max x, y, z des sommets sous la surface).

NE tire JAMAIS des sommets à la main pour effacer : remplis le creux avec UN volume plein (pavé) dont le dessus affleure EXACTEMENT la surface saine, en booléen UNION. Le seuil : scalaire de comparaison à ±0,05 mm près, sinon le pavé dépasse et on voit la cicatrice en impression.

## 3. Travailler (forme, congés, biseaux)

- Congés/biseaux : en mode Edit, sélectionne les arêtes ciblées (par position, pas à la main), `bmesh.ops.bevel` avec des segments ≥ 2 pour un congé lisse. Rayon ≥ 0,8 mm (imprimable).
- Formes libres : construis par extrusions, boules et soustractions (`bmesh`), pas par sculpt — le PLY doit rester étanche.
- Travaille par étapes petites : après CHAQUE changement visible, exécute `bpy.ops.view3d.view_all` (contexte fenêtre via `bpy.context.window_manager.windows`) pour recentrer la vue — l'utilisateur te voit travailler — puis reviens : le journal de l'app montre chaque appel MCP.

## 3 bis. Créer une pièce de zéro (aucun modèle à importer)

- Pose la géométrie par le calcul, pas à l'œil : écris les coordonnées des points clés (charnière, appui, bord) avant de créer les objets, et vérifie-les par `get_scene_info` / bornes.
- Chaque partie doit **pénétrer** sa voisine d'au moins 1 mm (pas seulement la toucher) : un dossier incliné commence DANS la base, un rebord est enfoncé dans la plaque. Deux objets qui se touchent sans se recouvrir donnent des arêtes partagées par 4 faces et des morceaux séparés.
- Fusionne en UN seul objet par union booléenne (modificateur Boolean, opération UNION, solveur EXACT, appliqué), un objet à la fois, puis supprime les objets d'origine.
- Rien sous Z = 0 : la pièce repose sur le plateau, sa plus grande face plane en bas.

## 4. Vérifier à l'œil

- Après l'import et après chaque gros changement : `look` et JUGE d'après la capture, pas de ton imagination.
- Pour une analyse indépendante, appelle le sous-agent `vision` — il décrit la scène et débusque ce que tu ne vois plus ; garde ton contexte pour le travail, pas pour décrire.

## 5. Export vers la bibliothèque — LE protocole

L'atelier **remesure lui-même** chaque fichier que tu exportes (étanchéité, arêtes, morceaux, taille, Z min) et te renvoie les défauts : annoncer « étanche, vérifié » sans l'avoir mesuré ne sert à rien.

1. UN seul objet maillé sélectionné (les autres supprimés ou désélectionnés), modificateurs appliqués.
2. Mesure dans Blender, en UN appel `execute_code`, et affiche seulement ces nombres :

```python
import bpy, bmesh
o = bpy.context.active_object
bm = bmesh.new(); bm.from_mesh(o.data); bm.transform(o.matrix_world)
bad = sum(1 for e in bm.edges if not e.is_manifold)
seen, parts = set(), 0
for v in bm.verts:
    if v.index in seen: continue
    parts += 1; stack = [v]
    while stack:
        w = stack.pop()
        if w.index in seen: continue
        seen.add(w.index); stack += [e.other_vert(w) for e in w.link_edges]
zs = [v.co.z for v in bm.verts]
print("non_manifold", bad, "morceaux", parts, "zmin", round(min(zs), 3), "dims", [round(x, 1) for x in o.dimensions])
```

   Il faut `non_manifold 0`, `morceaux 1`, `zmin 0.0`, et des dimensions ≤ 256 mm. Sinon : corrige (union, pénétration, recalage en Z) et remesure.
3. Export **triangulé** dans le dossier de la bibliothèque (chemin donné au début) :

```python
bpy.ops.wm.ply_export(filepath=CHEMIN, export_selected_objects=True, apply_modifiers=True,
                      export_triangulated_mesh=True, export_colors='SRGB', ascii_format=False)
```

4. Recentre la vue sur l'objet et fais un `look`.
5. Seulement si les nombres sont bons : donne le nom du fichier exporté entre guillemets dans `reponse` — la vue 3D de l'application se recharge toute seule. Si l'atelier te renvoie un CONTRÔLE avec des défauts, corrige-les et réexporte sous le même nom.

## Pièges connus

- Un trop gros résultat d'`execute_code` coupe le pont : UN appel compact à la fois (importe + mesure + affiche), jamais d'impression de tableaux entiers.
- Les objets par défaut : `look` les montre, l'utilisateur croit que c'est sa pièce — supprime-les à l'import.
- Blender ne montre pas toujours les couleurs par face après certaines opérations booléennes : ce n'est PAS une perte — revérifie dans le PLY exporté (les champs `red green blue` par face).
