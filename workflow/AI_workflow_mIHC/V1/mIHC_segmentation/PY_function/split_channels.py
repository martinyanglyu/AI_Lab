#!/usr/bin/env python3
"""
Split multi-channel TIFF into individual channel TIFF files.

This script extracts each channel from a multi-page TIFF file (e.g., from VSI conversion)
and saves them as separate TIFF files with channel labels preserved in filenames.

Usage:
    python3 split_channels.py <input_tiff> [-o <output_dir>]

Example:
    python3 split_channels.py /workspace/Raw/ome.tif -o /workspace/results/channels
"""

import os
import sys
import argparse

def split_channels_tifffile(input_tif, output_dir):
    """
    Split multi-channel TIFF into individual channel files using tifffile.

    Args:
        input_tif (str): Path to input multi-channel TIFF file
        output_dir (str): Output directory for individual channel TIFFs

    Returns:
        bool: True if successful, False otherwise
    """
    try:
        import tifffile

        print(f"=== Splitting Multi-Channel TIFF ===")
        print(f"Input: {input_tif}")
        print(f"Output directory: {output_dir}")

        # Create output directory if it doesn't exist
        os.makedirs(output_dir, exist_ok=True)

        # Read the multi-page TIFF
        with tifffile.TiffFile(input_tif) as tif:
            num_pages = len(tif.pages)
            print(f"\nFound {num_pages} channels")

            # Extract channel labels if available
            channel_labels = []
            if tif.imagej_metadata and 'Labels' in tif.imagej_metadata:
                channel_labels = tif.imagej_metadata['Labels']
                print(f"Channel labels found: {len(channel_labels)}")

            # Split each channel
            for i, page in enumerate(tif.pages):
                # Read the page data
                img = page.asarray()

                # Generate output filename
                if i < len(channel_labels):
                    # Use the label as filename (clean it up)
                    label = channel_labels[i].replace('.tiff', '').replace('.tif', '')
                    output_file = os.path.join(output_dir, f"channel_{i+1:02d}_{label}.tif")
                else:
                    output_file = os.path.join(output_dir, f"channel_{i+1:02d}.tif")

                # Save as individual TIFF with compression
                tifffile.imwrite(output_file, img, compression='deflate')

                # Print stats
                file_size_kb = os.path.getsize(output_file) / 1024
                print(f"Channel {i+1}: {img.shape} dtype={img.dtype} -> {os.path.basename(output_file)} ({file_size_kb:.1f} KB)")

        print(f"\n✓ Successfully split {num_pages} channels into {output_dir}")
        return True

    except ImportError as e:
        print(f"ERROR: tifffile not available: {e}")
        print("Please install tifffile: pip install tifffile")
        return False
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    parser = argparse.ArgumentParser(
        description='Split multi-channel TIFF into individual channel files',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Split ome.tif in current directory
  python3 split_channels.py ome.tif

  # Split with custom output directory
  python3 split_channels.py /data/Raw/ome.tif -o /data/results/channels

  # Split using Docker (recommended)
  docker run --rm -v /path/to/data:/workspace channel_metadata:v1 \\
      python3 /workspace/split_channels.py /workspace/Raw/ome.tif -o /workspace/results/channels
"""
    )
    parser.add_argument(
        'input_tiff',
        help='Path to multi-channel TIFF file'
    )
    parser.add_argument(
        '-o', '--output',
        default='./channels',
        help='Output directory for individual channel TIFFs (default: ./channels)'
    )

    args = parser.parse_args()

    # Check input file exists
    if not os.path.exists(args.input_tiff):
        print(f"ERROR: Input file not found: {args.input_tiff}")
        sys.exit(1)

    # Split channels
    success = split_channels_tifffile(args.input_tiff, args.output)

    sys.exit(0 if success else 1)

if __name__ == '__main__':
    main()
