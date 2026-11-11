# Réglages (`config.toml`)

[← Retour au README](../README.fr.md) · 🇬🇧 [English](en/configuration.md)

Les réglages sont dans `config.toml`, à la racine du projet (ignoré par git, lisible par ton utilisateur seulement).
La plupart s'écrivent depuis l'atelier (onglet Démarrage, carte Machine, cloche des alertes…) : tu n'as pas besoin
de l'éditer à la main. `config.example.toml` sert de point de départ. Après une modification à la main, redémarre
l'atelier.

```toml
[printer]
host = "192.168.1.42"       # IP de la CC2 (fixe-la dans la box : bail DHCP statique)
access_code = "Ab12Cd"      # code d'accès affiché sur l'écran de l'imprimante (Paramètres → Réseau)
serial = "F01…"             # facultatif : numéro de série, évite une requête au démarrage

[dashboard]
port = 8787                 # port HTTP de l'atelier (le HTTPS du réseau est sur 8443 : cc2 dash --port-https)

[alertes]
ntfy = "https://ntfy.sh/mon-sujet"   # notifications sur le téléphone, appli fermée (voir guide Alertes) ; "" = coupé

[surveillance]              # carte « Surveillance par caméra » de l'onglet Imprimante
ia = true                   # IA anti-ratés pendant l'impression
pause_auto = false          # mettre en pause quand l'IA est sûre d'un raté
sensibilite = 1.0           # de 0.5 (moins d'alertes) à 2.0 (plus d'alertes)
timelapse = true            # une photo par couche, vidéo dans la galerie

[lancement]                 # options envoyées à la CC2 au départ (carte « Machine »)
bedlevel_force = false      # niveler tout le plateau avant chaque impression
printer_check = true        # vérifications de l'imprimante avant de démarrer
print_layout = "A"          # disposition A ou B
delay_video = false         # timelapse de l'imprimante elle-même

[assemblage]
jeu_mm = 0.15               # jeu des chevilles des pièces découpées (onglet Démarrage, étape 4)

[tranchage]
niveler = true              # false retire le nivellement du G-code : déconseillé, la CC2 nivelle alors tout le plateau

[slicer]
path = ""                   # autre slicer compatible OrcaSlicer (par défaut tools/orcaslicer, installé par make slicer)

[comfyui]
url = "http://127.0.0.1:8188"   # adresse de ComfyUI (voir guide ComfyUI)
hunyuan = false             # afficher les workflows Hunyuan3D (licence non valable dans l'UE)

[acces]                     # écrit par l'atelier : empreinte du code d'accès et secret des sessions. Ne pas modifier.
```

## Variables d'environnement

Elles passent avant `config.toml`, pratique pour un essai ou un deuxième atelier :

| Variable | Remplace |
|---|---|
| `CC2_CONFIG` | le chemin de `config.toml` |
| `CC2_MODELS` | le dossier de la bibliothèque (`models/`) |
| `CC2_HOST`, `CC2_ACCESS_CODE`, `CC2_SERIAL` | `[printer]` |
| `CC2_DASH_PORT` | `[dashboard] port` |
| `COMFYUI_URL` | `[comfyui] url` |

## Où sont les données

Tout est dans `models/`, à côté de tes fichiers :

| Fichier | Contenu |
|---|---|
| `.index.json` | la fiche de chaque G-code (modèle d'origine, durée, grammes, couleurs) |
| `.bobines.json`, `.mes_bobines.json` | stock et noms de tes bobines |
| `.galerie/` | une entrée par impression : photo, timelapse, alertes, bilan |
| `.photos/` | photos de fin d'impression et des alertes de l'IA |
| `.events.json` | le journal des alertes |
| `.queue.json` | la file d'attente |
| `.entretien.json` | le carnet d'entretien |
| `.plateau_vide.jpg` | la photo de référence du plateau vide |
| `.thumbs/`, `.repairs/`, `.retouches/` | vignettes, copies réparées, retouches au pinceau |
| `references/` | les images intermédiaires des générations IA |

À sauvegarder : `models/`, `config.toml` et `.certs/` (l'autorité de certification des téléphones).
