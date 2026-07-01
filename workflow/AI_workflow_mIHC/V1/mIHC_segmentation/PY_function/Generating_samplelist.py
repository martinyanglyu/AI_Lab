# python3
# -*- coding: utf-8 -*-
"""
Generate Sample_list.csv for mIHC pipeline.
Scans Raw/ folder for TIFF files and creates CSV mapping for Docker pipeline.
Metadata CSV is optional (auto-generated if missing).
"""

import os
import glob
import re
import csv
import argparse


def generate_csv(input_folder, output_csv_path='/mnt/Sample_list.csv', output_dir='/mnt/results'):
    raw_path = os.path.abspath(input_folder)

    # Find TIFF input files (mIHC: OME-TIFF from VSI conversion)
    tiff_files = (glob.glob(os.path.join(raw_path, "*.tif")) +
                  glob.glob(os.path.join(raw_path, "*.tiff")) +
                  glob.glob(os.path.join(raw_path, "*.ome.tif")))
    # Filter out channel split outputs
    tiff_files = [f for f in tiff_files if not os.path.basename(f).startswith('channel_')]

    if not tiff_files:
        raise FileNotFoundError("No .tif/.tiff files found in the input folder.")

    # Find metadata CSV (optional for mIHC)
    all_csv_files = glob.glob(os.path.join(raw_path, "*.csv"))
    metadata_files = [f for f in all_csv_files if re.search(r"metadata", os.path.basename(f), re.IGNORECASE)]
    metadata_file = metadata_files[0] if metadata_files else None

    # Also check for channel CSV (e.g., 253066_MIX1_a.csv)
    if not metadata_file:
        channel_csvs = [f for f in all_csv_files if not re.search(r"sample|list", os.path.basename(f), re.IGNORECASE)]
        metadata_file = channel_csvs[0] if channel_csvs else None

    # Compute Docker output path: host mounts (external drive under /media/,
    # network share under /mnt/share/) are mapped to /mnt/results in the container.
    if output_dir.startswith('/media/') or output_dir.startswith('/mnt/share/'):
        docker_output_path = "/mnt/results"
    else:
        docker_output_path = output_dir

    # Write CSV rows using Docker mount paths
    rows = []
    for tiff_file in tiff_files:
        filename = os.path.basename(tiff_file)
        docker_input_path = f"/mnt/Raw/{filename}"
        docker_metadata_path = f"/mnt/Raw/{os.path.basename(metadata_file)}" if metadata_file else ""

        rows.append({
            "raw_file_path": docker_input_path,
            "metafile_path": docker_metadata_path,
            "output_path": docker_output_path
        })

    with open(output_csv_path, mode="w", newline="") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=["raw_file_path", "metafile_path", "output_path"])
        writer.writeheader()
        writer.writerows(rows)

    print(f"CSV generated: {output_csv_path}")
    print(f"Total TIFF files listed: {len(rows)}")
    if metadata_file:
        print(f"Metadata/channel CSV: {os.path.basename(metadata_file)}")
    else:
        print(f"No metadata CSV found (pipeline will auto-detect channels from filenames)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate Sample_list.csv for mIHC pipeline (TIFF inputs).")
    parser.add_argument("input_folder", help="Folder containing .tif/.tiff files (e.g. /mnt/Raw)")
    parser.add_argument("output_csv", nargs='?', default='/mnt/Sample_list.csv',
                        help="Output CSV file path (default: /mnt/Sample_list.csv)")
    parser.add_argument("output_dir", nargs='?', default='/mnt/results',
                        help="Output directory for results (default: /mnt/results)")
    args = parser.parse_args()

    generate_csv(args.input_folder, args.output_csv, args.output_dir)
