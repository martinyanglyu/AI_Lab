#!/bin/bash

################################################################################
# mIHC_pipeline.sh
# Main controller script for AI_workflow_mIHC
#
# Runs mIHC single-cell segmentation pipeline on local workstation via SSH.
# Uses StarDist 2D_versatile_fluo model (pre-downloaded, no GitHub dependency).
#
# Usage:
#   bash env/mIHC_pipeline.sh <project_name> <task_name> [external_data_path]
#
# Examples:
#   # External drive mode (mIHC data on an external drive)
#   bash env/mIHC_pipeline.sh VSI_Test_260406 pipeline_test /Volumes/external-drive/IMC_data/VSI_Test_260406
#
#   # Workflow-centric mode (data in workflow Project/)
#   bash env/mIHC_pipeline.sh MY_PROJECT analysis
#
# Author: AI_workflow_mIHC
# Created: 2026-04-13
################################################################################

set -e
set -u

################################################################################
# Configuration
################################################################################

# Local workflow paths.
# Defaults are derived from this script's location (env/ lives inside the
# workflow root); override Workflow_path / Local_path via env to relocate.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
Workflow_path="${Workflow_path:-$(cd "${SCRIPT_DIR}/.." && pwd)}"
Local_path="${Local_path:-${Workflow_path}}"

# Paths on the remote workstation (override to match your environment)
WORKSTATION_WORKFLOW_PATH="${WORKSTATION_WORKFLOW_PATH:-/path/to/AI_workflow_mIHC}"
WORKSTATION_STARDIST_MODEL="${WORKSTATION_STARDIST_MODEL:-/path/to/Ref_models/stardist}"

# SSH connection — supply your own connector script + auth file.
# WORKSTATION_SSH must accept:  --cmd "<remote command>"
Workstation_autho_path="${Workstation_autho_path:-${Local_path}/env/workstation_auth.txt}"
WORKSTATION_SSH="${WORKSTATION_SSH:-python3 ${Local_path}/PY_function/workstation_connect.py ${Workstation_autho_path}}"

################################################################################
# Command line arguments
################################################################################

Project_name="${1:-}"
Task_name="${2:-}"
External_data_path="${3:-}"
TIFF_file="${4:-}"              # Required: OME-TIFF filename in Raw/ (e.g., 253066_MIX1_ome.tif)
CSV_file="${5:-}"               # Required: Channel annotation CSV in Raw/ (e.g., 253066_MIX1_a.csv)
Sample_list_file="${6:-}"       # Optional: Sample_list.csv path (auto-generated if not provided)

if [[ -z "$Project_name" ]] || [[ -z "$Task_name" ]] || [[ -z "$TIFF_file" ]] || [[ -z "$CSV_file" ]]; then
    echo "Usage: $0 <project_name> <task_name> <external_data_path> <ome_tiff> <channel_csv> [sample_list.csv]"
    echo ""
    echo "Arguments:"
    echo "  project_name       - Project name (e.g., VSI_Test_260406)"
    echo "  task_name          - Task name (e.g., pipeline_test)"
    echo "  external_data_path - Path to data folder containing Raw/ (e.g., /Volumes/external-drive/IMC_data/VSI_Test_260406)"
    echo "  ome_tiff           - OME-TIFF filename in Raw/ (e.g., 253066_MIX1_ome.tif)"
    echo "  channel_csv        - Channel annotation CSV in Raw/ (e.g., 253066_MIX1_a.csv)"
    echo "  sample_list.csv    - Optional: Sample_list.csv (auto-generated from ome_tiff if omitted)"
    echo ""
    echo "Example:"
    echo "  $0 VSI_Test_260406 pipeline_test /Volumes/external-drive/IMC_data/VSI_Test_260406 253066_MIX1_ome.tif 253066_MIX1_a.csv"
    echo "  $0 VSI_Test_260406 pipeline_test /Volumes/external-drive/IMC_data/VSI_Test_260406 253066_MIX1_ome.tif 253066_MIX1_a.csv /path/to/Sample_list.csv"
    exit 1
fi

################################################################################
# Run Pipeline
################################################################################

echo ""
echo "================================================================================"
echo "  AI_workflow_mIHC: Single-Cell Segmentation Pipeline"
echo "  Model: StarDist 2D_versatile_fluo (local, no download)"
echo "================================================================================"
echo "Project:      $Project_name"
echo "Task:         $Task_name"
echo "OME-TIFF:     $TIFF_file"
echo "Channel CSV:  $CSV_file"
if [[ -n "$Sample_list_file" ]]; then
    echo "Sample List:  $Sample_list_file"
else
    echo "Sample List:  (auto-generate)"
fi

# Mount-point prefixes for an external drive shared between this host and the
# workstation. Override to match where the drive mounts on each machine.
LOCAL_DRIVE_PREFIX="${LOCAL_DRIVE_PREFIX:-/Volumes/external-drive}"
WORKSTATION_DRIVE_PREFIX="${WORKSTATION_DRIVE_PREFIX:-/media/external-drive}"

# Determine paths based on mode
if [[ -n "$External_data_path" ]]; then
    # EXTERNAL DRIVE MODE — translate the local mount prefix to the workstation's
    if [[ "$External_data_path" == "${LOCAL_DRIVE_PREFIX}"* ]]; then
        WORKSTATION_EXTERNAL_DATA="${External_data_path/#${LOCAL_DRIVE_PREFIX}/${WORKSTATION_DRIVE_PREFIX}}"
    elif [[ "$External_data_path" == "${WORKSTATION_DRIVE_PREFIX}"* ]]; then
        WORKSTATION_EXTERNAL_DATA="$External_data_path"
    else
        echo "Error: Unsupported external data path: $External_data_path"
        echo "       Set LOCAL_DRIVE_PREFIX / WORKSTATION_DRIVE_PREFIX to match your mounts."
        exit 1
    fi

    WORKSTATION_RAW_PATH="${WORKSTATION_EXTERNAL_DATA}/Raw"
    WORKSTATION_RESULTS_PATH="${WORKSTATION_EXTERNAL_DATA}/results"

    echo "External: $External_data_path"
    echo "Mode:     EXTERNAL DRIVE"
else
    # WORKFLOW-CENTRIC MODE
    WORKSTATION_PROJECT_PATH="${WORKSTATION_WORKFLOW_PATH}/Project/${Project_name}"
    WORKSTATION_RAW_PATH="${WORKSTATION_PROJECT_PATH}/Raw"

    echo "Mode:     WORKFLOW-CENTRIC"
fi
echo "================================================================================"
echo ""

# ============================================================================
# Step 0: Test SSH connection
# ============================================================================
echo "[Step 0] Testing SSH connection..."
${WORKSTATION_SSH} --cmd "echo 'Connected'" || {
    echo "Error: Cannot connect to workstation"
    exit 1
}
echo "✓ SSH connection successful"
echo ""

# ============================================================================
# Step 0.1: Verify input files on workstation
# ============================================================================
echo "[Step 0.1] Verifying input files..."
${WORKSTATION_SSH} --cmd "test -f ${WORKSTATION_RAW_PATH}/${TIFF_file}" || {
    echo "Error: OME-TIFF not found: ${WORKSTATION_RAW_PATH}/${TIFF_file}"
    exit 1
}
${WORKSTATION_SSH} --cmd "test -f ${WORKSTATION_RAW_PATH}/${CSV_file}" || {
    echo "Error: Channel CSV not found: ${WORKSTATION_RAW_PATH}/${CSV_file}"
    exit 1
}
echo "✓ Input files verified: ${TIFF_file}, ${CSV_file}"
echo ""

# ============================================================================
# Step 0.2: Verify StarDist model on workstation
# ============================================================================
echo "[Step 0.2] Verifying StarDist model..."
${WORKSTATION_SSH} --cmd "test -f ${WORKSTATION_STARDIST_MODEL}/2D_versatile_fluo/weights_best.h5" || {
    echo "Error: StarDist model not found at ${WORKSTATION_STARDIST_MODEL}/2D_versatile_fluo/"
    echo "Run: download_stardist_model.py to set up the model"
    exit 1
}
echo "✓ StarDist model verified"
echo ""

# ============================================================================
# Step 1: Create timestamped task folder
# ============================================================================
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
TASK_FOLDER="${TIMESTAMP}_${Task_name}"

if [[ -n "$External_data_path" ]]; then
    WORKSTATION_TASK_PATH="${WORKSTATION_EXTERNAL_DATA}/task/${TASK_FOLDER}"
    LOCAL_TASK_PATH="${External_data_path}/task/${TASK_FOLDER}"
else
    WORKSTATION_TASK_PATH="${WORKSTATION_PROJECT_PATH}/task/${TASK_FOLDER}"
    LOCAL_TASK_PATH="${Workflow_path}/Project/${Project_name}/task/${TASK_FOLDER}"
fi

echo "[Step 1] Creating task folder: ${TASK_FOLDER}"
${WORKSTATION_SSH} --cmd "mkdir -p ${WORKSTATION_TASK_PATH}/{Module2_mIHC_processing,results}"
# Copy only the Docker launcher to the task folder (everything else is mounted)
${WORKSTATION_SSH} --cmd "cp ${WORKSTATION_WORKFLOW_PATH}/sh_files/Docker_run_mIHC_pipeline.sh ${WORKSTATION_TASK_PATH}/ 2>/dev/null" || {
    # SMB not synced — copy via Mac mount
    cp "${Workflow_path}/sh_files/Docker_run_mIHC_pipeline.sh" "${LOCAL_TASK_PATH}/" 2>/dev/null
}
echo "✓ Task folder created"
echo ""

# ============================================================================
# Step 2: Set up config.sh (scripts mounted directly — no copy needed)
# ============================================================================
echo "[Step 2] Setting up configuration..."
if [[ -n "$External_data_path" ]]; then
    # Check if project has custom config
    HAS_CONFIG=$(${WORKSTATION_SSH} --cmd "test -f ${WORKSTATION_EXTERNAL_DATA}/Configs/config.sh && echo yes || echo no" 2>/dev/null | grep -E '^(yes|no)$' | head -1)
    if [[ "$HAS_CONFIG" == "yes" ]]; then
        ${WORKSTATION_SSH} --cmd "cp ${WORKSTATION_EXTERNAL_DATA}/Configs/config.sh ${WORKSTATION_TASK_PATH}/config.sh"
    else
        ${WORKSTATION_SSH} --cmd "cp ${WORKSTATION_WORKFLOW_PATH}/env/config_template.sh ${WORKSTATION_TASK_PATH}/config.sh"
    fi
else
    HAS_CONFIG=$(${WORKSTATION_SSH} --cmd "test -f ${WORKSTATION_PROJECT_PATH}/Configs/config.sh && echo yes || echo no" 2>/dev/null | grep -E '^(yes|no)$' | head -1)
    if [[ "$HAS_CONFIG" == "yes" ]]; then
        ${WORKSTATION_SSH} --cmd "cp ${WORKSTATION_PROJECT_PATH}/Configs/config.sh ${WORKSTATION_TASK_PATH}/config.sh"
    else
        ${WORKSTATION_SSH} --cmd "cp ${WORKSTATION_WORKFLOW_PATH}/env/config_template.sh ${WORKSTATION_TASK_PATH}/config.sh"
    fi
fi
# Set all config values via sed replacement
SAMPLE_LIST_VALUE="auto"
if [[ -n "$Sample_list_file" ]]; then
    SAMPLE_LIST_VALUE="${Sample_list_file}"
fi

${WORKSTATION_SSH} --cmd "
    sed -i 's|__TASK_PATH__|${WORKSTATION_TASK_PATH}|g' ${WORKSTATION_TASK_PATH}/config.sh
    sed -i 's|__INPUT_TIFF__|${TIFF_file}|g' ${WORKSTATION_TASK_PATH}/config.sh
    sed -i 's|__INPUT_CSV__|${CSV_file}|g' ${WORKSTATION_TASK_PATH}/config.sh
    sed -i 's|__INPUT_SAMPLE_LIST__|${SAMPLE_LIST_VALUE}|g' ${WORKSTATION_TASK_PATH}/config.sh
"

# If user provided a sample list file, copy it to the task folder
if [[ -n "$Sample_list_file" ]] && [[ "$Sample_list_file" != "auto" ]]; then
    echo "[Step 3.1] Copying user-provided Sample_list.csv..."
    if [[ "$Sample_list_file" == "${LOCAL_DRIVE_PREFIX}"* ]]; then
        WORKSTATION_SAMPLE_LIST="${Sample_list_file/#${LOCAL_DRIVE_PREFIX}/${WORKSTATION_DRIVE_PREFIX}}"
        ${WORKSTATION_SSH} --cmd "cp ${WORKSTATION_SAMPLE_LIST} ${WORKSTATION_TASK_PATH}/Sample_list.csv"
    elif [[ -f "$Sample_list_file" ]]; then
        cp "$Sample_list_file" "${LOCAL_TASK_PATH}/Sample_list.csv" 2>/dev/null
    fi
    echo "✓ Sample_list.csv copied"
fi
echo "✓ Config ready (TIFF=${TIFF_file}, CSV=${CSV_file}, SampleList=${SAMPLE_LIST_VALUE})"
echo ""

# ============================================================================
# Step 4: Run pipeline via Docker
# ============================================================================
echo "[Step 4] Running mIHC segmentation pipeline..."
echo ""
echo "Pipeline will automatically:"
echo "  1. Split OME-TIFF into channel TIFFs (using channel CSV)"
echo "  2. Generate Sample_list.csv"
echo "  3. Run StarDist DAPI segmentation (local model)"
echo "  4. Nuclear dilation + hot pixel removal + SC expression"
echo ""
echo "Docker mounts:"
echo "  Task folder    → /mnt          (config.sh, results/)"
echo "  Raw data       → /mnt/Raw"
echo "  sh_files       → /mnt/sh_files  (mounted from workflow, read-only)"
echo "  PY_function    → /mnt/PY_function (mounted from workflow, read-only)"
echo "  StarDist model → /mnt/stardist_model (read-only)"
echo ""

${WORKSTATION_SSH} --cmd "docker rm -f mihc_sc_run 2>/dev/null; bash ${WORKSTATION_TASK_PATH}/Docker_run_mIHC_pipeline.sh ${WORKSTATION_TASK_PATH} 2>&1 | tee ${WORKSTATION_TASK_PATH}/Module2_mIHC_processing/sc_pipeline.log"

echo ""
echo "✓ Pipeline completed"
echo ""

# ============================================================================
# Step 5: Validation
# ============================================================================
echo "[Step 5] Validation..."
cells_count=$(${WORKSTATION_SSH} --cmd "find ${WORKSTATION_TASK_PATH}/results -name '*.cells.csv' 2>/dev/null | wc -l" 2>/dev/null | grep -E '^[0-9]+$' | head -1 | tr -d ' ')
cells_count=${cells_count:-0}
tiff_count=$(${WORKSTATION_SSH} --cmd "find ${WORKSTATION_TASK_PATH}/results -name '*.tiff' 2>/dev/null | wc -l" 2>/dev/null | grep -E '^[0-9]+$' | head -1 | tr -d ' ')
tiff_count=${tiff_count:-0}
annotation_count=$(${WORKSTATION_SSH} --cmd "find ${WORKSTATION_TASK_PATH}/results -name 'file_annotation.md' 2>/dev/null | wc -l" 2>/dev/null | grep -E '^[0-9]+$' | head -1 | tr -d ' ')
annotation_count=${annotation_count:-0}

echo "Results:"
echo "  - TIFF files: ${tiff_count}"
echo "  - Single-cell CSV files: ${cells_count}"
echo "  - File annotations: ${annotation_count}"
echo ""

echo "================================================================================"
echo "  mIHC Pipeline Complete!"
echo "================================================================================"
echo "Task Folder:  ${TASK_FOLDER}"
echo "Local Path:   ${LOCAL_TASK_PATH}"
echo "Workstation:  ${WORKSTATION_TASK_PATH}"
echo "Model:        StarDist 2D_versatile_fluo (local)"
echo "Results:      results/*/roi_*/single_cell/Expression/*.cells.csv"
echo "Logs:         Module2_mIHC_processing/sc_pipeline.log"
echo "Annotations:  results/*/roi_*/file_annotation.md"
echo "================================================================================"
echo ""
