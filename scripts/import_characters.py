#!/usr/bin/env python3
"""Bulk import character reference images.

Takes a folder of images named like:
  john_doe_01.png
  john_doe_02.png
  sarah_smith_01.png
  ...

And creates character folders with metadata files.

Usage:
  python scripts/import_characters.py --input /path/to/character_faces/ --output data/characters/
  python scripts/import_characters.py --input /path/to/character_faces/ --interactive
"""

import argparse
import json
import sys
from pathlib import Path


def parse_arguments():
    parser = argparse.ArgumentParser(
        description="Bulk import character reference images"
    )
    parser.add_argument("--input", "-i", type=str, required=True,
                        help="Folder containing character face images")
    parser.add_argument("--output", "-o", type=str, default="data/characters",
                        help="Output folder for character data (default: data/characters)")
    parser.add_argument("--interactive", action="store_true",
                        help="Prompt for character descriptions interactively")
    parser.add_argument("--name-format", type=str, default="{id}_{num}",
                        help="Image naming format: {id}_{num}.png (default)")
    return parser.parse_args()


def detect_characters(input_path: Path):
    image_extensions = {".png", ".jpg", ".jpeg", ".webp"}
    images = sorted([
        f for f in input_path.iterdir()
        if f.suffix.lower() in image_extensions
    ])

    if not images:
        print(f"No image files found in {input_path}")
        return {}

    characters = {}
    for img in images:
        stem = img.stem
        parts = stem.split("_")

        if len(parts) >= 2 and parts[-1].isdigit():
            char_id = "_".join(parts[:-1])
            image_num = int(parts[-1])
        else:
            char_id = stem
            image_num = 1

        if char_id not in characters:
            characters[char_id] = []
        characters[char_id].append((image_num, img.name))

    for char_id in characters:
        characters[char_id].sort(key=lambda x: x[0])

    return characters


def import_characters(input_path: Path, output_path: Path, interactive: bool = False):
    output_path.mkdir(parents=True, exist_ok=True)

    characters = detect_characters(input_path)

    if not characters:
        return 0

    print(f"\nDetected {len(characters)} characters:")
    for char_id, images in sorted(characters.items()):
        names = [img[1] for img in images]
        print(f"  {char_id}: {len(images)} image(s) — {', '.join(names)}")

    imported_count = 0
    for char_id, images in sorted(characters.items()):
        char_dir = output_path / char_id
        char_dir.mkdir(exist_ok=True)

        name = char_id.replace("_", " ").title()

        description = ""
        aliases = []
        tags = []

        if interactive:
            print(f"\n--- {char_id} ---")
            name_input = input(f"  Name [{name}]: ").strip()
            if name_input:
                name = name_input

            desc_input = input(f"  Description (visual traits): ").strip()
            if desc_input:
                description = desc_input

            alias_input = input(f"  Aliases (comma-separated): ").strip()
            if alias_input:
                aliases = [a.strip() for a in alias_input.split(",")]

            tag_input = input(f"  Tags (comma-separated): ").strip()
            if tag_input:
                tags = [t.strip() for t in tag_input.split(",")]

        import shutil
        ref_images = []
        for num, img_name in images:
            src = input_path / img_name
            dst = char_dir / img_name
            shutil.copy2(str(src), str(dst))
            ref_images.append(img_name)

        metadata = {
            "id": char_id,
            "name": name,
            "aliases": aliases,
            "description": description,
            "reference_images": ref_images,
            "tags": tags,
        }

        meta_path = char_dir / "metadata.json"
        with open(meta_path, "w") as f:
            json.dump(metadata, f, indent=2)

        print(f"  Created: {char_id}/ ({len(images)} image(s))")
        imported_count += 1

    return imported_count


def main():
    args = parse_arguments()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Error: Input folder '{args.input}' not found.")
        sys.exit(1)

    output_path = Path(args.output)
    output_path.mkdir(parents=True, exist_ok=True)

    print("=" * 50)
    print("Character Image Importer")
    print("=" * 50)
    print(f"Input:  {input_path}")
    print(f"Output: {output_path}")

    imported = import_characters(input_path, output_path, interactive=args.interactive)

    print(f"\n{'=' * 50}")
    print(f"Imported {imported} characters")
    print(f"Output: {output_path}")
    print(f"{'=' * 50}")


if __name__ == "__main__":
    main()
