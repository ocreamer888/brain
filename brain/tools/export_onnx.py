#!/usr/bin/env python3
"""
Export all-mpnet-base-v2 to ONNX format for the Rust brain embedder.

Requires:
    pip install optimum[exporters] sentence-transformers

Output:
    brain/rust/models/all-mpnet-base-v2-onnx/
        model.onnx
        tokenizer.json
        tokenizer_config.json
        special_tokens_map.json
        vocab.txt

Usage:
    python3 brain/tools/export_onnx.py
"""
import sys
from pathlib import Path

OUTPUT_DIR = Path(__file__).parent.parent / "rust" / "models" / "all-mpnet-base-v2-onnx"
MODEL_ID = "sentence-transformers/all-mpnet-base-v2"

def main():
    try:
        from optimum.exporters.onnx import main_export
    except ImportError:
        print("Error: optimum not installed.")
        print("Run: pip install 'optimum[exporters]'")
        sys.exit(1)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Exporting {MODEL_ID} → {OUTPUT_DIR}")

    main_export(
        model_name_or_path=MODEL_ID,
        output=OUTPUT_DIR,
        task="feature-extraction",
    )

    print(f"\nExport complete: {OUTPUT_DIR}")
    print("Files:")
    for f in sorted(OUTPUT_DIR.iterdir()):
        size_kb = f.stat().st_size // 1024
        print(f"  {f.name:40s} {size_kb:>8} KB")

if __name__ == "__main__":
    main()
