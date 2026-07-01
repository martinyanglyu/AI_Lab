#!/usr/bin/env python3
"""
generate_annotation.py

Generate file_annotation.md for each sample/ROI by scanning the results directory.
Auto-detects segmentation model (StarDist vs Deep-IMCyto) from directory contents.

Usage:
    python3 generate_annotation.py /path/to/results
    python3 generate_annotation.py /path/to/results --model stardist
    python3 generate_annotation.py /path/to/results --model deepimcyto
"""

import os
import sys
import argparse
import datetime


# ============================================================================
# Directory and file descriptions
# ============================================================================

DESCRIPTIONS = {
    'full_stack': {
        '_dir': 'Individual channel TIFF images extracted from the multi-channel OME-TIFF. Each file is a single marker channel used for single-cell expression quantification.',
    },
    'nuclear': {
        '_dir': 'Nuclear reference channels for segmentation pipeline compatibility. Created by prepare_mIHC_for_module2.py from the DAPI channel.',
        'DNA1.tiff': 'Copy of DAPI channel mapped to DNA1 for backward compatibility with Deep-IMCyto U-Net pipeline (which expects DNA1+DNA2 inputs from IMC metal-channel data).',
        'DNA2.tiff': 'Copy of DAPI channel mapped to DNA2. Identical to DNA1.tiff. When Deep-IMCyto preprocesses, it merges DNA1+DNA2 by addition.',
    },
    'raw': {
        '_dir': 'StarDist QC (quality control) diagnostic outputs from predict_vsi.py. Used to visually inspect and validate nuclear segmentation quality. This folder is unique to StarDist; Deep-IMCyto produces nuclear_preprocess/ instead.',
    },
    'raw/stardist_prob': {
        '_dir': 'StarDist probability maps. Each pixel shows the model confidence that it belongs to a nucleus center. Analogous to Deep-IMCyto edge_weighted_nuc/ output.',
        '_pattern_png': 'Raw DAPI input image (grayscale). Saved alongside prediction for side-by-side comparison.',
        '_pattern_predict': 'Per-pixel nucleus probability map. Brighter pixels = higher confidence of being near a nucleus center. Used internally by StarDist with prob_thresh (default 0.479) to filter detections.',
    },
    'raw/stardist_dist': {
        '_dir': 'StarDist distance maps. Each pixel encodes the predicted distance to the nearest nucleus boundary along multiple radial directions (star-convex polygon radii). Analogous to Deep-IMCyto boundaries/ output.',
        '_pattern_png': 'Raw DAPI input image (grayscale). For visual reference.',
        '_pattern_predict': 'Mean radial distance map across all 32 radial directions. Bright regions = large nuclei (farther from edge). Useful for checking if nuclear shapes are detected correctly.',
    },
    'raw/stardist_overlay': {
        '_dir': 'Segmentation overlays on the DAPI image. The most useful QC outputs for quick visual validation of segmentation accuracy.',
        '_pattern_boundary': 'Red nucleus boundaries drawn on the DAPI image. Best single image for QC: check that red contours match actual nuclear edges. Over-segmentation = extra boundaries inside nuclei; under-segmentation = merged nuclei without boundaries.',
        '_pattern_overlay': 'Color-coded label overlay on DAPI. Each detected nucleus filled with a unique random color. Useful for verifying individual nucleus separation and checking for merged cells.',
    },
    'nuclear_preprocess': {
        '_dir': 'Deep-IMCyto U-Net preprocessing output. DNA1+DNA2 channels merged and contrast-adjusted to create the input image for the U-Net segmentation model. This folder is unique to Deep-IMCyto; StarDist produces raw/ instead.',
        '_pattern_png': 'Contrast-adjusted merged nuclear image (PNG). Created by unet_preprocess.py: DNA1 + DNA2 addition, then percentile-based contrast adjustment. Used as direct input to predict.py for U-Net inference.',
    },
    'postprocess_predictions': {
        '_dir': 'Final segmentation masks after post-processing. These are the primary outputs used by downstream analysis (dilation, expression quantification).',
        '_pattern_nuclear_mask.tiff': 'Labeled nuclear mask (uint16 TIFF). Each pixel value is a unique integer label (0=background, 1..N=nucleus ID). Shape matches input image dimensions.',
        '_pattern_dilation.tiff': 'Dilated cell mask (uint16 TIFF). Nuclear mask expanded by nuclear_dilation_radius (default 2px) using skimage.segmentation.expand_labels. Approximates cell boundaries beyond the nucleus. Used for single-cell expression measurement.',
    },
    'hotpixel_removed': {
        '_dir': 'Channel TIFFs after hot pixel removal. Hot pixels (anomalously bright single pixels from detector noise) are clipped using a maximum filter. Parameters: filter_size=3, hot_pixel_threshold=50.',
        '_pattern_tiff': 'Denoised version of corresponding full_stack/ channel. Same dimensions and dtype. Hot pixels replaced with local maximum value from 3x3 neighborhood.',
    },
    'single_cell': {
        '_dir': 'Single-cell analysis outputs. Contains expression matrices, spatial neighbor data, and QC visualization plots. Generated by simple_seg_measurement.py.',
    },
    'single_cell/Expression': {
        '_dir': 'Single-cell expression matrices (CSV). Each row is one cell, columns are marker intensities and morphology features.',
        '_pattern_hot_pixel': 'Expression matrix measured from hotpixel_removed/ channels. Compare with raw to assess hot pixel impact on expression values.',
        '_pattern_cells.csv': 'Raw channel expression matrix. Columns: cell_id, centroid_x, centroid_y, area, + mean/median/std intensity per marker from full_stack/ channels. One row per segmented cell.',
    },
    'single_cell/Expression_neighbours': {
        '_dir': 'Spatial neighbor analysis. For each cell, identifies the k nearest neighbors (default k=5) based on centroid Euclidean distance.',
        '_pattern_neighbours': 'Neighbor data. Columns include neighbor IDs and distances for each cell. Used for spatial statistics and neighborhood composition analysis.',
    },
    'single_cell/Nuclei_plot': {
        '_dir': 'Nuclei position and morphology QC plots.',
        '_pattern_position': 'Scatter plot of all cell centroids (x,y). Shows spatial distribution of detected cells across the tissue.',
        '_pattern_standard_deviation': 'Bar chart of normalized standard deviation per marker across all cells. High std = heterogeneous expression; low std = uniform expression or technical artifact.',
    },
    'single_cell/Plot_channel': {
        '_dir': 'Marker expression intensity summary plots.',
        '_pattern_mean': 'Bar chart of normalized mean intensity per marker across all cells. Shows relative expression levels of each marker in the panel.',
    },
    'single_cell/Segmentation_color': {
        '_dir': 'Segmentation visualization from the measurement script.',
        '_pattern_seg_color': 'Color-coded segmentation map. Each cell filled with a unique color. Generated by simple_seg_measurement.py.',
    },
}


def detect_model(roi_dir):
    """Auto-detect segmentation model from directory contents."""
    if os.path.isdir(os.path.join(roi_dir, 'raw', 'cellpose_flows')):
        return 'cellpose'
    if os.path.isdir(os.path.join(roi_dir, 'raw', 'stardist_prob')):
        return 'stardist'
    if os.path.isdir(os.path.join(roi_dir, 'nuclear_preprocess')):
        return 'deepimcyto'
    return 'unknown'


def count_cells(roi_dir):
    """Count cells from the first .cells.csv found."""
    expr_dir = os.path.join(roi_dir, 'single_cell', 'Expression')
    if not os.path.isdir(expr_dir):
        return 0
    for f in os.listdir(expr_dir):
        if f.endswith('.cells.csv') and 'hot_pixel' not in f:
            fpath = os.path.join(expr_dir, f)
            with open(fpath) as fh:
                return sum(1 for _ in fh) - 1  # subtract header
    return 0


def get_image_shape(roi_dir):
    """Get image dimensions from a TIFF in full_stack/."""
    stack_dir = os.path.join(roi_dir, 'full_stack')
    if not os.path.isdir(stack_dir):
        return '?'
    for f in sorted(os.listdir(stack_dir)):
        if f.endswith('.tiff') and not f.startswith('._'):
            try:
                import tifffile
                img = tifffile.imread(os.path.join(stack_dir, f))
                return f'{img.shape[0]} x {img.shape[1]}'
            except ImportError:
                return '?'
            except Exception:
                return '?'
    return '?'


def get_file_desc(dir_key, fname):
    """Match a filename to its description using pattern matching."""
    if dir_key not in DESCRIPTIONS:
        return ''
    d = DESCRIPTIONS[dir_key]
    # Exact match first
    if fname in d:
        return d[fname]
    # Pattern matching
    for key, desc in d.items():
        if not key.startswith('_pattern'):
            continue
        suffix = key.replace('_pattern_', '')
        if suffix in fname:
            return desc
    return ''


def format_size(size):
    if size > 1024 * 1024:
        return f'{size / (1024 * 1024):.1f} MB'
    elif size > 1024:
        return f'{size / 1024:.1f} KB'
    return f'{size} B'


def generate_annotation(roi_dir, model, sample_name, roi_name):
    """Generate file_annotation.md for a single ROI directory."""
    cells = count_cells(roi_dir)
    shape = get_image_shape(roi_dir)
    channels = len([f for f in os.listdir(os.path.join(roi_dir, 'full_stack'))
                     if f.endswith('.tiff') and not f.startswith('._')]) if os.path.isdir(os.path.join(roi_dir, 'full_stack')) else 0

    model_name = 'StarDist 2D_versatile_fluo' if model == 'stardist' else 'Deep-IMCyto U-Net (TensorFlow)'

    lines = []
    lines.append('# File Annotation: Pipeline Outputs')
    lines.append('')
    lines.append(f'**Sample**: {sample_name} ({channels}-channel)')
    lines.append(f'**ROI**: {roi_name} ({shape} pixels)')
    lines.append(f'**Segmentation model**: {model_name} ({cells} cells detected)')
    lines.append(f'**Generated**: {datetime.datetime.now().strftime("%Y-%m-%d %H:%M")}')
    lines.append(f'**Pipeline**: AI_workflow_Deepcyto')
    lines.append('')
    lines.append('---')
    lines.append('')

    for root, dirs, files in sorted(os.walk(roi_dir)):
        rel = os.path.relpath(root, roi_dir)
        if rel == '.':
            continue
        # Skip macOS metadata dirs
        if any(part.startswith('.') for part in rel.split('/')):
            continue

        depth = rel.count('/')
        header_level = '##' + '#' * depth

        lines.append(f'{header_level} `{rel}/`')
        lines.append('')

        # Directory description
        if rel in DESCRIPTIONS and '_dir' in DESCRIPTIONS[rel]:
            lines.append(DESCRIPTIONS[rel]['_dir'])
            lines.append('')

        # Filter real files
        real_files = sorted([
            f for f in files
            if not f.startswith('._')
            and f != '.DS_Store'
            and not f.startswith('.fuse_hidden')
            and f != 'file_annotation.md'
            and f != 'LARGE_IMAGES.csv'
        ])

        if real_files:
            lines.append('| File | Size | Description |')
            lines.append('|------|------|-------------|')
            for fname in real_files:
                fpath = os.path.join(root, fname)
                try:
                    size_str = format_size(os.path.getsize(fpath))
                except OSError:
                    size_str = '?'
                desc = get_file_desc(rel, fname)
                lines.append(f'| `{fname}` | {size_str} | {desc} |')
            lines.append('')

    outpath = os.path.join(roi_dir, 'file_annotation.md')
    with open(outpath, 'w') as f:
        f.write('\n'.join(lines))

    return outpath, len(lines), cells


def main():
    parser = argparse.ArgumentParser(description='Generate file_annotation.md for pipeline results.')
    parser.add_argument('results_dir', help='Path to results directory (contains SAMPLE_ID/roi_N/ subdirs)')
    parser.add_argument('--model', choices=['stardist', 'deepimcyto', 'cellpose', 'auto'], default='auto',
                        help='Segmentation model (default: auto-detect)')
    args = parser.parse_args()

    results_dir = os.path.abspath(args.results_dir)
    if not os.path.isdir(results_dir):
        print(f'Error: {results_dir} is not a directory')
        sys.exit(1)

    total_annotated = 0
    for sample_name in sorted(os.listdir(results_dir)):
        sample_dir = os.path.join(results_dir, sample_name)
        if not os.path.isdir(sample_dir) or sample_name.startswith('.'):
            continue

        for roi_name in sorted(os.listdir(sample_dir)):
            roi_dir = os.path.join(sample_dir, roi_name)
            if not os.path.isdir(roi_dir) or not roi_name.startswith('roi_'):
                continue

            # Detect or use specified model
            if args.model == 'auto':
                model = detect_model(roi_dir)
            else:
                model = args.model

            outpath, num_lines, cells = generate_annotation(roi_dir, model, sample_name, roi_name)
            print(f'  {sample_name}/{roi_name}: {cells} cells, model={model} -> file_annotation.md ({num_lines} lines)')
            total_annotated += 1

    print(f'Done. Annotated {total_annotated} ROI(s).')


if __name__ == '__main__':
    main()
