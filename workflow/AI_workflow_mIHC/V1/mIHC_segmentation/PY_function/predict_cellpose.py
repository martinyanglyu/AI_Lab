#!/usr/bin/env python3
"""
predict_cellpose.py

Nuclear segmentation for mIHC DAPI fluorescence images using Cellpose.
Cellpose uses gradient flow-based segmentation which handles touching/overlapping
cells much better than star-convex polygon methods (StarDist).

Output directory structure (compatible with downstream pipeline):
  outdir/
  ├── raw/
  │   ├── cellpose_flows/          # Cellpose flow fields
  │   │   ├── {imagename}.png              # Input DAPI image
  │   │   └── {imagename}_flows.png        # X/Y gradient flows + cell probability
  │   └── cellpose_overlay/        # Segmentation overlay for visual QC
  │       ├── {imagename}_boundary_overlay.png  # Red boundaries on DAPI
  │       └── {imagename}_overlay.png           # Color label overlay on DAPI
  ├── postprocess_predictions/
  │   └── {imagename}_nuclear_mask.tiff    # Final labeled mask (uint16)
  └── LARGE_IMAGES.csv             # Flag for images that were tiled

Usage:
    python3 predict_cellpose.py \\
        --dapi /path/to/DAPI.tiff \\
        --outdir /path/to/roi_dir \\
        --imagename sample_roi \\
        [--diameter 0] \\
        [--flow_threshold 0.4] \\
        [--cellprob_threshold 0.0] \\
        [--min_size 30]
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


def segment_dapi_cellpose(dapi_image, diameter=0, flow_threshold=0.4,
                           cellprob_threshold=0.0, min_size=30, use_gpu=True):
    """
    Segment nuclei from a DAPI fluorescence image using Cellpose.

    Args:
        dapi_image: 2D numpy array (uint16 or uint8) - DAPI channel
        diameter: expected nucleus diameter in pixels (0 = auto-estimate)
        flow_threshold: max allowed error of flows for each mask (higher = more permissive)
        cellprob_threshold: cell probability threshold (lower = detect more cells)
        min_size: minimum nucleus area in pixels (default 30)
        use_gpu: try to use GPU if available

    Returns:
        labels: 2D labeled mask (uint16)
        flows: list of flow arrays [RGB_flows, dP, cellprob, p]
        diameters: estimated diameter
    """
    from cellpose import models

    print("  Input: shape=%s, dtype=%s, range=[%d, %d]" % (
          dapi_image.shape, dapi_image.dtype, dapi_image.min(), dapi_image.max()))

    # Load Cellpose nuclei model (API varies by version)
    print("  Loading Cellpose 'nuclei' model...")
    if hasattr(models, 'CellposeModel'):
        # Cellpose >= 4.x
        model = models.CellposeModel(gpu=use_gpu, model_type='nuclei')
    else:
        # Cellpose < 4.x
        model = models.Cellpose(gpu=use_gpu, model_type='nuclei')

    # Run segmentation
    print("  Running Cellpose prediction...")
    print("    diameter=%s, flow_threshold=%.2f, cellprob_threshold=%.2f, min_size=%d" % (
          str(diameter) if diameter > 0 else 'auto', flow_threshold, cellprob_threshold, min_size))

    masks, flows, styles = model.eval(
        dapi_image,
        diameter=diameter if diameter > 0 else None,
        flow_threshold=flow_threshold,
        cellprob_threshold=cellprob_threshold,
        min_size=min_size,
        channels=[0, 0]  # grayscale
    )
    diams = diameter if diameter > 0 else model.sz.mean() if hasattr(model, 'sz') else 0

    # Convert to uint16
    labels = masks.astype(np.uint16)

    print("  Cellpose detected: %d nuclei" % labels.max())
    if diameter == 0:
        print("  Auto-estimated diameter: %.1f pixels" % diams)

    return labels, flows, diams


def save_checking_outputs(dapi_image, labels, flows, outdir, imagename, diams):
    """
    Save QC/checking outputs compatible with downstream pipeline.

    Cellpose flows contain:
      flows[0]: RGB image of flows
      flows[1]: dP (2, Y, X) - flow field
      flows[2]: cellprob (Y, X) - cell probability
    """
    import skimage.io as io
    import tifffile
    import pandas as pd
    from skimage import color

    # Directory structure
    flow_dir = os.path.join(outdir, 'raw', 'cellpose_flows')
    overlay_dir = os.path.join(outdir, 'raw', 'cellpose_overlay')
    pp_dir = os.path.join(outdir, 'postprocess_predictions')

    for d in [flow_dir, overlay_dir, pp_dir]:
        os.makedirs(d, exist_ok=True)

    # Normalize DAPI for display
    dapi_display = normalize_image(dapi_image)
    dapi_uint8 = (dapi_display * 255).astype(np.uint8)

    # --- 1. Save flow fields ---
    io.imsave(os.path.join(flow_dir, '%s.png' % imagename), dapi_uint8, check_contrast=False)

    # flows[0] is RGB flow image from Cellpose
    if flows and len(flows) > 0:
        flow_rgb = flows[0]
        if flow_rgb is not None and flow_rgb.ndim == 3:
            flow_uint8 = flow_rgb.astype(np.uint8) if flow_rgb.max() > 1 else (flow_rgb * 255).astype(np.uint8)
            io.imsave(os.path.join(flow_dir, '%s_flows.png' % imagename), flow_uint8, check_contrast=False)

    # Save cell probability map
    if flows and len(flows) > 2:
        cellprob = flows[2]
        if cellprob is not None:
            cp_norm = np.clip((cellprob + 6) / 12, 0, 1)  # normalize from typical range [-6, 6]
            cp_uint8 = (cp_norm * 255).astype(np.uint8)
            io.imsave(os.path.join(flow_dir, '%s_cellprob.png' % imagename), cp_uint8, check_contrast=False)

    print("  Saved flow fields: raw/cellpose_flows/")

    # --- 2. Save color overlay (visual QC) ---
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

        print("  Saved overlays: raw/cellpose_overlay/")
    except Exception as e:
        print("  Warning: overlay generation failed: %s" % str(e))

    # --- 3. Save final nuclear mask ---
    mask_path = os.path.join(pp_dir, '%s_nuclear_mask.tiff' % imagename)

    print("")
    print("  Shape of mask: %s" % str(labels.shape))
    print("  Data type of mask: %s" % labels.dtype)
    print("  Min value in mask: %d" % np.min(labels))
    print("  Max value in mask: %d" % np.max(labels))

    tifffile.imwrite(mask_path, labels, compression='deflate')
    print("  Saved nuclear mask: postprocess_predictions/%s_nuclear_mask.tiff" % imagename)

    # --- 4. Save metadata ---
    large_df = pd.DataFrame({'diameter': [diams]})
    large_df.to_csv(os.path.join(outdir, 'LARGE_IMAGES.csv'), index=False)
    print("  Saved LARGE_IMAGES.csv (diameter=%.1f)" % diams)


def main():
    parser = argparse.ArgumentParser(
        description='Nuclear segmentation for mIHC DAPI using Cellpose')
    parser.add_argument('--dapi', required=True, help='Path to DAPI channel TIFF')
    parser.add_argument('--outdir', required=True, help='Output base directory (roi path)')
    parser.add_argument('--imagename', required=True, help='Image name prefix for output files')
    parser.add_argument('--diameter', type=float, default=0,
                        help='Expected nucleus diameter in pixels (0 = auto-estimate)')
    parser.add_argument('--flow_threshold', type=float, default=0.4,
                        help='Flow error threshold (default: 0.4, higher = more permissive)')
    parser.add_argument('--cellprob_threshold', type=float, default=0.0,
                        help='Cell probability threshold (default: 0.0, lower = detect more)')
    parser.add_argument('--min_size', type=int, default=30,
                        help='Minimum nucleus area in pixels (default: 30)')
    args = parser.parse_args()

    # Check input
    if not os.path.exists(args.dapi):
        print("ERROR: DAPI file not found: %s" % args.dapi)
        sys.exit(1)

    # Load DAPI
    from skimage import io as skio
    dapi = skio.imread(args.dapi)

    print("=== Nuclear Segmentation (Cellpose 'nuclei' model) ===")
    print("Input: %s" % args.dapi)
    print("Image name: %s" % args.imagename)

    if dapi.ndim > 2:
        dapi = np.squeeze(dapi)
    if dapi.ndim != 2:
        print("ERROR: Expected 2D image, got shape %s" % str(dapi.shape))
        sys.exit(1)

    # Segment
    labels, flows, diams = segment_dapi_cellpose(
        dapi,
        diameter=args.diameter,
        flow_threshold=args.flow_threshold,
        cellprob_threshold=args.cellprob_threshold,
        min_size=args.min_size
    )

    # Save outputs
    print("\nSaving outputs to: %s" % args.outdir)
    save_checking_outputs(dapi, labels, flows, args.outdir, args.imagename, diams)

    print("\n  Nuclei count: %d" % labels.max())
    print("=== Done ===")


if __name__ == '__main__':
    main()
