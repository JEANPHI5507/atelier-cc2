# Blender et MCP (facultatif)

Blender n'est **pas nécessaire** pour se servir de l'atelier (tout marche avec OrcaSlicer seul). Il enrichit
l'étape 4 **Assistant** : quand Blender est ouvert avec son pont MCP, l'assistant peut faire de la vraie CAO —
formes libres, sculpture, biseaux complexes, tout ce que les outils de l'atelier ne savent pas faire.

## Ce qui est installé sur cette machine

- **Blender 4.5 LTS** dans `~/tools/blender` (tarball officiel, sans droits administrateur) ; la commande
  `blender` est dans le PATH (`~/.local/bin/blender`).
- L'add-on **MCP for Blender** (ahujasid/mcp-for-blender), dans `~/.config/blender/4.5/scripts/addons`, activé
  pour de bon. Dès qu'on ouvre Blender, son pont attend les commandes sur `localhost:9876`.
- Le serveur MCP **blender** enregistré auprès du CLI agent : `vibe mcp add blender --transport stdio --command
  uvx --arg blender-mcp`.

## Quand l'utiliser

- Les outils de l'assistant (réparer, redimensionner, pivoter, percer, trancher, orientation) couvrent les cas
  courants : ils restent plus rapides et passent par le même code que les boutons de la page.
- Modélisation libre, trous qui se suivent, texte en relief, formes variées : ouvre Blender. L'assistant y
  **importe d'abord la pièce de la fiche** (celle affichée dans l'atelier) dans la scène, y construit le travail
  demandé, puis l'**exporte en PLY dans la bibliothèque `models/`**, donc tout de suite visible dans l'atelier
  et imprimable.

## Suivre l'assistant dans Blender

L'assistant édite la scène par petits blocs de code Python : entre deux appels, la vue 3D se met à jour ;
pendant un appel (par exemple l'import d'une grosse pièce), la fenêtre est figée quelques secondes puis saute au
résultat — c'est normal. Il recentre la vue sur la pièce à chaque étape qui la modifie : garde juste la fenêtre
Blender au premier plan (ou pas minimisée) pour suivre.

## L'assistant voit la pièce

L'assistant dispose de l'outil **vision** du pont Blender : après l'import et après chaque gros changement, il
prend une capture de la vue 3D (`look`) et juge d'après ce qu'il **voit**, pas d'après son imagination. Pour
l'analyse détaillée, il peut appeler un **sous-agent « vision »** (défini dans `~/.vibe/agents/vision.toml`) qui
regarde la scène et lui renvoie une description indépendante — l'assistant garde son propre contexte pour
travailler. Pour une bonne capture, cadrez la pièce avec un éclairage correct ; s'il décrit un objet difforme,
c'est souvent la caméra de la vue 3D qui est mal placée — un clic molette + glisser pour réorienter suffit, la
capture suivra.

## Lancer Blender

```bash
blender &            # la fenêtre s'ouvre ; le pont MCP démarre tout seul (panneau N → MCP for Blender)
```

La vue 3D te montre l'assistant travailler en direct. Un tour d'assistant qui passe par Blender peut prendre une
minute (chaque message relance l'agent hors écran et Blender exécute le code demandé) : c'est normal.

## Le moteur de repli

Sans le CLI `vibe` (ou avec `[assistant] moteur = "api"` dans `config.toml`), l'assistant retombe sur l'API
Mistral — il faut alors une clé (`api_key`, voir [Configuration](configuration.md)), et l'accès à Blender part.
