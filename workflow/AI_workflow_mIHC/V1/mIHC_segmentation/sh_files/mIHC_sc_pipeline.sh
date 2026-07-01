#!/bin/bash
################################################################################
# mIHC_sc_pipeline.sh
#
# Single-cell expression pipeline for mIHC (multiplex immunohistochemistry) data.
# Uses StarDist 2D_versatile_fluo from local mounted model (no GitHub download).
#
# Expected Docker mounts:
#   /mnt                  - task folder (config.sh, PY_function/, sh_files/)
#   /mnt/Raw              - raw data (OME-TIFF + channel CSV)
#   /mnt/results          - results directory (SAMPLE_ID/roi_N/...)
#   /mnt/stardist_model   - StarDist model (2D_versatile_fluo/)
#
# Expected directory structure (results/SAMPLE_ID/roi_N/):
#   nuclear/DAPI.tiff          - DAPI nuclear channel (or DNA1.tiff)
#   full_stack/*.tiff          - Individual marker channel TIFFs
#
# Outputs (in results/SAMPLE_ID/roi_N/):
#   postprocess_predictions/   - Nuclear mask + dilated cell mask
#   hotpixel_removed/          - Cleaned channel TIFFs
#   single_cell/Expression/    - Single-cell expression CSVs
#   single_cell/Expression_neighbours/ - Spatial neighbor data
#   single_cell/Nuclei_plot/   - QC plots
#   single_cell/Plot_channel/  - Marker intensity plots
#   single_cell/Segmentation_color/ - Segmentation overlay plots
#   raw/stardist_*/            - StarDist QC outputs
#   file_annotation.md         - Auto-generated file documentation
#
################################################################################

CONFIG_FILE="/mnt/config.sh"
if [ ! -f "$CONFIG_FILE" ]; then
    echo "ERROR: No config.sh file found at /mnt"
    exit 1
fi
source "$CONFIG_FILE"

PY_function_path="/mnt/PY_function"
STARDIST_MODEL_DIR="/mnt/stardist_model"

# ============================================================================
# Step 0a: Verify segmentation model
# ============================================================================
echo "Segmentation model: ${SEG_MODEL:-stardist}"

if [ "${SEG_MODEL:-stardist}" = "cellpose" ]; then
    python3 -c "import cellpose; v=getattr(cellpose,'__version__',getattr(cellpose,'version_str','unknown')); print('Cellpose', v)" || {
        echo "ERROR: Cellpose not found. Use Docker image aibiologist/imc_mihc:v2"
        exit 1
    }
else
    python3 -c "import stardist; print('StarDist', stardist.__version__)" || {
        echo "ERROR: StarDist not found. Use Docker image aibiologist/imc_mihc:v1"
        exit 1
    }
    # Verify local model
    if [ -d "${STARDIST_MODEL_DIR}/2D_versatile_fluo" ]; then
        echo "StarDist model found at: ${STARDIST_MODEL_DIR}/2D_versatile_fluo"
    else
        echo "WARNING: Local StarDist model not found at ${STARDIST_MODEL_DIR}/2D_versatile_fluo"
    fi
fi
echo ""

# ============================================================================
# Step 0b: Data Preparation — split OME-TIFF into channel TIFFs
# ============================================================================
# All input values loaded from config.sh: INPUT_TIFF, INPUT_CSV, INPUT_SAMPLE_LIST
if [ -z "${INPUT_TIFF:-}" ] || [ -z "${INPUT_CSV:-}" ]; then
    echo "ERROR: INPUT_TIFF and INPUT_CSV must be set in config.sh"
    echo "  These are set automatically by the controller (mIHC_pipeline.sh)"
    exit 1
fi

echo "Config values:"
echo "  INPUT_TIFF:        ${INPUT_TIFF}"
echo "  INPUT_CSV:         ${INPUT_CSV}"
echo "  INPUT_SAMPLE_LIST: ${INPUT_SAMPLE_LIST:-auto}"
echo ""

# Check if results/ already has channel TIFFs (data prep already done)
existing_tiffs=$(find /mnt/results -path "*/full_stack/*.tiff" 2>/dev/null | wc -l)

if [ "$existing_tiffs" -eq 0 ]; then
    echo "=========================================="
    echo "  Step 0b: Data Preparation"
    echo "  Splitting OME-TIFF into channel TIFFs"
    echo "=========================================="
    echo ""
    python3 ${PY_function_path}/prepare_mIHC_for_module2.py \
        --tiff "/mnt/Raw/${INPUT_TIFF}" \
        --csv "/mnt/Raw/${INPUT_CSV}" \
        --output /mnt/results \
        --nuclear_channel "${NUCLEAR_CHANNEL:-DAPI}"
    echo ""
else
    echo "Data preparation: already done ($existing_tiffs channel TIFFs found)"
    echo ""
fi

# ============================================================================
# Step 1: Sample list
# ============================================================================
# If user provided a sample list (copied by controller), use it
# If INPUT_SAMPLE_LIST != "auto" and file exists in Raw/, copy it
if [ "${INPUT_SAMPLE_LIST:-auto}" != "auto" ] && [ -f "/mnt/Raw/${INPUT_SAMPLE_LIST}" ]; then
    cp "/mnt/Raw/${INPUT_SAMPLE_LIST}" "$csv_file"
    echo "Using user-provided sample list: ${INPUT_SAMPLE_LIST}"
elif [ ! -f "$csv_file" ]; then
    echo "Generating sample list from ${INPUT_TIFF}..."
    python3 ${PY_function_path}/Generating_samplelist.py /mnt/Raw "$csv_file" /mnt/results
fi

# Clean up Windows line endings
new_csv="${csv_file%.csv}_new.csv"
if grep -q $'\r$' "$csv_file"; then
    tr -d '\r' < "$csv_file" > "$new_csv"
    echo "Cleaned line endings: $new_csv"
else
    new_csv="$csv_file"
fi

echo "=========================================="
echo "  mIHC Single-Cell Expression Pipeline"
echo "  Model: StarDist 2D_versatile_fluo"
echo "=========================================="
echo ""

# ============================================================================
# Step 2: Process each sample
# ============================================================================

tail -n +2 "$new_csv" | while IFS=$',\t' read -r raw_file_path metafile_path output_path; do
    # Derive sample ID from filename
    Slide_ID=$(basename "$raw_file_path")
    Slide_ID=${Slide_ID%%.mcd}
    Slide_ID=${Slide_ID%%.tif*}
    Slide_ID=${Slide_ID%%_ome}
    Slide_path="$output_path/$Slide_ID"

    echo "============================================================"
    echo "Processing sample: $Slide_ID"
    echo "Results path: $Slide_path"
    echo "============================================================"

    # Process each ROI
    for d in ${Slide_path}/*roi*; do
        [ -d "$d" ] || continue

        ROI_name=$(basename "$d")
        sample_name="${Slide_ID}_${ROI_name}"
        echo ""
        echo "--- ROI: $ROI_name ---"

        # ================================================================
        # Step 2a: Find nuclear channel (from config NUCLEAR_CHANNEL)
        # ================================================================
        NUC_NAME="${NUCLEAR_CHANNEL:-DAPI}"
        DAPI_path=""
        if [ -f "${d}/full_stack/${NUC_NAME}.tiff" ]; then
            DAPI_path="${d}/full_stack/${NUC_NAME}.tiff"
        elif [ -f "${d}/nuclear/DNA1.tiff" ]; then
            DAPI_path="${d}/nuclear/DNA1.tiff"
        elif [ -f "${d}/nuclear/${NUC_NAME}.tiff" ]; then
            DAPI_path="${d}/nuclear/${NUC_NAME}.tiff"
        fi

        if [ -z "$DAPI_path" ]; then
            echo "ERROR: Nuclear channel '${NUC_NAME}' not found in ${d}"
            continue
        fi
        echo "Nuclear channel (${NUC_NAME}): $DAPI_path"

        # ================================================================
        # Step 2b: Nuclear segmentation (model from config SEG_MODEL)
        # ================================================================
        mask="${d}/postprocess_predictions/${sample_name}_nuclear_mask.tiff"

        if [ ! -f "$mask" ]; then
            if [ "${SEG_MODEL:-stardist}" = "cellpose" ]; then
                echo "Running Cellpose segmentation..."
                PREDICT_CMD="python3 ${PY_function_path}/predict_cellpose.py \
                    --dapi $DAPI_path \
                    --outdir $d \
                    --imagename $sample_name \
                    --diameter ${CELLPOSE_DIAMETER:-0} \
                    --flow_threshold ${CELLPOSE_FLOW_THRESH:-0.4} \
                    --cellprob_threshold ${CELLPOSE_CELLPROB_THRESH:-0.0} \
                    --min_size ${CELLPOSE_MIN_SIZE:-30}"
            else
                echo "Running StarDist segmentation (local model)..."
                PREDICT_CMD="python3 ${PY_function_path}/predict_vsi.py \
                    --dapi $DAPI_path \
                    --outdir $d \
                    --imagename $sample_name \
                    --min_size ${STARDIST_MIN_SIZE:-50} \
                    --tile_size ${STARDIST_TILE_SIZE:-2048} \
                    --model_dir $STARDIST_MODEL_DIR"

                if [ -n "${STARDIST_PROB_THRESH:-}" ]; then
                    PREDICT_CMD="$PREDICT_CMD --prob_thresh $STARDIST_PROB_THRESH"
                fi
                if [ -n "${STARDIST_NMS_THRESH:-}" ]; then
                    PREDICT_CMD="$PREDICT_CMD --nms_thresh $STARDIST_NMS_THRESH"
                fi
            fi

            eval $PREDICT_CMD
        else
            echo "Nuclear mask already exists: $mask"
        fi

        if [ ! -f "$mask" ]; then
            echo "ERROR: Segmentation failed — mask not found: $mask"
            continue
        fi

        # ================================================================
        # Step 2c: Nuclear dilation
        # ================================================================
        cellmask="${d}/postprocess_predictions/${sample_name}_nuclear_mask_nuclear_dilation.tiff"

        if [ ! -f "$cellmask" ]; then
            echo "Running nuclear dilation (radius=${nuclear_dilation_radius})..."
            python3 ${PY_function_path}/nuclear_dilation.py \
                --input_mask "$mask" \
                --output_directory "${d}/postprocess_predictions" \
                --radius $nuclear_dilation_radius
        else
            echo "Cell mask already exists: $cellmask"
        fi

        # ================================================================
        # Step 2d: Hot pixel removal
        # ================================================================
        stack_dir="${d}/full_stack"
        hotpixel_remove_path="${d}/hotpixel_removed"

        tiff_count_stack=$(find "$stack_dir" -maxdepth 1 -type f -name "*.tiff" | wc -l)
        tiff_count_d=0
        if [ -d "$hotpixel_remove_path" ]; then
            tiff_count_d=$(find "$hotpixel_remove_path" -maxdepth 1 -type f -name "*.tiff" | wc -l)
        fi

        echo "Channel TIFFs (original): $tiff_count_stack"
        echo "Channel TIFFs (denoised): $tiff_count_d"

        if [ "$tiff_count_d" -ne "$tiff_count_stack" ]; then
            echo "Removing hot pixels..."
            python3 ${PY_function_path}/remove_hotpixels_channel.py \
                --input_dir "$stack_dir" \
                --outdir "$hotpixel_remove_path" \
                --filter_size $filter_size \
                --hot_pixel_threshold $hot_pixel_threshold \
                --file_extension '.tiff' 2>&1
        fi

        # ================================================================
        # Step 2e: Single-cell expression measurement
        # ================================================================
        mkdir -p "${d}/single_cell"

        # Raw expression
        outfile="${sample_name}.cells.csv"
        if [ ! -f "${d}/single_cell/Expression/${outfile}" ]; then
            echo "Measuring single cells (raw channels)..."
            python3 ${PY_function_path}/simple_seg_measurement.py \
                --input_dir "$stack_dir" \
                --output_dir "${d}/single_cell" \
                --label_image_path "$cellmask" \
                --output_file "$outfile" \
                --n_neighbours $N_neighbours
        else
            echo "Raw expression CSV already exists"
        fi

        # Hot-pixel-removed expression
        outfile="${sample_name}_hot_pixel_removal.cells.csv"
        if [ ! -f "${d}/single_cell/Expression/${outfile}" ]; then
            echo "Measuring single cells (hotpixel removed)..."
            python3 ${PY_function_path}/simple_seg_measurement.py \
                --input_dir "$hotpixel_remove_path" \
                --output_dir "${d}/single_cell" \
                --label_image_path "$cellmask" \
                --output_file "$outfile" \
                --n_neighbours $N_neighbours
        else
            echo "Hotpixel-removed expression CSV already exists"
        fi

        echo ""
        echo "--- ROI $ROI_name complete ---"
        echo ""

    done

    echo "============================================================"
    echo "Sample $Slide_ID complete!"
    echo "============================================================"
    echo ""

done

# Generate file annotations for all samples
echo "=========================================="
echo "  Generating File Annotations"
echo "=========================================="
python3 ${PY_function_path}/generate_annotation.py /mnt/results --model ${SEG_MODEL:-stardist}
echo ""

echo "=========================================="
echo "  Pipeline Complete!"
echo "=========================================="
