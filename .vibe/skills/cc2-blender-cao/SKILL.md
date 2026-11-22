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

## 4. Vérifier à l'œil

- Après l'import et après chaque gros changement : `look` et JUGE d'après la capture, pas de ton imagination.
- Pour une analyse indépendante, appelle le sous-agent `vision` — il décrit la scène et débusque ce que tu ne vois plus ; garde ton contexte pour le travail, pas pour décrire.

## 5. Export vers la bibliothèque — LE protocole

- Export en PLY dans le dossier de la bibliothèque (le chemin est dans le message du début), posé à plat (Z min = 0 exactement), couleurs gardées.
- APRÈS l'export : REIMPORT le fichier exporté, vérifie étanchéité (`mesh.is_watertight` ou équivalent bmesh) et lisibilité (au moins ~500 triangle pour une pièce réaliste), recentre la vue sur l'objet et fais un `look`.
- Le résultat N'EST PAS BON → corrige et exporte de nouveau. Un export corrompu ou incomplet ne s'annonce JAMAIS.
- Seulement s'il est bon : donne le nom du fichier exporté entre guillemets dans `reponse` — la vue 3D de l'application se recharge toute seule.

## Pièges connus

- Un trop gros résultat d'`execute_code` coupe le pont : UN appel compact à la fois (importe + mesure + affiche), jamais d'impression de tableaux entiers.
- Les objets par défaut : `look` les montre, l'utilisateur croit que c'est sa pièce — supprime-les à l'import.
- Blender ne montre pas toujours les couleurs par face après certaines opérations booléennes : ce n'est PAS une perte — revérifie dans le PLY exporté (les champs `red green blue` par face).
