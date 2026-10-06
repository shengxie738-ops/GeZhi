"""Read-only, explicit operator acceptance for the original official course pack.

No Settings/app startup, credentials, network, file writes or default data path.
Provenance is declared by the operator; hashes do not prove rights or pedagogy.
"""
import argparse
from hashlib import sha256
import json
from pathlib import Path, PurePosixPath
import re
import sys

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
from app.services.teacher_lesson_prep.courseware_catalog import (
    CoursewareCatalog, DEFAULT_COURSE_DIRECTORIES, COURSE_DISPLAY_NAMES, SUPPORTED_EXTENSIONS,
)

EXPECTED = dict(total=97, pdf=58, slides=39, ppt=38, pptx=1)


def verify_pack(frontend_root: Path, manifest_path: Path) -> dict:
    result = dict(ok=False, official_content_verified=False, external_provider_verified=False)
    root = Path(frontend_root).resolve()
    if not root.is_dir():
        return {**result, "error": "COURSEWARE_PACK_REQUIRED"}
    path = Path(manifest_path)
    if not path.is_file() or path.is_symlink() or path.resolve().name.startswith(".env"):
        return {**result, "error": "SOURCE_MANIFEST_REQUIRED"}
    try:
        raw = path.read_bytes()
        manifest = json.loads(raw)
        source = manifest.get("source")
        if (manifest.get("schema") != "gezhi-courseware-source/v1" or manifest.get("synthetic") is not False
                or type(source) is not dict or any(type(source.get(k)) is not str or not source[k].strip()
                    for k in ("description", "origin", "acquired_at", "authorized_by"))):
            return {**result, "error": "OFFICIAL_SOURCE_DECLARATION_REQUIRED"}
        declared = manifest.get("files")
        if type(declared) is not list or not declared:
            raise ValueError("nonempty exact file inventory required")
        observed, normalized = {}, set()
        for item in declared:
            name = item["path"]
            parsed = PurePosixPath(name)
            if (type(name) is not str or "\\" in name or parsed.is_absolute() or ".." in parsed.parts
                    or parsed.as_posix() != name or len(parsed.parts) < 2
                    or parsed.parts[0] not in DEFAULT_COURSE_DIRECTORIES
                    or parsed.name.startswith(".env")
                    or parsed.suffix.casefold() not in SUPPORTED_EXTENSIONS
                    or name.casefold() in normalized):
                raise ValueError("unique canonical allowed path required")
            candidate = root / name
            if any((root.joinpath(*parsed.parts[:i])).is_symlink() for i in range(1, len(parsed.parts) + 1)):
                raise ValueError("symlinks are not operator inventory files")
            if not candidate.resolve().is_relative_to(root / parsed.parts[0]) or not candidate.is_file():
                raise ValueError("owned course path required")
            data = candidate.read_bytes()
            digest = sha256(data).hexdigest()
            if (type(item.get("byte_size")) is not int or item["byte_size"] != len(data)
                    or type(item.get("sha256")) is not str or not re.fullmatch(r"[0-9a-f]{64}", item["sha256"])
                    or item["sha256"] != digest):
                raise ValueError("exact file size and SHA256 required")
            normalized.add(name.casefold())
            observed[name] = dict(byte_size=len(data), sha256=digest)
        inventory = set()
        for course in DEFAULT_COURSE_DIRECTORIES:
            folder = root / course
            if not folder.is_dir() or folder.is_symlink():
                raise ValueError("all five ordinary course directories required")
            for item in folder.rglob("*"):
                if item.is_symlink():
                    raise ValueError("symlink in course inventory")
                if item.is_file() and item.suffix.casefold() in SUPPORTED_EXTENSIONS:
                    inventory.add(item.relative_to(root).as_posix())
        if inventory != set(observed):
            raise ValueError("manifest must exactly cover the course inventory")
    except (ValueError, TypeError, KeyError, OSError, AttributeError):
        return {**result, "error": "COURSEWARE_INTEGRITY_FAILED"}
    catalog = CoursewareCatalog(frontend_root=root)
    resources = catalog.scan()
    summary = catalog.summarize(resources).model_dump()
    legacy = [r for r in resources if r.extension == ".ppt"]
    valid = (all(summary[k] == v for k, v in EXPECTED.items())
             and {r.course for r in resources} == set(COURSE_DISPLAY_NAMES.values())
             and len({r.id for r in resources}) == len(resources)
             and legacy and all(r.index_status == "UNSUPPORTED_LEGACY_PPT" and not r.searchable for r in legacy))
    return {**result, "ok": bool(valid), "error": None if valid else "OFFICIAL_COURSEWARE_CONTRACT_FAILED",
            "expected": EXPECTED, "summary": summary, "source": source,
            "source_status": "operator-declared; not independently authenticated",
            "manifest_sha256": sha256(raw).hexdigest(), "files": observed,
            "scope": "inventory, file hashes and original catalog contract; no content/provider acceptance"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--courseware-root", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    args = parser.parse_args()
    result = verify_pack(args.courseware_root, args.manifest)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
