"""CLI: extract files from testing_files/ and print JSON. Run: python run_local_extract.py"""
import json
import sys
from pathlib import Path

from fileExtraction import SUPPORTED_EXTENSIONS
from local_extract import TESTING_FILES_DIR, extract_local_file, list_testing_files

ROOT = Path(__file__).resolve().parent


def resolve_path(name_or_path: str) -> Path:
    candidate = Path(name_or_path)
    if candidate.is_file():
        return candidate.resolve()
    for base in (TESTING_FILES_DIR, ROOT):
        path = (base / candidate).resolve()
        if path.is_file():
            return path
    return candidate.resolve()


def main():
    if len(sys.argv) > 1:
        target = resolve_path(sys.argv[1])
        if not target.is_file():
            print(f"File not found: {sys.argv[1]}\nLooked in: {TESTING_FILES_DIR}")
            sys.exit(1)
        files = [target]
    else:
        files = list_testing_files()
        if not files:
            print(f"No files in {TESTING_FILES_DIR}\nSupported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}")
            sys.exit(1)

    failed = 0
    for path in files:
        result = extract_local_file(path)
        print(f"\n=== {path.name} ===")
        print(json.dumps(result, indent=2, ensure_ascii=False))
        if not result.get("success"):
            failed += 1
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
