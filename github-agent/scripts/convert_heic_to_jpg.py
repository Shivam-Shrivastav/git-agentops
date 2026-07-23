#!/usr/bin/env python3
"""Convert HEIC images in a folder to JPG on macOS.

This script uses macOS's built-in `sips` command, so it does not require any
third-party Python packages.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


DEFAULT_INPUT_DIR = Path("/Users/shivamshrivastava/Downloads/Photos-1-001")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convert .heic/.HEIC files in a folder to .jpg files."
    )
    parser.add_argument(
        "input_dir",
        nargs="?",
        type=Path,
        default=DEFAULT_INPUT_DIR,
        help=f"Folder containing HEIC files. Defaults to {DEFAULT_INPUT_DIR}",
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        help="Folder for converted JPG files. Defaults to the input folder.",
    )
    parser.add_argument(
        "-r",
        "--recursive",
        action="store_true",
        help="Also convert HEIC files inside subfolders.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace existing JPG files with the same name.",
    )
    return parser.parse_args()


def find_heic_files(input_dir: Path, recursive: bool) -> list[Path]:
    pattern = "**/*" if recursive else "*"
    return sorted(
        path
        for path in input_dir.glob(pattern)
        if path.is_file() and path.suffix.lower() == ".heic"
    )


def output_path_for(source: Path, input_dir: Path, output_dir: Path, recursive: bool) -> Path:
    if recursive:
        relative_source = source.relative_to(input_dir)
        return output_dir / relative_source.with_suffix(".jpg")
    return output_dir / source.with_suffix(".jpg").name


def convert_file(source: Path, destination: Path, overwrite: bool) -> str:
    if destination.exists() and not overwrite:
        return "skipped"

    destination.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["sips", "-s", "format", "jpeg", str(source), "--out", str(destination)],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    return "converted"


def main() -> int:
    args = parse_args()
    input_dir = args.input_dir.expanduser().resolve()
    output_dir = (args.output_dir or input_dir).expanduser().resolve()

    if shutil.which("sips") is None:
        print("Error: this script requires macOS's built-in `sips` command.", file=sys.stderr)
        return 1

    if not input_dir.is_dir():
        print(f"Error: input folder does not exist: {input_dir}", file=sys.stderr)
        return 1

    files = find_heic_files(input_dir, args.recursive)
    if not files:
        print(f"No HEIC files found in {input_dir}")
        return 0

    converted = 0
    skipped = 0
    failed = 0

    for source in files:
        destination = output_path_for(source, input_dir, output_dir, args.recursive)
        try:
            status = convert_file(source, destination, args.overwrite)
        except subprocess.CalledProcessError as exc:
            failed += 1
            error = exc.stderr.strip() or "unknown conversion error"
            print(f"FAILED: {source} -> {error}", file=sys.stderr)
            continue

        if status == "converted":
            converted += 1
            print(f"Converted: {source.name} -> {destination}")
        else:
            skipped += 1
            print(f"Skipped existing: {destination}")

    print(
        f"Done. Converted: {converted}, skipped: {skipped}, failed: {failed}, total: {len(files)}"
    )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
