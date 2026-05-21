import json
import os
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

import yaml

from src.character_db import CharacterDatabase
from src.story_parser import StoryParser
from src.prompt_engineer import PromptEngineer
from src.comfyui_client import ComfyUIClient


class StoryPipeline:
    def __init__(self, config_path: str = "config/config.yaml"):
        self.config = self._load_config(config_path)
        self.project_root = Path(self.config.get("project_root", "."))

        self.db = CharacterDatabase(
            str(self.project_root / self.config["data"]["characters_dir"])
        )
        self.parser = StoryParser(
            self.db,
            use_ollama=self.config.get("ollama", {}).get("enabled", False),
            ollama_config=self.config.get("ollama", {}),
        )
        self.prompt_engineer = PromptEngineer(self.config.get("prompts", {}))
        self.comfy = ComfyUIClient(
            url=self.config["comfyui"]["url"],
            workflow_path=str(self.project_root / self.config["comfyui"]["workflow"]),
        )

        self.output_base = self.project_root / self.config["data"]["output_dir"]

    def _load_config(self, config_path: str) -> dict:
        with open(config_path, "r") as f:
            return yaml.safe_load(f)

    def run(self, story_path: str, output_dir: Optional[str] = None) -> List[str]:
        print("=" * 60)
        print("STORY-TO-IMAGE PIPELINE")
        print("=" * 60)

        story_name = Path(story_path).stem
        if output_dir:
            scene_output_dir = Path(output_dir)
        else:
            scene_output_dir = self.output_base / story_name
        scene_output_dir.mkdir(parents=True, exist_ok=True)

        print(f"\n[1/5] Loading character database...")
        char_count = self.db.load_all()
        print(f"  Loaded {char_count} characters")

        print(f"\n[2/5] Parsing story: {story_path}")
        scenes = self.parser.parse_file(story_path)
        print(f"  Detected {len(scenes)} scenes")

        print(f"\n[3/5] Generating prompts...")
        scenes = self.prompt_engineer.build_prompts_for_scenes(scenes, self.db)
        print(f"  Generated {len(scenes)} prompts")

        scenes_json_path = scene_output_dir / "scenes.json"
        self.parser.save_scenes(scenes, str(scenes_json_path))

        print(f"\n[4/5] Connecting to ComfyUI...")
        if not self.comfy.connect():
            print("  WARNING: Could not connect to ComfyUI at",
                  self.config["comfyui"]["url"])
            print("  Start ComfyUI with: python ComfyUI/main.py --listen --port 8188 --normalvram")
            print("  Saving prompts only (no generation).")
            self._save_text_output(scenes, scene_output_dir)
            return []

        print(f"  Connected to ComfyUI")

        print(f"\n[5/5] Generating images...")

        workflow = None
        try:
            workflow = self.comfy.load_workflow()
        except (FileNotFoundError, ValueError) as e:
            print(f"  Error loading workflow: {e}")
            print("  Saving prompts only.")
            self._save_text_output(scenes, scene_output_dir)
            return []

        generated_files = []
        for i, scene in enumerate(scenes):
            scene_num = i + 1
            output_name = f"scene_{scene_num:03d}.png"

            print(f"\n  Scene {scene_num}/{len(scenes)}: {scene.get('title', '')}")
            print(f"    Characters: {', '.join(scene.get('characters_present', []))}")
            print(f"    Setting: {scene.get('setting', '')[:60]}")

            result = self.comfy.generate(
                prompt_text=scene.get("sdxl_prompt", ""),
                negative_prompt=scene.get("negative_prompt", ""),
                character_refs=scene.get("character_images", []),
                output_name=output_name,
                workflow=workflow,
            )

            if result:
                generated_files.append(str(scene_output_dir / result))
                scene_meta = scene.copy()
                scene_meta["output_image"] = result
                meta_path = scene_output_dir / f"scene_{scene_num:03d}.json"
                with open(meta_path, "w") as f:
                    json.dump(scene_meta, f, indent=2)

        print(f"\n{'=' * 60}")
        print(f"Pipeline complete!")
        print(f"  Story: {story_path}")
        print(f"  Scenes: {len(scenes)}")
        print(f"  Generated: {len(generated_files)}/{len(scenes)} images")
        print(f"  Output: {scene_output_dir}")
        print(f"{'=' * 60}")

        return generated_files

    def _save_text_output(self, scenes: List[dict], output_dir: Path):
        text_path = output_dir / "prompts.txt"
        with open(text_path, "w") as f:
            for scene in scenes:
                f.write(f"Scene {scene['scene_id']}: {scene.get('title', '')}\n")
                f.write(f"  Characters: {', '.join(scene.get('characters_present', []))}\n")
                f.write(f"  Setting: {scene.get('setting', '')}\n")
                f.write(f"  Mood: {scene.get('mood', '')}\n")
                f.write(f"  Action: {scene.get('action', '')}\n")
                f.write(f"  Prompt: {scene.get('sdxl_prompt', '')}\n")
                f.write(f"  Negative: {scene.get('negative_prompt', '')}\n")
                f.write(f"  Ref Images: {scene.get('character_images', [])}\n")
                f.write("\n" + "-" * 60 + "\n\n")
        print(f"  Saved prompts to {text_path}")
