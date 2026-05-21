import json
import os
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple


class CharacterDatabase:
    def __init__(self, characters_dir: str = "data/characters"):
        self.characters_dir = Path(characters_dir)
        self.characters: Dict[str, dict] = {}
        self.aliases: Dict[str, str] = {}

    def load_all(self) -> int:
        self.characters = {}
        self.aliases = {}

        if not self.characters_dir.exists():
            print(f"Warning: Characters directory '{self.characters_dir}' not found.")
            return 0

        for char_dir in self.characters_dir.iterdir():
            if not char_dir.is_dir():
                continue
            metadata_path = char_dir / "metadata.json"
            if not metadata_path.exists():
                continue

            try:
                with open(metadata_path, "r") as f:
                    meta = json.load(f)

                char_id = meta.get("id", char_dir.name)
                ref_images = []
                for img_name in sorted(char_dir.iterdir()):
                    if img_name.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp"):
                        ref_images.append(str(img_name))
                    if meta.get("reference_images"):
                        ref_images = [
                            str(char_dir / r) for r in meta["reference_images"]
                            if (char_dir / r).exists()
                        ]

                if not ref_images:
                    ref_images = [
                        str(img) for img in sorted(char_dir.iterdir())
                        if img.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp")
                    ]

                meta["reference_images"] = ref_images
                meta["_dir"] = str(char_dir)
                self.characters[char_id] = meta

                aliases = [char_id] + meta.get("aliases", [])
                for alias in aliases:
                    self.aliases[alias.lower().strip()] = char_id

            except (json.JSONDecodeError, KeyError) as e:
                print(f"Warning: Could not load {metadata_path}: {e}")

        return len(self.characters)

    def get_character(self, char_id: str) -> Optional[dict]:
        return self.characters.get(char_id)

    def get_all_characters(self) -> Dict[str, dict]:
        return self.characters

    def get_all_character_ids(self) -> List[str]:
        return list(self.characters.keys())

    def detect_characters(self, text: str) -> List[str]:
        found_ids = []
        text_lower = text.lower()

        sorted_aliases = sorted(self.aliases.keys(), key=len, reverse=True)

        temp_text = text_lower
        for alias in sorted_aliases:
            pattern = re.compile(re.escape(alias), re.IGNORECASE)
            if pattern.search(temp_text):
                char_id = self.aliases[alias]
                if char_id not in found_ids:
                    found_ids.append(char_id)
                temp_text = pattern.sub("", temp_text)

        return found_ids

    def add_character(self,
                      char_id: str,
                      name: str,
                      description: str,
                      aliases: Optional[List[str]] = None,
                      tags: Optional[List[str]] = None,
                      reference_images: Optional[List[str]] = None) -> dict:
        char_dir = self.characters_dir / char_id
        char_dir.mkdir(parents=True, exist_ok=True)

        meta = {
            "id": char_id,
            "name": name,
            "aliases": aliases or [],
            "description": description,
            "reference_images": reference_images or [],
            "tags": tags or [],
        }

        meta_path = char_dir / "metadata.json"
        with open(meta_path, "w") as f:
            json.dump(meta, f, indent=2)

        self.characters[char_id] = meta
        self.aliases[char_id.lower()] = char_id
        for alias in meta.get("aliases", []):
            self.aliases[alias.lower().strip()] = char_id

        return meta

    def bulk_import(self, input_folder: str, output_folder: Optional[str] = None) -> int:
        if output_folder:
            self.characters_dir = Path(output_folder)
            self.characters_dir.mkdir(parents=True, exist_ok=True)

        input_path = Path(input_folder)
        if not input_path.exists():
            print(f"Error: Input folder '{input_folder}' not found.")
            return 0

        image_files = sorted([
            f for f in input_path.iterdir()
            if f.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp")
        ])

        imported = 0
        for img_path in image_files:
            stem = img_path.stem
            parts = stem.split("_")
            char_id = parts[0]

            if char_id in self.characters:
                char_dir = Path(self.characters[char_id]["_dir"])
            else:
                char_dir = self.characters_dir / char_id
                char_dir.mkdir(exist_ok=True)

            dest_path = char_dir / img_path.name
            import shutil
            shutil.copy2(str(img_path), str(dest_path))

            if char_id not in self.characters:
                name = char_id.replace("_", " ").title()
                self.add_character(
                    char_id=char_id,
                    name=name,
                    description="",
                    reference_images=[img_path.name],
                )
            else:
                meta = self.characters[char_id]
                if img_path.name not in meta.get("reference_images", []):
                    meta.setdefault("reference_images", []).append(img_path.name)
                    meta_path = Path(meta["_dir"]) / "metadata.json"
                    with open(meta_path, "w") as f:
                        json.dump(meta, f, indent=2)

            imported += 1

        return imported
