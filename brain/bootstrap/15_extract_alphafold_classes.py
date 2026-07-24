#!/usr/bin/env python3
"""
EXTRACT AND DOCUMENT ALL 117 ALPHAFOLD CLASSES
Create detailed markdown documentation for each class with real code
"""

import os
import re
from pathlib import Path
from typing import Dict, List, Tuple
from datetime import datetime

AF_REPO = "/tmp/alphafold/alphafold"
ALGORITHMS_DIR = "/Users/macm1air/Documents/AI/ALGORITHMS"

class ClassExtractor:
    def __init__(self):
        self.af_path = Path(AF_REPO)
        self.algo_path = Path(ALGORITHMS_DIR)
        self.extraction_log = []

    def extract_class_code(self, filepath: Path, class_name: str) -> Tuple[str, str]:
        """Extract class definition and key methods from file."""
        try:
            with open(filepath, 'r') as f:
                lines = f.readlines()
        except:
            return "", ""

        content = ''.join(lines)
        class_pattern = rf'class\s+{class_name}\s*(\([^)]*\))?:'

        match = re.search(class_pattern, content)
        if not match:
            return "", ""

        # Find class start
        class_start = match.start()
        class_start_line = content[:class_start].count('\n')

        # Find docstring
        docstring = ""
        start_pos = match.end()
        if content[start_pos:start_pos+3] in ['"""', "'''"]:
            quote = content[start_pos:start_pos+3]
            doc_start = start_pos + 3
            doc_end = content.find(quote, doc_start)
            if doc_end != -1:
                docstring = content[doc_start:doc_end].strip()

        # Get next 30 lines of class definition
        class_lines = lines[class_start_line:min(class_start_line+30, len(lines))]
        class_def = ''.join(class_lines)

        # Find __init__ method
        init_pattern = r'def\s+__init__\s*\([^)]*\):[^:]*?(?=\n\s{0,4}def|\nclass|\Z)'
        init_match = re.search(init_pattern, class_def, re.DOTALL)
        init_code = init_match.group(0) if init_match else ""

        # Find __call__ or forward method
        call_pattern = r'def\s+(__call__|forward)\s*\([^)]*\):[^:]*?(?=\n\s{0,4}def|\nclass|\Z)'
        call_match = re.search(call_pattern, class_def, re.DOTALL)
        call_code = call_match.group(0) if call_match else ""

        return docstring, init_code + "\n" + call_code

    def categorize_class(self, filename: str, class_name: str) -> str:
        """Determine which subdirectory class belongs to."""
        core_files = ["modules.py", "folding.py", "folding_multimer.py", "modules_multimer.py"]
        geom_files = ["quat_affine.py", "rotation_matrix.py", "rigid_matrix_vector.py", "vector.py"]
        data_files = ["mmcif_parsing.py", "templates.py", "msa_identifiers.py", "msa_pairing.py"]
        relax_files = ["relax.py"]

        if filename in core_files:
            return "core_algorithms"
        elif filename in geom_files:
            return "geometry"
        elif filename in data_files:
            return "data_processing"
        elif filename in relax_files:
            return "refinement"
        else:
            return "core_algorithms"  # Default

    def create_class_doc(self, filepath: Path, class_name: str, docstring: str, code: str) -> str:
        """Create markdown documentation for a single class."""

        doc = f"""# {class_name}

**File**: {filepath.name}
**Module**: {filepath.parent.name}
**Date**: {datetime.now().strftime('%Y-%m-%d')}

---

## Summary

{docstring if docstring else f"Class {class_name} from AlphaFold"}

---

## Class Definition

```python
{code[:500]}...
```

---

## Integration

This class is part of AlphaFold's {filepath.parent.name} module.

---

**Status**: ✅ Extracted from AlphaFold codebase
"""
        return doc

    def extract_all(self):
        """Extract all 117 classes and create documentation."""
        print("\n" + "="*70)
        print(" "*15 + "EXTRACTING ALL 117 ALPHAFOLD CLASSES")
        print("="*70 + "\n")

        categories = {
            "model": Path(AF_REPO) / "model",
            "data": Path(AF_REPO) / "data",
            "common": Path(AF_REPO) / "common",
            "relax": Path(AF_REPO) / "relax",
        }

        total_extracted = 0
        doc_count = 0

        for cat_name, cat_path in categories.items():
            if not cat_path.exists():
                continue

            print(f"Processing {cat_name}...")
            py_files = [f for f in cat_path.glob("*.py") if not f.name.endswith("_test.py") and f.name != "__init__.py"]

            for py_file in py_files:
                with open(py_file, 'r') as f:
                    content = f.read()

                # Find all classes
                class_matches = re.finditer(r'class\s+(\w+)\s*(\([^)]*\))?:', content)

                for match in class_matches:
                    class_name = match.group(1)
                    total_extracted += 1

                    # Extract class code
                    docstring, code = self.extract_class_code(py_file, class_name)

                    # Categorize
                    subdir = self.categorize_class(py_file.name, class_name)

                    # Create documentation
                    doc_content = self.create_class_doc(py_file, class_name, docstring, code)

                    # Save to appropriate directory
                    doc_path = (self.algo_path / "domains/biomolecular" / subdir)
                    doc_path.mkdir(parents=True, exist_ok=True)

                    output_file = doc_path / f"{class_name}.md"
                    with open(output_file, 'w') as f:
                        f.write(doc_content)

                    doc_count += 1
                    print(f"  ✓ {class_name} → {subdir}/")

        print(f"\n" + "="*70)
        print(f"✅ EXTRACTION COMPLETE")
        print(f"   Classes found: {total_extracted}")
        print(f"   Docs created: {doc_count}")
        print("="*70 + "\n")

        return total_extracted, doc_count

    def create_category_index(self):
        """Create index for each category."""
        print("Creating category indexes...")

        categories = {
            "core_algorithms": "Core Algorithm Classes (37)",
            "geometry": "Geometric Operations (5)",
            "data_processing": "Data Processing (33)",
            "refinement": "Refinement Pipeline (1)",
        }

        for cat_dir, cat_title in categories.items():
            cat_path = self.algo_path / "domains/biomolecular" / cat_dir
            if not cat_path.exists():
                continue

            md_files = list(cat_path.glob("*.md"))

            index = f"""# {cat_title}

**Date**: {datetime.now().strftime('%Y-%m-%d')}
**Classes**: {len(md_files)}

---

## Class List

"""
            for md_file in sorted(md_files):
                class_name = md_file.stem
                index += f"- [{class_name}]({md_file.name})\n"

            index_file = cat_path / "_INDEX.md"
            with open(index_file, 'w') as f:
                f.write(index)

            print(f"  ✓ {cat_dir} index created")

if __name__ == "__main__":
    extractor = ClassExtractor()
    total, docs = extractor.extract_all()
    extractor.create_category_index()

    print(f"\n✅ Full extraction complete: {docs} documentation files created")
