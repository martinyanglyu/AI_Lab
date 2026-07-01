# AI_workflow_mIHC

## Samplesheet Sample-ID Policy (MANDATORY)

**Every samplesheet driving a pipeline run MUST use the datahub `specimen_id` as the `sample` column** (e.g. `MN-4-a_TumorR135_s207`) — never GTAC sample IDs, MGI library IDs, raw_nuc codes (`R140`), library IDs (`LIB146909`), cohort labels (`X0092-a`, `JH_2_038_d`), or FASTQ filename roots. These IDs are either re-used across batches or unknown to the datahub, so they break the provenance chain that joins pipeline outputs back to clinical metadata.

**If raw inputs use a non-specimen_id, transform BEFORE writing the samplesheet:**

1. **Preferred** — query the datahub via the `human-samples-datahub` agent (e.g. `specimen_id where raw_nuc='R140' AND seq_core_id='SR011055'`).
2. **Alternate** — read the project's authoritative QC CSV (`RNASEQ_QC_*.csv`, `WEX_QC_*.csv`, etc.) which carries `specimen_id` alongside `samplename` / `gtac_library_id`.
3. **Legacy projects** (not yet datahub-registered) — document the mapping in `Project_info.md` and write a deterministic translator at `task/<task>/translate_sample_ids.py`. **NEVER hand-edit the samplesheet** to "fix up" names.

Applies to all samplesheet-driven tools in this workflow (nf-core / Nextflow pipelines, custom shell drivers, R/Python analyses that emit per-sample result rows). Does **NOT** apply to FASTQ / BAM filenames on disk — only to the `sample` column.

---

## Overview

Single-cell segmentation and expression quantification pipeline for **multiplex immunohistochemistry (mIHC)** fluorescence imaging data. Supports two segmentation models with **Cellpose** as the default (best for touching cells).

Separated from AI_workflow_Deepcyto (which focuses on IMC/MCD data with Deep-IMCyto U-Net).

## Segmentation Models

| Model | Default | Cells Detected* | Best For | Model Size |
|-------|---------|-----------------|----------|-----------|
| **Cellpose** (nuclei) | **Yes** | **1637** | Touching/overlapping cells (gradient flow) | 1.2 GB |
| StarDist (2D_versatile_fluo) | No | 993 | Well-separated cells (star-convex polygon) | 5.6 MB |

*Benchmark on sample 253066_MIX1 (7-channel mIHC, 1160x1508 DAPI)

## Workflow Purpose

**Input**: OME-TIFF + channel annotation CSV (in Raw/ folder)

**Output**: Nuclear segmentation masks, single-cell expression matrices, spatial neighbor data, QC plots, file annotations.

**Pipeline steps** (all automated, all parameters from config.sh):
1. Split OME-TIFF into channel TIFFs using channel CSV for marker names
2. Find nuclear channel (NUCLEAR_CHANNEL, default DAPI)
3. Segment nuclei using selected model (local, no download at runtime)
4. Dilate nuclei to create cell masks
5. Remove hot pixels from marker channels
6. Quantify single-cell expression (raw + hotpixel-removed)
7. Calculate spatial neighbor relationships
8. Generate QC plots and file annotations

## Execution Mode

### Local Workstation via SSH (Active)
- **Workstation**: <user>@<workstation-host>
- **Docker image**: `aibiologist/imc_mihc:v2` (StarDist + Cellpose pre-installed)
- **Models**: Pre-downloaded, mounted read-only — no internet required at runtime
  - Cellpose: `/path/to/workstation-mount/Active/Ref_models/cellpose/models/`
  - StarDist: `/path/to/workstation-mount/Active/Ref_models/stardist/`

### Deep Learning Stacks

**Cellpose** (default):
```
Cellpose 4.1.1 (Python API)
  └── PyTorch 2.4.1 (backend)
        └── CUDA / cuDNN (GPU acceleration)
```

**StarDist** (alternative):
```
StarDist 0.9.2 (Python API)
  └── CSBDeep → TensorFlow 2.9 / Keras (backend)
        └── CUDA / cuDNN (GPU acceleration)
```

## Path Mappings (Mac <-> Workstation)

| Mac Path | Workstation Path | Description |
|----------|------------------|-------------|
| `/path/to/AI_lab_V1/Workflow/AI_workflow_mIHC` | `/path/to/workstation-mount/Active/AI_lab_V1/Workflow/AI_workflow_mIHC` | Workflow (may have SMB sync delay) |
| `/Volumes/external-drive/IMC_data/AI_workflow_mIHC` | `/media/external-drive/IMC_data/AI_workflow_mIHC` | Workflow scripts (reliable, Docker mounts from here) |
| `/path/to/Active/Ref_models/cellpose` | `/path/to/workstation-mount/Active/Ref_models/cellpose` | Cellpose model |
| `/path/to/Active/Ref_models/stardist` | `/path/to/workstation-mount/Active/Ref_models/stardist` | StarDist model |
| `/Volumes/external-drive/IMC_data/...` | `/media/external-drive/IMC_data/...` | External drive data |

## Main Controller Script

**Script**: `env/mIHC_pipeline.sh`

```bash
cd /path/to/AI_lab_V1/Workflow/AI_workflow_mIHC

bash env/mIHC_pipeline.sh <project> <task> <data_path> <ome_tiff> <channel_csv> [sample_list]
```

**Example**:
```bash
bash env/mIHC_pipeline.sh VSI_Test_260406 analysis \
    /Volumes/external-drive/IMC_data/VSI_Test_260406 \
    253066_MIX1_ome.tif \
    253066_MIX1_a.csv
```

**Arguments**:

| # | Argument | Required | Description |
|---|----------|----------|-------------|
| 1 | `project_name` | Yes | Project name |
| 2 | `task_name` | Yes | Task name |
| 3 | `external_data_path` | Yes | Path to data folder containing Raw/ |
| 4 | `ome_tiff` | Yes | OME-TIFF filename in Raw/ |
| 5 | `channel_csv` | Yes | Channel annotation CSV filename in Raw/ |
| 6 | `sample_list` | No | Sample_list.csv (auto-generated if omitted) |

**What it does**:
1. Validates input files (OME-TIFF + CSV) on workstation
2. Verifies segmentation model exists
3. Creates timestamped task folder with config.sh
4. Writes input filenames + parameters to config.sh
5. Launches Docker (scripts mounted from H_drive_5, not copied)
6. Pipeline reads all parameters from config.sh
7. Validates results

## Docker Architecture

Scripts are **mounted directly** from H_drive_5 — not copied to the task folder. Only `config.sh` and `Docker_run_mIHC_pipeline.sh` are in the task folder.

| Host Path | Container Path | Mode | Purpose |
|-----------|---------------|------|---------|
| Task folder | `/mnt` | rw | config.sh, Sample_list.csv, results/ |
| Raw/ | `/mnt/Raw` | rw | Input OME-TIFF + CSV |
| `AI_workflow_mIHC/sh_files/` | `/mnt/sh_files` | ro | Pipeline scripts (mounted) |
| `AI_workflow_mIHC/PY_function/` | `/mnt/PY_function` | ro | Python functions (mounted) |
| `Ref_models/cellpose/models/` | `/root/.cellpose/models` | ro | Cellpose model (if cellpose) |
| `Ref_models/stardist/` | `/mnt/stardist_model` | ro | StarDist model (if stardist) |

## Configuration (config_template.sh)

All parameters in one file. Controller writes input files; user tunes segmentation parameters.

### Model Selection
```bash
SEG_MODEL="cellpose"                       # "cellpose" (default) or "stardist"
DOCKER_Image_sc="aibiologist/imc_mihc:v2"  # v2 has both models
NUCLEAR_CHANNEL="DAPI"                     # Nuclear channel name in CSV
```

### Cellpose Parameters (default model)
```bash
CELLPOSE_MODEL_WORKSTATION_PATH="/path/to/workstation-mount/Active/Ref_models/cellpose/models"
CELLPOSE_DIAMETER=0                        # 0 = auto-estimate
CELLPOSE_FLOW_THRESH=0.4                   # Higher = more permissive
CELLPOSE_CELLPROB_THRESH=0.0               # Lower = detect more cells
CELLPOSE_MIN_SIZE=30                       # Minimum nucleus area (pixels)
```

### StarDist Parameters (alternative)
```bash
STARDIST_MODEL_WORKSTATION_PATH="/path/to/workstation-mount/Active/Ref_models/stardist"
STARDIST_PROB_THRESH=""                    # "" = model default (0.479)
STARDIST_NMS_THRESH=""                     # "" = model default (0.3)
STARDIST_MIN_SIZE=50
STARDIST_TILE_SIZE=2048
```

### Post-Segmentation Parameters (shared)
```bash
nuclear_dilation_radius=2                  # Cell mask expansion (pixels)
filter_size=3                              # Hot pixel filter window
hot_pixel_threshold=50                     # Hot pixel intensity threshold
N_neighbours=5                             # Spatial neighbor count
```

### Input Files (set by controller)
```bash
INPUT_TIFF="__INPUT_TIFF__"                # OME-TIFF filename
INPUT_CSV="__INPUT_CSV__"                  # Channel annotation CSV
INPUT_SAMPLE_LIST="__INPUT_SAMPLE_LIST__"  # "auto" or filename
```

## Directory Structure

```
AI_workflow_mIHC/
├── CLAUDE.md                      # This file
├── env/                           # Configuration and controller
│   ├── mIHC_pipeline.sh           # Main controller (SSH-based)
│   ├── config_template.sh         # All configurable parameters
│   └── download_stardist_model.py # One-time StarDist model download
├── PY_function/                   # Python utilities
│   ├── predict_cellpose.py        # Cellpose nuclear segmentation [DEFAULT]
│   ├── predict_vsi.py             # StarDist nuclear segmentation (alternative)
│   ├── prepare_mIHC_for_module2.py # OME-TIFF → channel TIFF split
│   ├── nuclear_dilation.py        # Expand nuclear masks
│   ├── remove_hotpixels_channel.py # Hot pixel removal
│   ├── simple_seg_measurement.py  # Single-cell expression
│   ├── generate_annotation.py     # Auto-generate file_annotation.md
│   ├── Generating_samplelist.py   # Auto-generate Sample_list.csv
│   └── split_channels.py         # Split multi-channel TIFF
├── sh_files/                      # Shell scripts
│   ├── Docker_run_mIHC_pipeline.sh # Docker launcher (model-aware mounts)
│   └── mIHC_sc_pipeline.sh       # Pipeline (runs inside Docker)
├── docker/
│   └── Dockerfile.mihc            # Dockerfile for imc_mihc images
├── ref_model/
│   └── stardist -> /path/to/Active/Ref_models/stardist
├── Project/                       # Project tracking
└── .claude/
    └── skills/
        └── mIHC_processing/
```

## Prerequisites for New Data

1. **Convert VSI to OME-TIFF**: Fiji + EvidentViewer (manual, Mac/Windows)
2. **Place in Raw/**: `Raw/SAMPLE_ome.tif` + `Raw/SAMPLE_a.csv`
3. **Channel CSV format**:
```csv
Channel,Channel Name,Emission Wavelength,...
1,DAPI,455 nm,...
2,CD163,518 nm,...
```

Data prep (OME-TIFF split) runs automatically inside the pipeline.

## Protected Folders

`/env`, `/PY_function`, `/sh_files` — do not edit during normal operations. Follow backup + documentation procedure if changes are needed.
