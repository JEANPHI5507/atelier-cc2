# Génération IA avec ComfyUI

[← Retour au README](../README.md)

Facultatif. L'atelier peut transformer **une photo ou une phrase en modèle 3D en couleurs**, prêt à passer par le
CANVAS. Le calcul ne se fait pas dans l'atelier : il demande à un **[ComfyUI](https://github.com/comfyanonymous/ComfyUI)**,
le logiciel libre de génération d'images et de 3D, qui tourne sur une machine avec une **carte graphique NVIDIA**.
L'atelier envoie la photo ou le texte, attend, et range le modèle obtenu dans la bibliothèque.

```
photo ou texte ──► atelier ──► ComfyUI (machine avec GPU) ──► modèle .glb en couleurs ──► bibliothèque
```

La machine de l'atelier n'a pas besoin de carte graphique. ComfyUI peut tourner sur la même machine si elle en a une,
ou sur un autre PC de la maison.

## Ce qu'il faut

- Une carte **NVIDIA avec 16 Go de mémoire vidéo** : c'est la configuration testée (RTX 5060 Ti 16 Go). Moins peut
  marcher pour certains workflows, sans garantie.
- **Plusieurs dizaines de Go de disque** pour les modèles (moins si tu n'en installes qu'un).
- Une version **récente de ComfyUI** (de 2026 ou plus) : TRELLIS.2, Qwen Image Edit 2511 et Z-Image y sont des nœuds
  intégrés, sans extension à ajouter.

## 1. Installer ComfyUI

Sur la machine avec la carte graphique, suis l'installation officielle :
<https://github.com/comfyanonymous/ComfyUI#installing> (ComfyUI Desktop sous Windows, ou l'installation manuelle sous
Linux). Vérifie qu'elle marche en ouvrant son interface (http://127.0.0.1:8188).

## 2. Télécharger les modèles

Les workflows de l'atelier viennent des **modèles de départ officiels de ComfyUI** (menu **Workflow → Parcourir les
modèles**, « Templates » en anglais). Le plus simple : ouvre ces modèles une fois dans ComfyUI, il affiche les fichiers
manquants et propose de les télécharger au bon endroit.

| Pour | Cherche dans les modèles de départ |
|---|---|
| TRELLIS.2 (image ou texte vers 3D) | « Pixal3D & TRELLIS.2: Image to Model » (celui d'où viennent les workflows TRELLIS de l'atelier) |
| Qwen Image Edit (photo vers figurine) | « Qwen Image Edit » (version 2511) |
| Z-Image (texte vers image, pour « texte vers 3D ») | « Z-Image » |
| Hunyuan3D (facultatif, voir la licence plus bas) | « Hunyuan3D » |

Les noms des modèles de départ changent avec les versions de ComfyUI : si tu ne les trouves pas, télécharge les
fichiers ci-dessous à la main (depuis leurs pages Hugging Face) dans les bons sous-dossiers.

Les noms exacts des fichiers attendus par chaque workflow de l'atelier :

| Workflow | Fichiers |
|---|---|
| `trellis_image_vers_3d` | `trellis_2_int8_convrot.safetensors` (diffusion_models), `trellis_2_shape_vae_bf16.safetensors` et `trellis_2_texture_vae_bf16.safetensors` (vae), `dino_v3_L_naf_fp32.safetensors` (clip_vision), `birefnet.safetensors` (détourage) |
| `trellis_texte_vers_3d`, `trellis_texte_vers_3d_rapide` | les mêmes, plus `z_image_turbo_bf16.safetensors` (diffusion_models), `qwen_3_4b.safetensors` (text_encoders), `ae.safetensors` (vae) |
| `photo_vers_figurine`, `photo_vers_figurine_3d` | `qwen_image_edit_2511_fp8mixed.safetensors` (diffusion_models), `qwen_2.5_vl_7b_fp8_scaled.safetensors` (text_encoders), `qwen_image_vae.safetensors` (vae), `Qwen-Image-Edit-2511-Lightning-4steps-V1.0-bf16.safetensors` (loras) ; puis ceux de `trellis_image_vers_3d` |
| `hunyuan_image_vers_3d`, `hunyuan_texte_vers_3d` | `hunyuan_3d_v2.1.safetensors` (checkpoints) ; pour le texte, aussi ceux de Z-Image |

Entre parenthèses : le sous-dossier de `ComfyUI/models/`. Si un workflow échoue avec « value not in list », c'est
qu'un de ces fichiers manque ou porte un autre nom.

## 3. Relier l'atelier à ComfyUI

L'atelier doit pouvoir joindre l'adresse de ComfyUI. Deux cas :

- **ComfyUI sur la même machine que l'atelier** : rien à faire, l'adresse par défaut est `http://127.0.0.1:8188`.
- **ComfyUI sur un autre PC de la maison** : lance ComfyUI en écoutant le réseau (`python main.py --listen 0.0.0.0`,
  ou l'option « écouter sur le réseau » de ComfyUI Desktop), puis indique son adresse dans `config.toml` :

```toml
[comfyui]
url = "http://192.168.1.50:8188"
```

ComfyUI n'a pas de mot de passe : ne l'ouvre qu'au réseau de la maison, jamais à Internet. Une autre solution est un
tunnel ssh vers la machine GPU, qui fait apparaître ComfyUI en local :
`ssh -N -L 8188:127.0.0.1:8188 machine-gpu` (l'atelier garde alors `http://127.0.0.1:8188`).

Vérifie avec `uv run cc2 doctor` : la ligne ComfyUI doit montrer la carte graphique.

## 4. Générer

Dans l'atelier : **Générer avec l'IA** (en haut). Choisis le workflow, donne la photo ou la phrase, et lance. La
fenêtre suit l'avancement ; le modèle arrive dans la bibliothèque, ses couleurs sont associées aux bobines comme pour
n'importe quel fichier. Si l'atelier redémarre pendant le calcul, il reprend le suivi tout seul.

| Workflow | Entrée | Résultat |
|---|---|---|
| `photo_vers_figurine_3d` | une photo (personnes, animal, objet) | la photo redessinée en figurine sur socle, puis le modèle 3D en couleurs |
| `photo_vers_figurine` | une photo | seulement l'image de la figurine, pour essayer (≈ 40 s sur 16 Go) |
| `trellis_image_vers_3d` | une image propre d'un objet seul | modèle 3D texturé et peint aux couleurs |
| `trellis_texte_vers_3d` | une description (« un petit dragon rouge ») | une image de référence, puis le modèle 3D |
| `trellis_texte_vers_3d_rapide` | une description | pareil, plus vite et moins détaillé |
| `hunyuan_image_vers_3d`, `hunyuan_texte_vers_3d` | image / texte | la forme seule, sans couleurs |

Compte quelques minutes pour un modèle 3D, selon la carte et le workflow.

Conseils :

- Une photo brute (fond chargé, personnes coupées, selfie) donne un mauvais 3D : passe par `photo_vers_figurine_3d`,
  qui la redessine d'abord en figurine propre (personnes en pied, socle, couleurs franches, fond uni). L'image
  intermédiaire est gardée dans `models/references/` et montrée dans la fenêtre.
- Un modèle IA n'a pas d'unité réelle : l'atelier propose 60 mm de haut. « Optimiser pour la CC2 » le répare s'il le
  faut et le pose sur sa meilleure face.

En ligne de commande :

```bash
uv run cc2 gen trellis_texte_vers_3d --prompt "un petit dragon rouge"
uv run cc2 gen trellis_image_vers_3d --image photo.png
```

## Licences des modèles

- **TRELLIS.2** : licence MIT. Il s'appuie sur DINOv3, sous licence Meta : relis-la avant un usage commercial.
- **Qwen Image Edit 2511**, **Z-Image** : publiés par Alibaba ; vérifie leur licence sur leur page Hugging Face.
- **Hunyuan3D 2.1** : licence Tencent, qui **ne s'applique pas dans l'Union européenne, au Royaume-Uni ni en Corée du
  Sud**. Ses workflows sont masqués par défaut ; `[comfyui] hunyuan = true` les réaffiche si tu es ailleurs.

## Ajouter ton propre workflow

1. Dans ComfyUI, construis un workflow qui se termine par l'enregistrement d'un fichier 3D (`.glb`).
2. Exporte-le au **format API** (menu Workflow → Exporter (API)) et pose-le dans `workflows/MON_WORKFLOW.json`.
3. Décris ses entrées dans `workflows/MON_WORKFLOW.map.json` : pour chacune, le numéro du nœud et le nom du champ.

```json
{
  "image":  ["122", "image"],
  "prompt": ["9", "text"],
  "seed":   ["3", "seed"]
}
```

Seules les entrées présentes sont proposées dans l'atelier. Un champ `"next": "autre_workflow"` enchaîne un second
workflow avec l'image produite par le premier (c'est ainsi que `photo_vers_figurine_3d` passe la figurine à TRELLIS.2).
