# AI generation with ComfyUI

[← Back to the README](../../README.md) · 🇫🇷 [Français](../comfyui.md)

Optional. The workshop can turn **a photo or a sentence into a coloured 3D model**, ready to go through the CANVAS. The
computing doesn't happen in the workshop: it asks a **[ComfyUI](https://github.com/comfyanonymous/ComfyUI)**, the free
image and 3D generation software, running on a machine with an **NVIDIA graphics card**. The workshop sends the photo or
text, waits, and files the resulting model in the library.

```
photo or text ──► workshop ──► ComfyUI (machine with a GPU) ──► coloured .glb model ──► library
```

The workshop's machine doesn't need a graphics card. ComfyUI can run on the same machine if it has one, or on another PC
at home.

## Requirements

- An **NVIDIA card with 16 GB of video memory**: that's the tested setup (RTX 5060 Ti 16 GB). Less may work for some
  workflows, without guarantee.
- **Several tens of GB of disk** for the models (less if you only install one).
- A **recent ComfyUI** (2026 or later): TRELLIS.2, Qwen Image Edit 2511 and Z-Image are built-in nodes there, with no
  extension to add.

## 1. Install ComfyUI

On the machine with the graphics card, follow the official installation:
<https://github.com/comfyanonymous/ComfyUI#installing> (ComfyUI Desktop on Windows, or the manual installation on
Linux). Check that it works by opening its interface (http://127.0.0.1:8188).

## 2. Download the models

The workshop's workflows come from **ComfyUI's official templates** (menu **Workflow → Browse Templates**). The easiest
way: open these templates once in ComfyUI; it lists the missing files and offers to download them to the right place.

| For | Look for this template |
|---|---|
| TRELLIS.2 (image or text to 3D) | "Pixal3D & TRELLIS.2: Image to Model" (the one the workshop's TRELLIS workflows come from) |
| Qwen Image Edit (photo to figurine) | "Qwen Image Edit" (version 2511) |
| Z-Image (text to image, for "text to 3D") | "Z-Image" |
| Hunyuan3D (optional, see the licence below) | "Hunyuan3D" |

Template names change between ComfyUI versions: if you can't find them, download the files below by hand (from their
Hugging Face pages) into the right subfolders.

The exact file names each workshop workflow expects:

| Workflow | Files |
|---|---|
| `trellis_image_vers_3d` | `trellis_2_int8_convrot.safetensors` (diffusion_models), `trellis_2_shape_vae_bf16.safetensors` and `trellis_2_texture_vae_bf16.safetensors` (vae), `dino_v3_L_naf_fp32.safetensors` (clip_vision), `birefnet.safetensors` (background removal) |
| `trellis_texte_vers_3d`, `trellis_texte_vers_3d_rapide` | the same, plus `z_image_turbo_bf16.safetensors` (diffusion_models), `qwen_3_4b.safetensors` (text_encoders), `ae.safetensors` (vae) |
| `photo_vers_figurine`, `photo_vers_figurine_3d` | `qwen_image_edit_2511_fp8mixed.safetensors` (diffusion_models), `qwen_2.5_vl_7b_fp8_scaled.safetensors` (text_encoders), `qwen_image_vae.safetensors` (vae), `Qwen-Image-Edit-2511-Lightning-4steps-V1.0-bf16.safetensors` (loras); then those of `trellis_image_vers_3d` |
| `hunyuan_image_vers_3d`, `hunyuan_texte_vers_3d` | `hunyuan_3d_v2.1.safetensors` (checkpoints); for text, also Z-Image's |

In brackets: the subfolder of `ComfyUI/models/`. If a workflow fails with "value not in list", one of these files is
missing or has another name.

## 3. Connect the workshop to ComfyUI

The workshop must be able to reach ComfyUI's address. Two cases:

- **ComfyUI on the same machine as the workshop**: nothing to do, the default address is `http://127.0.0.1:8188`.
- **ComfyUI on another PC at home**: start ComfyUI listening on the network (`python main.py --listen 0.0.0.0`, or the
  "listen on network" option of ComfyUI Desktop), then put its address in `config.toml`:

```toml
[comfyui]
url = "http://192.168.1.50:8188"
```

ComfyUI has no password: only open it to your home network, never to the Internet. Another option is an ssh tunnel to
the GPU machine, which makes ComfyUI appear locally: `ssh -N -L 8188:127.0.0.1:8188 gpu-machine` (the workshop then keeps
`http://127.0.0.1:8188`).

Check with `uv run cc2 doctor`: the ComfyUI line should show the graphics card.

## 4. Generate

In the workshop: **Générer avec l'IA** (generate with AI, at the top). Pick the workflow, give the photo or sentence,
and start. The window follows the progress; the model lands in the library, and its colours are mapped to spools like
any other file. If the workshop restarts during the computation, it picks up the tracking by itself.

| Workflow | Input | Result |
|---|---|---|
| `photo_vers_figurine_3d` | a photo (people, animal, object) | the photo redrawn as a figurine on a base, then the coloured 3D model |
| `photo_vers_figurine` | a photo | only the figurine image, to try (≈ 40 s on 16 GB) |
| `trellis_image_vers_3d` | a clean image of a single object | textured 3D model, painted in colours |
| `trellis_texte_vers_3d` | a description ("a small red dragon") | a reference image, then the 3D model |
| `trellis_texte_vers_3d_rapide` | a description | the same, faster and less detailed |
| `hunyuan_image_vers_3d`, `hunyuan_texte_vers_3d` | image / text | the shape only, without colours |

Expect a few minutes for a 3D model, depending on the card and the workflow.

Tips:

- A raw photo (busy background, people cut off, selfie) makes a poor 3D model: go through `photo_vers_figurine_3d`,
  which first redraws it as a clean figurine (people full-length, base, bold colours, plain background). The intermediate
  image is kept in `models/references/` and shown in the window.
- An AI model has no real unit: the workshop suggests 60 mm high. "Optimiser pour la CC2" repairs it if needed and lays
  it on its best face.

From the command line:

```bash
uv run cc2 gen trellis_texte_vers_3d --prompt "a small red dragon"
uv run cc2 gen trellis_image_vers_3d --image photo.png
```

## Model licences

- **TRELLIS.2**: MIT licence. It relies on DINOv3, under Meta's licence: read it before any commercial use.
- **Qwen Image Edit 2511**, **Z-Image**: published by Alibaba; check their licence on their Hugging Face page.
- **Hunyuan3D 2.1**: Tencent licence, which **does not apply in the European Union, the United Kingdom or South Korea**.
  Its workflows are hidden by default; `[comfyui] hunyuan = true` shows them again if you live elsewhere.

## Adding your own workflow

1. In ComfyUI, build a workflow that ends by saving a 3D file (`.glb`).
2. Export it in **API format** (menu Workflow → Export (API)) and put it in `workflows/MY_WORKFLOW.json`.
3. Describe its inputs in `workflows/MY_WORKFLOW.map.json`: for each one, the node number and the field name.

```json
{
  "image":  ["122", "image"],
  "prompt": ["9", "text"],
  "seed":   ["3", "seed"]
}
```

Only the inputs present are offered in the workshop. A `"next": "other_workflow"` field chains a second workflow with
the image produced by the first (that's how `photo_vers_figurine_3d` hands the figurine to TRELLIS.2).
