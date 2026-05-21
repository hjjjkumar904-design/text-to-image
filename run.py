#!/usr/bin/env python3
"""Story-to-Image Pipeline - Single command entry point.

Usage:
    python run.py --story data/stories/my_story.txt [--output output/] [--config config/config.yaml]
    python run.py --build-workflow          # Generate default ComfyUI workflow JSON
    python run.py --list-characters         # List all loaded characters
"""

import argparse
import json
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(
        description="Automated Story-to-Image Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--story", "-s", type=str,
                        help="Path to story text file")
    parser.add_argument("--output", "-o", type=str, default=None,
                        help="Output directory for generated images")
    parser.add_argument("--config", "-c", type=str,
                        default="config/config.yaml",
                        help="Path to configuration YAML file")
    parser.add_argument("--build-workflow", action="store_true",
                        help="Build default ComfyUI workflow JSON and exit")
    parser.add_argument("--list-characters", action="store_true",
                        help="List all characters in the database and exit")
    parser.add_argument("--import-characters", type=str, default=None,
                        metavar="FOLDER",
                        help="Bulk import character images from folder and exit")

    args = parser.parse_args()

    if args.build_workflow:
        _build_workflow(args.config)
        return

    if args.list_characters:
        _list_characters(args.config)
        return

    if args.import_characters:
        _import_characters(args.import_characters, args.config)
        return

    if not args.story:
        parser.print_help()
        print("\nError: --story is required unless using --build-workflow, --list-characters, or --import-characters")
        sys.exit(1)

    _run_pipeline(args.story, args.output, args.config)


def _run_pipeline(story_path: str, output_dir: str, config_path: str):
    sys.path.insert(0, str(Path(__file__).parent))

    from src.pipeline import StoryPipeline

    pipeline = StoryPipeline(config_path)
    generated = pipeline.run(story_path, output_dir)

    if generated:
        print(f"\nGenerated {len(generated)} images successfully.")
    else:
        print("\nNo images were generated. Check the error messages above.")
        print("If ComfyUI is not running, start it:")
        print("  cd ComfyUI && python main.py --listen --port 8188 --normalvram")


def _build_workflow(config_path: str):
    sys.path.insert(0, str(Path(__file__).parent))

    import yaml
    with open(config_path) as f:
        config = yaml.safe_load(f)

    from src.comfyui_workflow_builder import ComfyUIWorkflowBuilder

    builder = ComfyUIWorkflowBuilder()
    workflow = builder.build_single_character_workflow()
    builder.save_workflow(workflow, config["comfyui"]["workflow"])

    multi_wf = builder.build_multi_character_workflow(num_characters=3)
    multi_path = config["comfyui"]["workflow"].replace(".json", "_multi.json")
    builder.save_workflow(multi_wf, multi_path)


def _list_characters(config_path: str):
    sys.path.insert(0, str(Path(__file__).parent))

    import yaml
    with open(config_path) as f:
        config = yaml.safe_load(f)

    from src.character_db import CharacterDatabase
    db = CharacterDatabase(config["data"]["characters_dir"])
    count = db.load_all()
    print(f"\nCharacter Database: {count} characters loaded\n")
    for cid, char in db.get_all_characters().items():
        print(f"  [{cid}] {char.get('name', cid)}")
        if char.get("aliases"):
            print(f"         Aliases: {', '.join(char['aliases'])}")
        if char.get("description"):
            print(f"         Desc: {char['description'][:80]}...")
        if char.get("tags"):
            print(f"         Tags: {', '.join(char['tags'])}")
        print()


def _import_characters(input_folder: str, config_path: str):
    sys.path.insert(0, str(Path(__file__).parent))

    import yaml
    with open(config_path) as f:
        config = yaml.safe_load(f)

    from src.character_db import CharacterDatabase
    db = CharacterDatabase(config["data"]["characters_dir"])
    count = db.load_all()
    print(f"Existing characters: {count}")
    imported = db.bulk_import(input_folder)
    print(f"Imported: {imported}")
    total = db.load_all()
    print(f"Total characters now: {total}")


if __name__ == "__main__":
    main()
