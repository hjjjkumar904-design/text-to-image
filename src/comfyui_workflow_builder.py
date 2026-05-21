import json
import uuid
from typing import Dict, List, Optional


class ComfyUIWorkflowBuilder:
    def __init__(self):
        self.nodes = {}
        self._node_counter = 0

    def _new_id(self) -> int:
        self._node_counter += 1
        return self._node_counter

    def _make_node(self, class_type: str, inputs: dict = None,
                   title: str = None) -> int:
        node_id = self._new_id()
        node = {
            "inputs": inputs or {},
            "class_type": class_type,
        }
        if title:
            node["_meta"] = {"title": title}
        self.nodes[str(node_id)] = node
        return node_id

    def add_checkpoint_loader(self, checkpoint_name: str) -> int:
        return self._make_node(
            "CheckpointLoaderSimple",
            {"ckpt_name": checkpoint_name},
            "Load Checkpoint",
        )

    def add_clip_text_encode(self, text: str, position_id: int = None) -> int:
        title = "CLIP Text Encode (Positive)" if position_id != 2 else "CLIP Text Encode (Negative)"
        return self._make_node("CLIPTextEncode", {"text": text}, title)

    def add_load_image(self, image_name: str = "REF_IMAGE_PLACEHOLDER.png") -> int:
        return self._make_node("LoadImage", {"image": image_name}, "Load Reference Image")

    def add_clip_vision_loader(self, clip_name: str = "CLIP-ViT-H-14-laion2B-s32B-b79K.safetensors") -> int:
        return self._make_node("CLIPVisionLoader", {"clip_name": clip_name}, "CLIP Vision Loader")

    def add_insightface_loader(self, provider: str = "CPU", model_name: str = "buffalo_l") -> int:
        return self._make_node("IPAdapterInsightFaceLoader", {"provider": provider, "model_name": model_name}, "InsightFace Loader")

    def add_ipadapter_model_loader(self, model_name: str = "ip-adapter-faceid-plusv2_sdxl.bin") -> int:
        return self._make_node(
            "IPAdapterModelLoader",
            {"ipadapter_file": model_name},
            "IPAdapter Model Loader",
        )

    def add_ipadapter_faceid(self, weight: float = 0.75,
                              weight_faceidv2: float = 0.6,
                              weight_type: str = "linear",
                              start_at: float = 0.0,
                              end_at: float = 1.0) -> int:
        return self._make_node(
            "IPAdapterFaceID",
            {
                "weight": weight,
                "weight_faceidv2": weight_faceidv2,
                "weight_type": weight_type,
                "combine_embeds": "concat",
                "start_at": start_at,
                "end_at": end_at,
                "embeds_scaling": "V only",
            },
            "IPAdapter FaceID",
        )

    def add_empty_latent(self, width: int = 1216, height: int = 832, batch_size: int = 1) -> int:
        return self._make_node(
            "EmptyLatentImage",
            {"width": width, "height": height, "batch_size": batch_size},
            "Empty Latent Image",
        )

    def add_ksampler(self, seed: int = 0, steps: int = 30, cfg: float = 7.5,
                     sampler_name: str = "dpmpp_2m", scheduler: str = "karras",
                     denoise: float = 1.0) -> int:
        return self._make_node(
            "KSampler",
            {
                "seed": seed,
                "steps": steps,
                "cfg": cfg,
                "sampler_name": sampler_name,
                "scheduler": scheduler,
                "denoise": denoise,
            },
            "KSampler",
        )

    def add_vae_decode(self) -> int:
        return self._make_node("VAEDecode", {}, "VAE Decode")

    def add_save_image(self, filename_prefix: str = "scene") -> int:
        return self._make_node(
            "SaveImage",
            {"filename_prefix": filename_prefix},
            "Save Image",
        )

    def add_upscale(self, upscale_model_name: str = None) -> int:
        node_id = self._make_node(
            "UltimateSDUpscale",
            {
                "upscale_model": upscale_model_name or "4x_NMKD-Superscale-SP_178000_G.pth",
                "target_size_type": 2,
                "upscale_factor": 1.5,
            },
            "Ultimate SD Upscale",
        )
        return node_id

    def connect(self, from_id: int, from_output: str,
                to_id: int, to_input: str):
        if str(to_id) not in self.nodes:
            self.nodes[str(to_id)] = {"inputs": {}, "class_type": "unknown"}
        if str(from_id) not in self.nodes:
            self.nodes[str(from_id)] = {"inputs": {}, "class_type": "unknown"}

        output_names = {
            "CheckpointLoaderSimple": {"model": 0, "clip": 1, "vae": 2},
            "CLIPTextEncode": {"CONDITIONING": 0},
            "CLIPVisionLoader": {"CLIP_VISION": 0},
            "LoadImage": {"IMAGE": 0},
            "IPAdapterModelLoader": {"IPADAPTER": 0},
            "IPAdapterFaceID": {"MODEL": 0, "face_image": 1},
            "IPAdapterAdvanced": {"MODEL": 0},
            "IPAdapterInsightFaceLoader": {"INSIGHTFACE": 0},
            "EmptyLatentImage": {"LATENT": 0},
            "KSampler": {"LATENT": 0},
            "VAEDecode": {"IMAGE": 0},
            "SaveImage": {},
            "UltimateSDUpscale": {"IMAGE": 0},
        }
        from_cls = self.nodes.get(str(from_id), {}).get("class_type", "")
        out_idx = output_names.get(from_cls, {}).get(from_output, 0)
        self.nodes[str(to_id)]["inputs"][to_input] = [str(from_id), out_idx]

    def build_single_character_workflow(self,
                                          checkpoint_name: str = "Juggernaut-XL_v9_RunDiffusionPhoto_v2.safetensors",
                                          ipadapter_model: str = "ip-adapter-faceid-plusv2_sdxl.bin",
                                          width: int = 1216, height: int = 832,
                                          steps: int = 30, cfg: float = 7.5) -> dict:
        return self.build_simple_workflow(checkpoint_name=checkpoint_name, width=width, height=height, steps=steps, cfg=cfg)

    def build_simple_workflow(self,
                               checkpoint_name: str = "Juggernaut-XL_v9_RunDiffusionPhoto_v2.safetensors",
                               width: int = 1216, height: int = 832,
                               steps: int = 30, cfg: float = 7.5) -> dict:
        self.nodes = {}
        checkpoint = self.add_checkpoint_loader(checkpoint_name)
        pos_enc = self.add_clip_text_encode("POSITIVE_PLACEHOLDER")
        neg_enc = self.add_clip_text_encode("NEGATIVE_PLACEHOLDER", position_id=2)
        latent = self.add_empty_latent(width, height)
        ksampler = self.add_ksampler(steps=steps, cfg=cfg)
        vae_decode = self.add_vae_decode()
        save_image = self.add_save_image("scene")

        self.connect(checkpoint, "clip", pos_enc, "clip")
        self.connect(checkpoint, "clip", neg_enc, "clip")
        self.connect(checkpoint, "vae", vae_decode, "vae")
        self.connect(checkpoint, "model", ksampler, "model")
        self.connect(pos_enc, "CONDITIONING", ksampler, "positive")
        self.connect(neg_enc, "CONDITIONING", ksampler, "negative")
        self.connect(latent, "LATENT", ksampler, "latent_image")
        self.connect(ksampler, "LATENT", vae_decode, "samples")
        self.connect(vae_decode, "IMAGE", save_image, "images")

        return self.nodes

    def build_multi_character_workflow(self,
                                        checkpoint_name: str = "Juggernaut-XL_v9_RunDiffusionPhoto_v2.safetensors",
                                        ipadapter_model: str = "ip-adapter-faceid-plusv2_sdxl.bin",
                                        num_characters: int = 2,
                                        width: int = 1216, height: int = 832,
                                        steps: int = 30, cfg: float = 7.5) -> dict:
        return self.build_simple_workflow(checkpoint_name=checkpoint_name, width=width, height=height, steps=steps, cfg=cfg)

    def save_workflow(self, workflow: dict, output_path: str):
        with open(output_path, "w") as f:
            json.dump(workflow, f, indent=2)
        print(f"Saved workflow to {output_path}")
