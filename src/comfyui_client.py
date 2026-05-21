import json
import os
import time
import uuid
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests
from tqdm import tqdm


class ComfyUIClient:
    def __init__(self, url: str = "http://127.0.0.1:8188", workflow_path: str = None):
        self.url = url.rstrip("/")
        self.workflow_path = workflow_path
        self.client_id = str(uuid.uuid4())[:8]

    def connect(self) -> bool:
        try:
            response = requests.get(f"{self.url}/system_stats", timeout=5)
            return response.status_code == 200
        except requests.RequestException:
            return False

    def queue_prompt(self, workflow: dict) -> Optional[str]:
        payload = {
            "prompt": workflow,
            "client_id": self.client_id,
        }
        try:
            response = requests.post(
                f"{self.url}/prompt",
                json=payload,
                timeout=30,
            )
            if response.status_code == 200:
                return response.json().get("prompt_id")
            else:
                print(f"Error queueing prompt: {response.status_code} {response.text}")
                return None
        except requests.RequestException as e:
            print(f"Connection error: {e}")
            return None

    def get_history(self, prompt_id: str) -> Optional[dict]:
        try:
            response = requests.get(
                f"{self.url}/history/{prompt_id}",
                timeout=10,
            )
            if response.status_code == 200:
                return response.json().get(prompt_id)
            return None
        except requests.RequestException:
            return None

    def wait_for_completion(self, prompt_id: str, timeout: int = 300) -> bool:
        start = time.time()
        with tqdm(total=100, desc="Generating", bar_format="{desc}: {percentage:3.0f}%|{bar}|") as pbar:
            while time.time() - start < timeout:
                history = self.get_history(prompt_id)
                if history:
                    status = history.get("status", {})
                    if status.get("completed") is True:
                        pbar.n = 100
                        pbar.refresh()
                        return True
                    if status.get("error"):
                        print(f"Generation error: {status['error']}")
                        return False
                    progress = status.get("progress", 0)
                    pbar.n = int(progress * 100)
                    pbar.refresh()
                time.sleep(1)
        print(f"Timeout after {timeout}s waiting for prompt {prompt_id}")
        return False

    def get_image(self, filename: str, output_dir: str = "output") -> Optional[bytes]:
        image_path = Path(output_dir) / filename
        if image_path.exists():
            with open(image_path, "rb") as f:
                return f.read()

        try:
            response = requests.get(
                f"{self.url}/view",
                params={"filename": filename},
                timeout=30,
            )
            if response.status_code == 200:
                image_path.parent.mkdir(parents=True, exist_ok=True)
                with open(image_path, "wb") as f:
                    f.write(response.content)
                return response.content
        except requests.RequestException:
            pass

        return None

    def load_workflow(self, workflow_path: str = None) -> dict:
        path = workflow_path or self.workflow_path
        if not path:
            raise ValueError("No workflow path specified")

        with open(path, "r") as f:
            workflow = json.load(f)

        return workflow

    def inject_prompt(self, workflow: dict, prompt_text: str, negative_prompt: str,
                      character_images: Optional[List[str]] = None,
                      output_filename: str = "output.png") -> dict:
        workflow_copy = json.loads(json.dumps(workflow))

        for node_id, node in workflow_copy.items():
            if not isinstance(node, dict):
                continue

            class_type = node.get("class_type", "")

            if class_type == "CLIPTextEncode" and node.get("_meta", {}).get("title", "") == "":
                inputs = node.get("inputs", {})
                if "text" in inputs:
                    text_value = str(inputs.get("text", "")).lower()
                    if "masterpiece" in text_value or "quality" in text_value:
                        inputs["text"] = prompt_text
                    elif "blurry" in text_value or "low quality" in text_value:
                        inputs["text"] = negative_prompt

            if "inputs" in node and "text" in node["inputs"]:
                text_val = str(node["inputs"]["text"])
                if "POSITIVE_PLACEHOLDER" in text_val:
                    node["inputs"]["text"] = prompt_text
                elif "NEGATIVE_PLACEHOLDER" in text_val:
                    node["inputs"]["text"] = negative_prompt

            if class_type == "SaveImage":
                inputs = node.get("inputs", {})
                inputs["filename_prefix"] = output_filename.replace(".png", "")

            if class_type in ("LoadImage", "IPAdapterImage"):
                if character_images and "image" in node.get("inputs", {}):
                    img_val = str(node["inputs"].get("image", ""))
                    if "REF_IMAGE_PLACEHOLDER" in img_val:
                        if character_images:
                            node["inputs"]["image"] = character_images[0]

        return workflow_copy

    def generate(self, prompt_text: str, negative_prompt: str = None,
                 character_refs: Optional[List[str]] = None,
                 output_name: str = "scene_001.png",
                 workflow: dict = None) -> Optional[str]:
        if workflow is None:
            workflow = self.load_workflow()

        if negative_prompt is None:
            negative_prompt = "blurry, low quality, bad anatomy, distorted face, extra limbs, watermark, text, signature"

        workflow = self.inject_prompt(
            workflow, prompt_text, negative_prompt,
            character_images=character_refs,
            output_filename=output_name,
        )

        prompt_id = self.queue_prompt(workflow)
        if not prompt_id:
            print(f"Failed to queue generation for {output_name}")
            return None

        print(f"Queued {output_name} (prompt_id: {prompt_id})")

        if self.wait_for_completion(prompt_id):
            print(f"Completed: {output_name}")
            return output_name
        else:
            print(f"Failed: {output_name}")
            return None
