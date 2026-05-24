import json
import re
from pathlib import Path
from typing import Dict, List, Optional

from src.character_db import CharacterDatabase


class StoryParser:
    def __init__(self, character_db: CharacterDatabase, use_ollama: bool = False, ollama_config: Optional[dict] = None):
        self.db = character_db
        self.use_ollama = use_ollama
        self.ollama_config = ollama_config or {}

    def parse_file(self, filepath: str) -> List[dict]:
        file_path = Path(filepath)
        if not file_path.exists():
            raise FileNotFoundError(f"Story file not found: {filepath}")

        with open(file_path, "r", encoding="utf-8") as f:
            text = f.read()

        scenes = self._split_scenes(text)
        parsed_scenes = []

        for i, scene_text in enumerate(scenes):
            scene_text = scene_text.strip()
            if not scene_text:
                continue

            title = self._extract_title(scene_text)
            body = self._extract_body(scene_text)

            characters = self.db.detect_characters(body)

            setting = self._infer_setting(title, body)
            mood = self._infer_mood(body)
            action = self._infer_action(body)

            if self.use_ollama:
                enriched = self._enrich_with_ollama(body, characters)
                setting = enriched.get("setting", setting)
                mood = enriched.get("mood", mood)
                action = enriched.get("action", action)

            parsed_scenes.append({
                "scene_id": i + 1,
                "title": title,
                "text_excerpt": body[:500],
                "setting": setting,
                "mood": mood,
                "action": action,
                "characters_present": characters,
            })

        return parsed_scenes

    def _split_scenes(self, text: str) -> List[str]:
        scene_header = re.compile(
            r"^(?:Scene|Chapter)\s+\d+[\s:]*(.*?)$",
            re.IGNORECASE | re.MULTILINE,
        )

        matches = list(scene_header.finditer(text))
        if len(matches) >= 2:
            scenes = []
            for i, match in enumerate(matches):
                start = match.end()
                end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
                scene_text = text[match.start():end].strip()
                scenes.append(scene_text)
            return scenes

        sep_patterns = [
            r"(?:^|\n)\s*---+\s*(?:\n|$)",
            r"(?:^|\n)\s*\*+\s*(?:\n|$)",
            r"(?:^|\n)\s*={3,}\s*(?:\n|$)",
        ]
        combined = "|".join(f"(?:{p})" for p in sep_patterns)
        parts = re.split(combined, text, flags=re.MULTILINE)
        parts = [p.strip() for p in parts if p.strip()]
        if len(parts) > 1:
            return parts

        paragraphs = re.split(r"\n\s*\n", text)
        parts = [p.strip() for p in paragraphs if p.strip()]
        return parts if parts else [text.strip()]

    def _extract_title(self, scene_text: str) -> str:
        lines = scene_text.strip().split("\n")
        first_line = lines[0].strip()
        scene_match = re.match(
            r"(?:Scene|Chapter)\s+\d+[\s:]*(.*)", first_line, re.IGNORECASE
        )
        if scene_match:
            title = scene_match.group(1).strip().rstrip(".:")
            if title:
                return title
        return first_line[:60] if first_line else "Untitled Scene"

    def _extract_body(self, scene_text: str) -> str:
        lines = scene_text.strip().split("\n")
        if re.match(
            r"(?:Scene|Chapter)\s+\d+", lines[0].strip(), re.IGNORECASE
        ):
            body = "\n".join(lines[1:]).strip()
            return body if body else scene_text
        return scene_text

    def _infer_setting(self, title: str, body: str) -> str:
        combined = f"{title} {body}".lower()

        settings = {
            "tavern": "medieval tavern interior",
            "castle": "medieval castle",
            "forest": "dense forest",
            "dungeon": "dark dungeon",
            "cave": "rocky cave interior",
            "mountain": "mountain landscape",
            "village": "medieval village",
            "city": "medieval city streets",
            "battlefield": "war-torn battlefield",
            "road": "dusty road",
            "river": "riverside",
            "bridge": "stone bridge",
            "tower": "stone tower",
            "temple": "ancient temple",
            "ruins": "ancient ruins",
            "desert": "desert landscape",
            "sea": "open sea",
            "ship": "wooden ship",
            "market": "busy marketplace",
            "library": "ancient library",
            "throne": "throne room",
            "garden": "royal garden",
            "camp": "military camp",
            "inn": "cozy inn",
        }

        for keyword, description in settings.items():
            if keyword in combined:
                return description

        return "detailed environment"

    def _infer_mood(self, body: str) -> str:
        text_lower = body.lower()

        mood_keywords = {
            "tense": ["tense", "nervous", "anxious", "suspense", "dread", "ominous", "foreboding", "sinister", "dark", "shadow", "pursu", "chaos", "shatter", "erupt"],
            "joyful": ["joy", "happy", "celebrate", "laughter", "cheerful", "merry", "delight", "peaceful", "calm", "warm"],
            "sad": ["sad", "gloomy", "melancholy", "mourn", "tear", "cry", "sorrow", "grief", "despair", "faint"],
            "mysterious": ["mysterious", "strange", "odd", "peculiar", "eerie", "unnerving", "uncanny", "enigmatic", "ancient", "symbol", "glow", "hidden", "secret"],
            "action-packed": ["battle", "fight", "attack", "charge", "clash", "explosion", "rage", "fury", "combat", "struggle", "burst", "sword", "drew his", "drew her"],
            "romantic": ["romantic", "love", "kiss", "embrace", "tender", "passionate", "intimate"],
            "peaceful": ["peaceful", "serene", "quiet", "tranquil", "gentle", "soft", "warm", "cozy", "calm"],
            "epic": ["epic", "grand", "majestic", "glorious", "monumental", "vast", "sweeping", "surge", "determination"],
            "sinister": ["sinister", "menacing", "threatening", "malevolent", "evil", "corrupt", "wicked", "cruel"],
            "hopeful": ["hope", "hopeful", "promising", "bright", "optimistic", "uplifting", "dawn", "light"],
        }

        scores = {}
        for mood, keywords in mood_keywords.items():
            score = sum(1 for kw in keywords if kw in text_lower)
            if score > 0:
                scores[mood] = score

        if scores:
            primary_mood = max(scores, key=scores.get)
            return primary_mood

        return "neutral"

    def _infer_action(self, body: str) -> str:
        text_lower = body.lower()

        action_keywords = {
            "walking": ["walk", "walked", "walking", "step", "stepped", "stride", "strode", "pace", "paced", "stroll", "strolled", "march", "marched", "enter", "entered", "approach", "approached"],
            "running": ["run", "ran", "running", "sprint", "sprinted", "dash", "dashed", "flee", "fled", "fleeing", "chase", "chased", "chasing", "rush", "rushed"],
            "fighting": ["fight", "fought", "fighting", "battle", "attacked", "attack", "strike", "struck", "swing", "swung", "parry", "parried", "block", "blocked", "slash", "slashed", "punch", "punched", "drew his", "drew her", "drew my"],
            "talking": ["say", "said", "says", "speak", "spoke", "speaking", "tell", "told", "talk", "talked", "talking", "converse", "conversed", "whisper", "whispered", "shout", "shouted", "exclaim", "exclaimed", "call", "called"],
            "sitting": ["sit", "sat", "sitting", "seat", "seated", "rest", "rested", "wait", "waited", "waiting"],
            "riding": ["ride", "rode", "riding", "horse", "mount", "mounted"],
            "eating": ["eat", "ate", "eating", "drink", "drank", "drinking", "feast", "feasted", "dine", "dined", "meal"],
            "hiding": ["hide", "hid", "hiding", "duck", "ducked", "ducking", "conceal", "concealed", "sneak", "sneaked", "crouch", "crouched", "lurk", "lurked"],
            "climbing": ["climb", "climbed", "climbing", "scale", "scaled", "ascend", "ascended"],
            "searching": ["search", "searched", "searching", "look", "looked", "looking", "seek", "sought", "explore", "explored", "examine", "examined", "inspect", "inspected", "discover", "discovered", "find", "found"],
            "sleeping": ["sleep", "slept", "sleeping", "rest", "rested", "lie", "lay", "lain", "bed"],
            "celebrating": ["celebrate", "celebrated", "cheer", "cheered", "rejoice", "rejoiced", "feast", "feasted", "toast", "toasted"],
            "fleeing": ["flee", "fled", "fleeing", "escape", "escaped", "escaping", "retreat", "retreated", "retreating", "run away", "ran away"],
            "observing": ["watch", "watched", "watching", "observe", "observed", "gaze", "gazed", "stare", "stared", "peer", "peered", "glance", "glanced", "saw", "see"],
            "emerging": ["emerge", "emerged", "emerging", "exit", "exited", "exit", "came out", "come out", "step out", "stepped out"],
            "standing": ["stand", "stood", "standing", "wait", "waited"],
        }

        scores = {}
        for action, keywords in action_keywords.items():
            score = sum(1 for kw in keywords if kw in text_lower)
            if score > 0:
                scores[action] = score

        if scores:
            primary_action = max(scores, key=scores.get)
            return primary_action

        return "standing"

    def _enrich_with_ollama(self, text: str, characters: List[str]) -> dict:
        import requests

        char_descriptions = []
        for cid in characters:
            char = self.db.get_character(cid)
            if char:
                char_descriptions.append(f"{char['name']}: {char['description']}")

        char_list_str = "\n".join(char_descriptions) if char_descriptions else "None"

        prompt = f"""Analyze this story scene and extract: setting, mood, action, characters.

Scene text:
{text[:1000]}

Known characters:
{char_list_str}

Respond ONLY in JSON format:
{{"setting": "...", "mood": "...", "action": "..."}}"""

        try:
            response = requests.post(
                f"{self.ollama_config.get('url', 'http://127.0.0.1:11434')}/api/generate",
                json={
                    "model": self.ollama_config.get("model", "qwen2.5:14b"),
                    "prompt": prompt,
                    "stream": False,
                },
                timeout=30,
            )
            if response.status_code == 200:
                result = response.json().get("response", "")
                json_match = re.search(r"\{.*\}", result, re.DOTALL)
                if json_match:
                    return json.loads(json_match.group())
        except Exception as e:
            print(f"Ollama enrichment failed: {e}")

        return {}

    def save_scenes(self, scenes: List[dict], output_path: str):
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        with open(output_file, "w") as f:
            json.dump(scenes, f, indent=2)
        print(f"Saved {len(scenes)} scenes to {output_path}")
