# config_template.sh - Configuration for AI_workflow_mIHC Pipeline
# Copy to Project/YOUR_PROJECT/Configs/config.sh and customize

# ============================================================================
# Project Configuration
# ============================================================================

# Working directory - SET AUTOMATICALLY BY PIPELINE (do not edit)
WORKING_DIR="__TASK_PATH__"

# ============================================================================
# Docker Images
# ============================================================================

# Docker image for mIHC segmentation and single-cell analysis
# imc_mihc:v2 = imc_sc:v1 + StarDist + Cellpose pre-installed
DOCKER_Image_sc="aibiologist/imc_mihc:v2"

# ============================================================================
# StarDist Model
# ============================================================================

# StarDist model path on workstation (mounted as /mnt/stardist_model in Docker)
STARDIST_MODEL_WORKSTATION_PATH="/path/to/Ref_models/stardist"

# ============================================================================
# Input Files (SET BY CONTROLLER — do not edit manually)
# ============================================================================

# OME-TIFF filename in Raw/ (multi-channel mIHC image)
INPUT_TIFF="__INPUT_TIFF__"

# Channel annotation CSV filename in Raw/ (maps channel index to marker name)
INPUT_CSV="__INPUT_CSV__"

# Sample list CSV (auto-generated from INPUT_TIFF if set to "auto")
# Set to a filename in Raw/ to use a user-provided sample list
INPUT_SAMPLE_LIST="__INPUT_SAMPLE_LIST__"

# ============================================================================
# Sample List (internal — used by Docker pipeline)
# ============================================================================

# Path inside Docker container (auto-generated or copied from INPUT_SAMPLE_LIST)
csv_file="/mnt/Sample_list.csv"

# ============================================================================
# Segmentation Model Selection
# ============================================================================

# Which segmentation model to use: "stardist" or "cellpose"
#   cellpose  — Cellpose nuclei model (gradient flow, best for touching cells) [DEFAULT]
#   stardist  — StarDist 2D_versatile_fluo (star-convex polygons, fast but weaker on touching cells)
SEG_MODEL="cellpose"

# Nuclear channel name in channel CSV (used for data prep and DAPI detection)
NUCLEAR_CHANNEL="DAPI"

# ============================================================================
# StarDist Parameters (used when SEG_MODEL="stardist")
# ============================================================================

# Probability threshold — higher = fewer but more confident detections
# Set to "" to use model default (0.479)
STARDIST_PROB_THRESH=""

# Non-maximum suppression threshold — higher = fewer overlapping detections
# Set to "" to use model default (0.3)
STARDIST_NMS_THRESH=""

# Minimum nucleus area in pixels — remove small false detections
STARDIST_MIN_SIZE=50

# Tile size for large images (auto-tiling if image > this)
STARDIST_TILE_SIZE=2048

# ============================================================================
# Cellpose Parameters (used when SEG_MODEL="cellpose")
# ============================================================================

# Cellpose model path on workstation (mounted as /root/.cellpose/models in Docker)
CELLPOSE_MODEL_WORKSTATION_PATH="/path/to/Ref_models/cellpose/models"

# Expected nucleus diameter in pixels (0 = auto-estimate from image)
CELLPOSE_DIAMETER=0

# Flow error threshold — higher = more permissive (keep more cells)
CELLPOSE_FLOW_THRESH=0.4

# Cell probability threshold — lower = detect more cells (including dim ones)
CELLPOSE_CELLPROB_THRESH=0.0

# Minimum nucleus area in pixels
CELLPOSE_MIN_SIZE=30

# ============================================================================
# Post-Segmentation Parameters
# ============================================================================

# Radius (in pixels) for nuclear dilation to create cell masks
nuclear_dilation_radius=2

# Hot pixel removal parameters
filter_size=3                    # Filter window size
hot_pixel_threshold=50          # Intensity threshold for hot pixel detection

# Number of neighbors for spatial analysis
N_neighbours=5

# ============================================================================
# Notes
# ============================================================================
# - WORKING_DIR, INPUT_TIFF, INPUT_CSV are set by the controller — do not edit
# - STARDIST_MODEL_WORKSTATION_PATH points to pre-downloaded model (no GitHub download)
# - Model structure: stardist/2D_versatile_fluo/{config.json, weights_best.h5, thresholds.json}
# - StarDist parameters: prob_thresh/nms_thresh="" means use model defaults
# - Docker image can be updated if newer versions are available
