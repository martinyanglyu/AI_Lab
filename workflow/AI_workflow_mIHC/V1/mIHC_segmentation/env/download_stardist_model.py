#!/usr/bin/env python3
"""Download StarDist 2D_versatile_fluo model and copy to output directory."""

import os
import sys
import shutil

def main():
    output_dir = sys.argv[1] if len(sys.argv) > 1 else '/mnt/stardist_model'

    print("Installing stardist...")
    os.system("pip install stardist -q 2>/dev/null")

    from stardist.models import StarDist2D

    print("Downloading StarDist 2D_versatile_fluo model...")
    model = StarDist2D.from_pretrained('2D_versatile_fluo')

    src_dir = model.logdir
    print(f"Model source: {src_dir}")

    # List model files
    print("Model files:")
    for root, dirs, files in os.walk(src_dir):
        for f in files:
            fpath = os.path.join(root, f)
            rel = os.path.relpath(fpath, src_dir)
            size = os.path.getsize(fpath)
            print(f"  {rel}: {size} bytes")

    # Copy to output
    os.makedirs(output_dir, exist_ok=True)
    for root, dirs, files in os.walk(src_dir):
        for f in files:
            src = os.path.join(root, f)
            rel = os.path.relpath(src, src_dir)
            dst = os.path.join(output_dir, rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)

    print(f"Model copied to: {output_dir}")

    # Verify
    print("Verification:")
    for f in os.listdir(output_dir):
        print(f"  {f}")

if __name__ == '__main__':
    main()
