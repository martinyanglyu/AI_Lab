# mIHC Segmentation Pipeline

Single-cell **nuclear segmentation** and **expression quantification** for multiplex
immunohistochemistry (**mIHC**) fluorescence imaging. The pipeline takes an OME-TIFF
plus a channel-annotation CSV and produces nuclear masks, single-cell expression
matrices, spatial-neighbor data, and QC plots.

Everything runs inside a **Docker** container (GPU-accelerated). Two segmentation
models are supported, with **Cellpose** as the default (best for touching/overlapping
cells).

> **Note on model files:** The deep-learning model weights are **not** shipped in this
> repository. They are downloaded once from the official model hosts and mounted
> read-only into the container — see [Model Setup](#2-model-setup-required-once).

---

## Segmentation Models

| Model | Default | Best for | Approx. size | Model identifier |
|-------|---------|----------|--------------|------------------|
| **Cellpose** (nuclei) | **Yes** | Touching / overlapping cells (gradient flow) | ~1.2 GB | `nuclei` |
| StarDist (2D_versatile_fluo) | No | Well-separated cells (star-convex polygons) | ~5.6 MB | `2D_versatile_fluo` |

---

## Repository Layout

```
mIHC_segmentation/
├── README.md                       # This file
├── claude/
│   └── CLAUDE.md                   # Detailed workflow reference
├── docker/
│   └── Dockerfile.mihc             # Image build (StarDist + Cellpose)
├── env/
│   ├── mIHC_pipeline.sh            # Main controller (SSH/host driver)
│   ├── config_template.sh          # All tunable parameters
│   └── download_stardist_model.py  # One-time StarDist model fetch
├── PY_function/                    # Python steps
│   ├── predict_cellpose.py         # Cellpose DAPI segmentation  [DEFAULT]
│   ├── predict_vsi.py              # StarDist DAPI segmentation   [alt]
│   ├── prepare_mIHC_for_module2.py # OME-TIFF → per-channel TIFFs
│   ├── split_channels.py
│   ├── nuclear_dilation.py         # Nucleus → cell mask expansion
│   ├── remove_hotpixels_channel.py # Hot-pixel removal
│   ├── simple_seg_measurement.py   # Single-cell expression
│   ├── Generating_samplelist.py    # Auto sample list
│   └── generate_annotation.py      # File annotation report
└── sh_files/
    ├── Docker_run_mIHC_pipeline.sh # Docker launcher (model-aware mounts)
    └── mIHC_sc_pipeline.sh         # Pipeline body (runs inside container)
```

---

## Prerequisites

- **Docker** with the **NVIDIA Container Toolkit** (`--runtime=nvidia --gpus all`)
- An **NVIDIA GPU** + driver (CPU works but is much slower)
- Input data in a `Raw/` folder:
  - `Raw/<SAMPLE>_ome.tif` — OME-TIFF
  - `Raw/<SAMPLE>_a.csv` — channel annotation, e.g.:
    ```csv
    Channel,Channel Name,Emission Wavelength
    1,DAPI,455 nm
    2,CD163,518 nm
    ```

---

## How To Run

### 1. Pull (or build) the Docker image

```bash
# Pull the prebuilt image (StarDist + Cellpose preinstalled)
docker pull aibiologist/imc_mihc:v2

# --- OR build locally ---
docker build -f docker/Dockerfile.mihc -t aibiologist/imc_mihc:v2 .
```

### 2. Model Setup (required once)

Model weights are **not** in this repo. Download them once to a local folder and
mount that folder read-only at runtime (the container needs **no internet** during a run).

**Cellpose `nuclei` model (default)** — auto-downloaded by the Cellpose API to
`~/.cellpose/models`. Pre-fetch it into a chosen folder:

```bash
# Fetch the Cellpose 'nuclei' model once
python3 -c "from cellpose import models; models.CellposeModel(gpu=False, model_type='nuclei')"
# Weights land in ~/.cellpose/models  → mount this folder at /root/.cellpose/models
```

- Cellpose models are hosted by the Cellpose project: **https://www.cellpose.org/models**
- Docs: **https://cellpose.readthedocs.io**

**StarDist `2D_versatile_fluo` model (alternative)** — use the bundled helper:

```bash
python3 env/download_stardist_model.py /path/to/stardist_model
# → /path/to/stardist_model/2D_versatile_fluo  (mount at /mnt/stardist_model)
```

- StarDist pretrained models: **https://github.com/stardist/stardist-models**
- Docs: **https://stardist.net**

Point `config.sh` at wherever you saved the weights:

```bash
CELLPOSE_MODEL_WORKSTATION_PATH="/path/to/cellpose/models"   # → /root/.cellpose/models
STARDIST_MODEL_WORKSTATION_PATH="/path/to/stardist_model"    # → /mnt/stardist_model
```

### 3. Configure

Copy the template and tune parameters (model choice, thresholds, dilation, etc.):

```bash
cp env/config_template.sh config.sh
# edit config.sh:  SEG_MODEL="cellpose"   NUCLEAR_CHANNEL="DAPI"   INPUT_TIFF=...  INPUT_CSV=...
```

### 4. Run the pipeline

**Option A — one-shot controller** (validates inputs, builds the task folder, launches Docker):

```bash
bash env/mIHC_pipeline.sh <project> <task> <data_path> <ome_tiff> <channel_csv> [sample_list]

# Example
bash env/mIHC_pipeline.sh VSI_Test analysis \
    /path/to/data/VSI_Test \
    253066_MIX1_ome.tif \
    253066_MIX1_a.csv
```

**Option B — direct Docker launch** (when `config.sh` already exists in the task folder):

```bash
bash sh_files/Docker_run_mIHC_pipeline.sh /path/to/task_folder
```

This mounts (model mount chosen automatically from `SEG_MODEL`):

| Host | Container | Mode |
|------|-----------|------|
| Task folder | `/mnt` | rw — `config.sh`, results/ |
| `Raw/` | `/mnt/Raw` | rw — inputs |
| `sh_files/` | `/mnt/sh_files` | ro — pipeline scripts |
| `PY_function/` | `/mnt/PY_function` | ro — Python steps |
| Cellpose models | `/root/.cellpose/models` | ro — *if cellpose* |
| StarDist model | `/mnt/stardist_model` | ro — *if stardist* |

---

## Pipeline Steps (all automated)

1. Split OME-TIFF into per-channel TIFFs using the channel CSV
2. Locate the nuclear channel (`NUCLEAR_CHANNEL`, default `DAPI`)
3. Segment nuclei with the selected model (Cellpose or StarDist)
4. Dilate nuclei → cell masks (`nuclear_dilation_radius`)
5. Remove hot pixels from marker channels
6. Quantify single-cell expression (raw + hot-pixel-removed)
7. Compute spatial neighbor relationships (`N_neighbours`)
8. Generate QC plots and a file-annotation report

## Key Parameters (`config.sh`)

```bash
SEG_MODEL="cellpose"                 # "cellpose" (default) or "stardist"
NUCLEAR_CHANNEL="DAPI"

# Cellpose
CELLPOSE_DIAMETER=0                  # 0 = auto-estimate
CELLPOSE_FLOW_THRESH=0.4             # higher = more permissive
CELLPOSE_CELLPROB_THRESH=0.0         # lower  = detect more cells
CELLPOSE_MIN_SIZE=30

# StarDist
STARDIST_PROB_THRESH=""              # "" = model default (0.479)
STARDIST_NMS_THRESH=""               # "" = model default (0.3)
STARDIST_MIN_SIZE=50

# Shared post-processing
nuclear_dilation_radius=2
filter_size=3
hot_pixel_threshold=50
N_neighbours=5
```

## Outputs

- `postprocess_predictions/<image>_nuclear_mask.tiff` — labeled nuclear mask
- Single-cell expression matrices (raw + hot-pixel-removed)
- Spatial neighbor tables
- QC overlays / flow fields and a `file_annotation` report

---

## Software Stack

**Cellpose (default):** Cellpose 4.1.1 → PyTorch 2.4.1 → CUDA/cuDNN
**StarDist (alt):** StarDist 0.9.2 → CSBDeep → TensorFlow 2.9/Keras → CUDA/cuDNN

## Citation

- **Cellpose** — Stringer et al., *Nature Methods* (2021). https://www.cellpose.org
- **StarDist** — Schmidt et al., *MICCAI* (2018). https://stardist.net

