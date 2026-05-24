from typing import List, Optional

from src.character_db import CharacterDatabase


class PromptEngineer:
    def __init__(self, config: Optional[dict] = None):
        self.config = config or {}

        self.base_quality = self.config.get("base_quality",
            "masterpiece, best quality, highly detailed background, "
            "cinematic lighting, 8k, depth of field")

        self.negative_prompt = self.config.get("negative_prompt",
            "blurry, low quality, bad anatomy, distorted face, "
            "extra limbs, watermark, text, signature, deformed, "
            "ugly, poorly drawn, out of frame")

        self.style = self.config.get("style", "digital painting, fantasy art")

    def build_prompt(self, scene: dict, characters: List[dict]) -> str:
        parts = []

        parts.append(self.base_quality)

        if scene.get("setting"):
            parts.append(scene["setting"])

        if scene.get("mood") and scene["mood"] != "neutral":
            mood_to_keywords = {
                "tense": "tense atmosphere, dramatic shadows",
                "joyful": "warm, cheerful atmosphere, golden light",
                "sad": "melancholic atmosphere, muted colors, soft shadows",
                "mysterious": "mysterious atmosphere, fog, dramatic lighting",
                "action-packed": "dynamic scene, action pose, motion blur, sparks",
                "romantic": "warm golden hour light, soft focus, intimate",
                "peaceful": "peaceful, serene, soft light, calm",
                "epic": "epic scale, majestic, dramatic sky, grand vista",
                "sinister": "dark, ominous, shadowy, menacing atmosphere",
                "hopeful": "bright, hopeful, warm light, sunrise tones",
            }
            keywords = mood_to_keywords.get(scene["mood"])
            if keywords:
                parts.append(keywords)

        for char in characters:
            if char and char.get("description"):
                parts.append(char["description"])

        if scene.get("action"):
            action_map = {
                "walking": "walking",
                "running": "running, motion",
                "fighting": "fighting, dynamic action pose",
                "talking": "speaking, gesturing",
                "sitting": "sitting, resting",
                "riding": "riding a horse",
                "eating": "eating, dining",
                "hiding": "hiding, crouching",
                "climbing": "climbing",
                "searching": "searching, looking around",
                "sleeping": "sleeping, resting",
                "celebrating": "celebrating, cheering",
                "fleeing": "fleeing, running away",
                "observing": "observing, watching intently",
                "standing": "standing",
            }
            action_desc = action_map.get(scene["action"])
            if action_desc:
                parts.append(action_desc)

        parts.append(self.style)

        return ", ".join(parts)

    def build_negative_prompt(self) -> str:
        return self.negative_prompt

    def build_prompts_for_scenes(self, scenes: List[dict], db: CharacterDatabase) -> List[dict]:
        for scene in scenes:
            chars = []
            for cid in scene.get("characters_present", []):
                char = db.get_character(cid)
                if char:
                    chars.append(char)

            scene["sdxl_prompt"] = self.build_prompt(scene, chars)
            scene["negative_prompt"] = self.build_negative_prompt()
            scene["character_images"] = []
            for char in chars:
                if char.get("reference_images"):
                    scene["character_images"].append(char["reference_images"][0])

        return scenes
