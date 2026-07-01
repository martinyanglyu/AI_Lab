#!/usr/bin/env python3
"""
prepare_mIHC_for_module2.py

Data preparation: Split multi-channel mIHC OME-TIFF into individual channel TIFFs
in the directory structure expected by the segmentation pipeline.

Can run in two modes:
  1. Single file mode: --tiff FILE --csv FILE --sample_id NAME
  2. Auto mode: --raw_dir DIR --output DIR (scans for all OME-TIFFs + matching CSVs)

Input:
  - OME-TIFF: multi-channel image (e.g., 253066_MIX1_ome.tif)
  - Channel CSV: maps channel index to marker name
    Required column: 'Channel Name'
    Example: Channel,Channel Name,Emission Wavelength,...

Output:
  results/SAMPLE_ID/roi_1/
    ├── full_stack/
    │   ├── DAPI.tiff
    │   ├── CD3.tiff
    │   └── ...
    └── nuclear/
        ├── DNA1.tiff  (copy of DAPI)
        └── DNA2.tiff  (copy of DAPI)

Usage:
    # Auto mode: scan Raw/ for all OME-TIFFs
    python3 prepare_mIHC_for_module2.py --raw_dir /mnt/Raw --output /mnt/results

    # Single file mode
    python3 prepare_mIHC_for_module2.py --tiff /path/to/ome.tif --csv /path/to/channels.csv \\
        --output /path/to/results --sample_id 253066_MIX1
"""

import os
import sys
import csv
import glob
import argparse


def find_matching_csv(tiff_path, raw_dir):
    """Find channel CSV matching a TIFF file by sample name prefix."""
    tiff_name = os.path.basename(tiff_path)
    # Strip common suffixes to get sample base name
    base = tiff_name
    for suffix in ['_ome.tif', '_ome.tiff', '.ome.tif', '.ome.tiff', '.tif', '.tiff']:
        if base.lower().endswith(suffix):
            base = base[:len(base) - len(suffix)]
            break

    # Search for CSV with matching prefix
    csv_candidates = glob.glob(os.path.join(raw_dir, f"{base}*.csv"))
    # Filter out Sample_list.csv and similar
    csv_candidates = [c for c in csv_candidates
                      if 'sample_list' not in os.path.basename(c).lower()
                      and 'Sample_list' not in os.path.basename(c)]

    if csv_candidates:
        return csv_candidates[0], base
    return None, base


def derive_sample_id(tiff_path):
    """Derive sample ID from TIFF filename."""
    name = os.path.basename(tiff_path)
    # Strip suffixes
    for suffix in ['_ome.tif', '_ome.tiff', '.ome.tif', '.ome.tiff', '.tif', '.tiff']:
        if name.lower().endswith(suffix):
            name = name[:len(name) - len(suffix)]
            break
    return name


def read_channel_names(csv_path):
    """Read channel names from CSV. Returns list of names in order."""
    channels = []
    with open(csv_path, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        # Find the column name for channel name (flexible)
        fieldnames = reader.fieldnames
        name_col = None
        for col in fieldnames:
            if 'channel name' in col.lower() or col.lower() == 'name':
                name_col = col
                break
        if not name_col:
            print(f"  WARNING: No 'Channel Name' column found in {csv_path}")
            print(f"  Available columns: {fieldnames}")
            return None

        for row in reader:
            channels.append(row[name_col].strip())
    return channels


def split_tiff(tiff_path, csv_path, output_dir, sample_id, nuclear_channel='DAPI'):
    """Split multi-channel TIFF into individual channel TIFFs."""
    try:
        import tifffile
    except ImportError:
        print("ERROR: tifffile not installed. Run: pip install tifffile")
        sys.exit(1)

    # Read channel names from CSV
    if csv_path and os.path.exists(csv_path):
        channel_names = read_channel_names(csv_path)
        if channel_names:
            print(f"  Channel CSV: {os.path.basename(csv_path)}")
            for i, name in enumerate(channel_names):
                print(f"    Ch{i+1}: {name}")
        else:
            channel_names = None
    else:
        channel_names = None
        print(f"  No channel CSV — will use generic names (channel_1, channel_2, ...)")

    # Create output directories
    roi_dir = os.path.join(output_dir, sample_id, "roi_1")
    nuclear_dir = os.path.join(roi_dir, "nuclear")
    full_stack_dir = os.path.join(roi_dir, "full_stack")

    # Check if already prepared
    if os.path.isdir(full_stack_dir):
        existing = glob.glob(os.path.join(full_stack_dir, "*.tiff"))
        if existing:
            print(f"  Already prepared: {len(existing)} channel TIFFs in full_stack/")
            return roi_dir, True

    os.makedirs(nuclear_dir, exist_ok=True)
    os.makedirs(full_stack_dir, exist_ok=True)

    # Read and split the multi-channel TIFF
    nuclear_found = False
    with tifffile.TiffFile(tiff_path) as tif:
        num_pages = len(tif.pages)
        print(f"  TIFF channels: {num_pages}")

        if channel_names and num_pages != len(channel_names):
            print(f"  WARNING: TIFF has {num_pages} channels but CSV has {len(channel_names)} entries")

        for i, page in enumerate(tif.pages):
            img = page.asarray()

            if channel_names and i < len(channel_names):
                ch_name = channel_names[i]
            else:
                ch_name = f"channel_{i+1}"

            # Save to full_stack
            out_file = os.path.join(full_stack_dir, f"{ch_name}.tiff")
            tifffile.imwrite(out_file, img, compression='deflate')
            size_kb = os.path.getsize(out_file) / 1024
            print(f"    Ch{i+1}: {ch_name}.tiff ({img.shape}, {size_kb:.0f} KB)")

            # Save nuclear channel as DNA1 + DNA2
            if ch_name.upper() == nuclear_channel.upper():
                dna1 = os.path.join(nuclear_dir, "DNA1.tiff")
                dna2 = os.path.join(nuclear_dir, "DNA2.tiff")
                tifffile.imwrite(dna1, img, compression='deflate')
                tifffile.imwrite(dna2, img, compression='deflate')
                print(f"      -> nuclear/DNA1.tiff + DNA2.tiff")
                nuclear_found = True

    if not nuclear_found:
        print(f"  ERROR: Nuclear channel '{nuclear_channel}' not found!")
        if channel_names:
            print(f"  Available: {channel_names}")
        sys.exit(1)

    return roi_dir, False


def main():
    parser = argparse.ArgumentParser(
        description='Prepare mIHC data: split OME-TIFF into channel TIFFs for pipeline')
    parser.add_argument('--raw_dir', type=str,
                        help='Raw data directory to scan for OME-TIFFs (auto mode)')
    parser.add_argument('--tiff', type=str,
                        help='Single OME-TIFF file (single file mode)')
    parser.add_argument('--csv', type=str,
                        help='Channel CSV file (single file mode, optional in auto mode)')
    parser.add_argument('--output', required=True,
                        help='Output results directory')
    parser.add_argument('--sample_id', type=str,
                        help='Sample ID (auto-derived from filename if not set)')
    parser.add_argument('--nuclear_channel', default='DAPI',
                        help='Nuclear channel name (default: DAPI)')
    args = parser.parse_args()

    print("=== mIHC Data Preparation ===")
    print()

    if args.raw_dir:
        # AUTO MODE: scan Raw/ for OME-TIFFs
        raw_dir = os.path.abspath(args.raw_dir)
        tiff_files = (glob.glob(os.path.join(raw_dir, "*.tif")) +
                      glob.glob(os.path.join(raw_dir, "*.tiff")))
        tiff_files = [f for f in tiff_files
                      if not os.path.basename(f).startswith('channel_')
                      and not os.path.basename(f).startswith('._')]

        if not tiff_files:
            print(f"ERROR: No TIFF files found in {raw_dir}")
            sys.exit(1)

        print(f"Found {len(tiff_files)} TIFF file(s) in {raw_dir}")
        print()

        total_prepared = 0
        total_skipped = 0
        for tiff_path in sorted(tiff_files):
            sample_id = derive_sample_id(tiff_path)
            csv_path, _ = find_matching_csv(tiff_path, raw_dir)

            print(f"Sample: {sample_id}")
            print(f"  TIFF: {os.path.basename(tiff_path)}")
            roi_dir, skipped = split_tiff(
                tiff_path, csv_path, args.output, sample_id, args.nuclear_channel)

            if skipped:
                total_skipped += 1
            else:
                total_prepared += 1
            print()

        print(f"=== Data Preparation Complete ===")
        print(f"  Prepared: {total_prepared} sample(s)")
        print(f"  Skipped (already done): {total_skipped} sample(s)")

    elif args.tiff:
        # SINGLE FILE MODE
        tiff_path = os.path.abspath(args.tiff)
        sample_id = args.sample_id or derive_sample_id(tiff_path)
        csv_path = args.csv

        if not csv_path:
            csv_path, _ = find_matching_csv(tiff_path, os.path.dirname(tiff_path))

        print(f"Sample: {sample_id}")
        print(f"  TIFF: {tiff_path}")
        split_tiff(tiff_path, csv_path, args.output, sample_id, args.nuclear_channel)
        print()
        print("=== Data Preparation Complete ===")

    else:
        parser.error("Either --raw_dir (auto mode) or --tiff (single file mode) is required")


if __name__ == '__main__':
    main()
