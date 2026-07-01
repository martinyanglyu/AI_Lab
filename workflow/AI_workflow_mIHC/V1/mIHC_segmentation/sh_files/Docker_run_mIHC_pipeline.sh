#!/bin/bash
################################################################################
# Docker_run_mIHC_pipeline.sh
#
# Docker launcher for mIHC single-cell expression pipeline.
# Mounts workflow scripts directly (no copy to task folder needed).
#
# Docker mounts:
#   Task folder        → /mnt          (config.sh, Sample_list.csv, results/)
#   Raw data           → /mnt/Raw
#   Workflow sh_files  → /mnt/sh_files  (pipeline scripts, read from workflow)
#   Workflow PY_function → /mnt/PY_function (Python functions, read from workflow)
#   StarDist model     → /mnt/stardist_model
#
# Must be run from workstation. Config.sh must exist in the task folder.
################################################################################

# Find config — can be called from anywhere, config path passed via WORKING_DIR env or first arg
if [ -n "${1:-}" ] && [ -f "${1}/config.sh" ]; then
    CONFIG_FILE="${1}/config.sh"
elif [ -f "${PWD}/config.sh" ]; then
    CONFIG_FILE="${PWD}/config.sh"
elif [ -f "$(dirname "$PWD")/config.sh" ]; then
    CONFIG_FILE="$(dirname "$PWD")/config.sh"
else
    echo "ERROR: config.sh not found"
    exit 1
fi
source "$CONFIG_FILE"

# Workflow paths on workstation (scripts are mounted directly into the container).
# Override WORKFLOW_BASE via env or config.sh to point at wherever the workflow
# scripts live on your host (e.g. an external drive or a network mount).
WORKFLOW_BASE="${WORKFLOW_BASE:-/path/to/AI_workflow_mIHC}"
WORKFLOW_SH="${WORKFLOW_BASE}/sh_files"
WORKFLOW_PY="${WORKFLOW_BASE}/PY_function"

# Model paths on the host (override via config.sh / env)
STARDIST_MODEL_PATH="${STARDIST_MODEL_WORKSTATION_PATH:-/path/to/Ref_models/stardist}"
CELLPOSE_MODEL_PATH="${CELLPOSE_MODEL_WORKSTATION_PATH:-/path/to/Ref_models/cellpose/models}"

# Verify workflow scripts exist
if [ ! -f "${WORKFLOW_SH}/mIHC_sc_pipeline.sh" ]; then
    echo "ERROR: Workflow scripts not found at ${WORKFLOW_SH}/"
    echo "Set WORKFLOW_BASE to the directory containing sh_files/ and PY_function/"
    exit 1
fi

# Verify StarDist model (only needed for stardist mode)
if [ "${SEG_MODEL:-stardist}" = "stardist" ] && [ ! -d "${STARDIST_MODEL_PATH}/2D_versatile_fluo" ]; then
    echo "ERROR: StarDist model not found at ${STARDIST_MODEL_PATH}/2D_versatile_fluo"
    exit 1
fi

# Determine Raw path based on mode (external mounts live under /media/)
if [[ "$WORKING_DIR" == *"/media/"* ]]; then
    # EXTERNAL DRIVE MODE
    EXTERNAL_BASE=$(echo "$WORKING_DIR" | sed 's|/task/.*||g')
    RAW_PATH="${EXTERNAL_BASE}/Raw"
    MODE="External Drive"
else
    # WORKFLOW-CENTRIC MODE
    PROJECT_PATH=$(echo "$WORKING_DIR" | sed 's|/task/.*||g')
    RAW_PATH="${PROJECT_PATH}/Raw"
    MODE="Workflow-Centric"
fi

echo "${MODE} Mode (${SEG_MODEL:-stardist})"
echo "  Task:       ${WORKING_DIR}"
echo "  Raw:        ${RAW_PATH}"
echo "  Results:    ${WORKING_DIR}/results (task-local)"
echo "  Scripts:    ${WORKFLOW_SH} (mounted)"
echo "  PY_function: ${WORKFLOW_PY} (mounted)"
if [ "${SEG_MODEL:-stardist}" = "stardist" ]; then
    echo "  Model:      ${STARDIST_MODEL_PATH}"
fi

# Remove stale container
docker rm -f mihc_sc_run 2>/dev/null

# Build mount arguments
DOCKER_MOUNTS="-v ${WORKING_DIR}:/mnt \
    -v ${RAW_PATH}:/mnt/Raw \
    -v ${WORKFLOW_SH}:/mnt/sh_files:ro \
    -v ${WORKFLOW_PY}:/mnt/PY_function:ro"

# Mount model based on selection
if [ "${SEG_MODEL:-stardist}" = "stardist" ]; then
    DOCKER_MOUNTS="${DOCKER_MOUNTS} -v ${STARDIST_MODEL_PATH}:/mnt/stardist_model:ro"
elif [ "${SEG_MODEL:-stardist}" = "cellpose" ]; then
    DOCKER_MOUNTS="${DOCKER_MOUNTS} -v ${CELLPOSE_MODEL_PATH}:/root/.cellpose/models:ro"
fi

docker run --runtime=nvidia --gpus all --rm \
    --name mihc_sc_run \
    ${DOCKER_MOUNTS} \
    $DOCKER_Image_sc /bin/bash /mnt/sh_files/mIHC_sc_pipeline.sh
