#!/usr/bin/env python3
"""
predict_vsi.py

Deep learning nuclear segmentation for mIHC DAPI fluorescence images.

Uses StarDist 2D_versatile_fluo model (pretrained on fluorescence microscopy)
instead of Deep-IMCyto U-Net (trained on IMC metal-channel data).

Produces the same output structure and QC checking outputs as the original
predict.py for consistency and visual inspection:

Output directory structure (mirrors original predict.py):
  outdir/
  ├── raw/
  │   ├── stardist_prob/           # StarDist probability map (like edge_weighted_nuc/)
  │   │   ├── {imagename}.png              # Input DAPI image
  │   │   └── {imagename}_predict.png      # Probability map
  │   ├── stardist_dist/           # StarDist distance map (like boundaries/)
  │   │   ├── {imagename}.png              # Input DAPI image
  │   │   └── {imagename}_predict.png      # Mean distance map
  │   └── stardist_overlay/        # Segmentation overlay for visual QC
  │       └── {imagename}_overlay.png      # Color overlay on DAPI
  ├── postprocess_predictions/
  │   └── {imagename}_nuclear_mask.tiff    # Final labeled mask
  └── LARGE_IMAGES.csv             # Flag for images that were tiled

Usage:
    python3 predict_vsi.py \
        --dapi /path/to/DAPI.tiff \
        --outdir /path/to/roi_dir \
        --imagename sample_roi \
        [--prob_thresh 0.5] \
        [--nms_thresh 0.3] \
        [--min_size 50] \
        [--tile_size 2048]
"""

import argparse
import os
import sys
import numpy as np


def normalize_image(img):
    """Normalize image to 0-1 float range with percentile clipping."""
    p_low, p_high = np.percentile(img, (1, 99.8))
    img_norm = (img.astype(np.float32) - p_low) / max(p_high - p_low, 1e-6)
    img_norm = np.clip(img_norm, 0, 1)
    return img_norm


def segment_dapi_stardist(dapi_image, prob_thresh=None, nms_thresh=None,
                          min_size=50, tile_size=2048, model_dir=None):
    """
    Segment nuclei from a DAPI fluorescence image using StarDist 2D_versatile_fluo.

    Args:
        dapi_image: 2D numpy array (uint16 or uint8) - DAPI channel
        prob_thresh: probability threshold (None = use model default ~0.48)
        nms_thresh: NMS threshold (None = use model default ~0.3)
        min_size: minimum nucleus area in pixels (default 50)
        tile_size: tile size for large images (default 2048)

    Returns:
        labels: 2D labeled mask (uint16)
        details: dict with 'prob' (probability map) and 'dist' (distance maps)
    """
    from stardist.models import StarDist2D
    from skimage import morphology, measure
    from csbdeep.utils import normalize

    print("  Input: shape=%s, dtype=%s, range=[%d, %d]" % (
          dapi_image.shape, dapi_image.dtype, dapi_image.min(), dapi_image.max()))

    # Load pretrained model for fluorescence data
    # model_dir should be basedir containing 2D_versatile_fluo/ subfolder
    # e.g., /mnt/stardist_model/ which contains 2D_versatile_fluo/{config.json, weights_best.h5, thresholds.json}
    if model_dir and os.path.isdir(os.path.join(model_dir, '2D_versatile_fluo')):
        print("  Loading StarDist model from local path: %s/2D_versatile_fluo" % model_dir)
        model = StarDist2D(None, name='2D_versatile_fluo', basedir=model_dir)
    else:
        print("  Loading StarDist 2D_versatile_fluo model (downloading from GitHub)...")
        model = StarDist2D.from_pretrained('2D_versatile_fluo')

    # Normalize image (percentile-based, standard for fluorescence)
    img_norm = normalize(dapi_image, 1, 99.8, axis=(0, 1))
    print("  Normalized: range=[%.3f, %.3f]" % (img_norm.min(), img_norm.max()))

    # Determine if tiling is needed
    max_dim = max(dapi_image.shape)
    is_large = max_dim > tile_size

    # Build predict kwargs
    predict_kwargs = {}
    if prob_thresh is not None:
        predict_kwargs['prob_thresh'] = prob_thresh
    if nms_thresh is not None:
        predict_kwargs['nms_thresh'] = nms_thresh

    if is_large:
        print("  Large image (%dpx) - using tiled prediction (tile=%d)" % (max_dim, tile_size))
        predict_kwargs['n_tiles'] = model._guess_n_tiles(img_norm)

    # Run prediction
    print("  Running StarDist prediction...")
    labels, details = model.predict_instances(img_norm, **predict_kwargs)
    n_raw = labels.max()
    print(f"  StarDist detected: {n_raw} nuclei")

    # Post-processing: remove small objects
    if min_size > 0:
        labels = morphology.remove_small_objects(labels, min_size=min_size)
        labels = measure.label(labels > 0)
        print(f"  After removing objects < {min_size}px: {labels.max()} nuclei")

    return labels.astype(np.uint16), details, is_large


def save_checking_outputs(dapi_image, labels, details, outdir, imagename, is_large):
    """
    Save QC/checking outputs matching original predict.py structure.

    StarDist details contain per-object data (not pixel maps):
      - 'prob': (N,) per-nucleus probability scores
      - 'coord': (N, 2, 32) polygon coordinates (32 rays)
      - 'points': (N, 2) nucleus centroids

    We generate 2D maps from these for visual QC:
      raw/stardist_prob/     - per-pixel probability (painted from per-object probs)
      raw/stardist_dist/     - distance-to-boundary map from labeled mask
      raw/stardist_overlay/  - color segmentation overlay on DAPI
      postprocess_predictions/ - final labeled nuclear mask
      LARGE_IMAGES.csv       - flag for tiled images
    """
    import skimage.io as io
    import tifffile
    import pandas as pd
    from skimage import color
    from scipy import ndimage

    # Directory structure matching original predict.py
    prob_dir = os.path.join(outdir, 'raw', 'stardist_prob')
    dist_dir = os.path.join(outdir, 'raw', 'stardist_dist')
    overlay_dir = os.path.join(outdir, 'raw', 'stardist_overlay')
    pp_dir = os.path.join(outdir, 'postprocess_predictions')

    for d in [prob_dir, dist_dir, overlay_dir, pp_dir]:
        os.makedirs(d, exist_ok=True)

    # Normalize DAPI for display
    dapi_display = normalize_image(dapi_image)
    dapi_uint8 = (dapi_display * 255).astype(np.uint8)

    # --- 1. Save probability map (like edge_weighted_nuc/) ---
    # StarDist prob is per-object (1D). Paint each nucleus with its probability.
    prob_scores = details.get('prob', None)
    if prob_scores is not None and len(prob_scores) > 0:
        # Build 2D probability image: each labeled pixel gets its object's prob score
        prob_2d = np.zeros(dapi_image.shape, dtype=np.float32)
        for obj_id in range(1, labels.max() + 1):
            if obj_id <= len(prob_scores):
                prob_2d[labels == obj_id] = prob_scores[obj_id - 1]

        io.imsave(os.path.join(prob_dir, '%s.png' % imagename), dapi_uint8, check_contrast=False)
        prob_uint8 = (np.clip(prob_2d, 0, 1) * 255).astype(np.uint8)
        io.imsave(os.path.join(prob_dir, '%s_predict.png' % imagename), prob_uint8, check_contrast=False)
        print("  Saved probability map: raw/stardist_prob/")

    # --- 2. Save distance map (like boundaries/) ---
    # Generate distance transform from labeled mask boundaries
    binary_mask = labels > 0
    distance = ndimage.distance_transform_edt(binary_mask)
    if distance.max() > 0:
        dist_uint8 = ((distance / distance.max()) * 255).astype(np.uint8)
    else:
        dist_uint8 = np.zeros_like(dapi_uint8)

    io.imsave(os.path.join(dist_dir, '%s.png' % imagename), dapi_uint8, check_contrast=False)
    io.imsave(os.path.join(dist_dir, '%s_predict.png' % imagename), dist_uint8, check_contrast=False)
    print("  Saved distance map: raw/stardist_dist/")

    # --- 3. Save color overlay (visual QC) ---
    try:
        from skimage.segmentation import find_boundaries

        # Boundary overlay: DAPI + red boundaries
        overlay = color.gray2rgb(dapi_display)
        boundaries = find_boundaries(labels, mode='thick')
        overlay[boundaries] = [1, 0, 0]

        boundary_overlay = (np.clip(overlay, 0, 1) * 255).astype(np.uint8)
        io.imsave(os.path.join(overlay_dir, '%s_boundary_overlay.png' % imagename), boundary_overlay, check_contrast=False)

        # Label-colored overlay
        label_overlay = color.label2rgb(labels, image=dapi_display, bg_label=0, alpha=0.3)
        overlay_uint8 = (np.clip(label_overlay, 0, 1) * 255).astype(np.uint8)
        io.imsave(os.path.join(overlay_dir, '%s_overlay.png' % imagename), overlay_uint8, check_contrast=False)

        print("  Saved overlays: raw/stardist_overlay/")
    except Exception as e:
        print("  Warning: overlay generation failed: %s" % str(e))

    # --- 4. Save final nuclear mask (same as original) ---
    mask_path = os.path.join(pp_dir, '%s_nuclear_mask.tiff' % imagename)

    # Print mask stats (same as original predict.py)
    print("")
    print("  Shape of mask: %s" % str(labels.shape))
    print("  Data type of mask: %s" % labels.dtype)
    print("  Min value in mask: %d" % np.min(labels))
    print("  Max value in mask: %d" % np.max(labels))

    tifffile.imwrite(mask_path, labels, compression='deflate')
    print("  Saved nuclear mask: postprocess_predictions/%s_nuclear_mask.tiff" % imagename)

    # --- 5. Save LARGE_IMAGES.csv (same as original) ---
    large_img_list = [dapi_image.shape] if is_large else []
    large_df = pd.DataFrame(large_img_list)
    large_df.to_csv(os.path.join(outdir, 'LARGE_IMAGES.csv'))
    print("  Saved LARGE_IMAGES.csv (large_image=%s)" % is_large)


def main():
    parser = argparse.ArgumentParser(
        description='Deep learning nuclear segmentation for mIHC DAPI fluorescence')
    parser.add_argument('--dapi', required=True, help='Path to DAPI channel TIFF')
    parser.add_argument('--outdir', required=True, help='Output base directory (roi path)')
    parser.add_argument('--imagename', required=True, help='Image name prefix for output files')
    parser.add_argument('--prob_thresh', type=float, default=None,
                        help='StarDist probability threshold (default: model default ~0.48)')
    parser.add_argument('--nms_thresh', type=float, default=None,
                        help='StarDist NMS threshold (default: model default ~0.3)')
    parser.add_argument('--min_size', type=int, default=50,
                        help='Minimum nucleus area in pixels (default: 50)')
    parser.add_argument('--tile_size', type=int, default=2048,
                        help='Tile size for large images (default: 2048)')
    parser.add_argument('--model_dir', type=str, default=None,
                        help='Path to local StarDist model directory (skip download if set)')
    args = parser.parse_args()

    # Check input
    if not os.path.exists(args.dapi):
        print(f"ERROR: DAPI file not found: {args.dapi}")
        sys.exit(1)

    # Load DAPI
    from skimage import io as skio
    dapi = skio.imread(args.dapi)

    print(f"=== VSI Nuclear Segmentation (StarDist 2D_versatile_fluo) ===")
    print(f"Input: {args.dapi}")
    print(f"Image name: {args.imagename}")

    if dapi.ndim > 2:
        dapi = np.squeeze(dapi)
    if dapi.ndim != 2:
        print(f"ERROR: Expected 2D image, got shape {dapi.shape}")
        sys.exit(1)

    # Segment
    labels, details, is_large = segment_dapi_stardist(
        dapi,
        prob_thresh=args.prob_thresh,
        nms_thresh=args.nms_thresh,
        min_size=args.min_size,
        tile_size=args.tile_size,
        model_dir=args.model_dir
    )

    # Save all outputs (mask + checking/QC)
    print(f"\nSaving outputs to: {args.outdir}")
    save_checking_outputs(dapi, labels, details, args.outdir, args.imagename, is_large)

    print(f"\n  Nuclei count: {labels.max()}")
    print(f"=== Done ===")


if __name__ == '__main__':
    main()
