import argparse
import json
import shutil
import subprocess
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TARGET_DIR = PROJECT_ROOT / "data" / "converted" / "docx"
DEFAULT_WORK_DIR = PROJECT_ROOT / "data" / "converted" / "libreoffice_tmp"


def find_soffice(explicit_path: str | None = None) -> Path | None:
    if explicit_path:
        path = Path(explicit_path)
        return path if path.exists() else None

    found = shutil.which("soffice") or shutil.which("libreoffice")
    if found:
        return Path(found)

    candidates = [
        Path(r"C:\Program Files\LibreOffice\program\soffice.exe"),
        Path(r"C:\Program Files (x86)\LibreOffice\program\soffice.exe"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def doc_items(manifest_path: Path) -> list[dict]:
    items = json.loads(manifest_path.read_text(encoding="utf-8"))
    return [item for item in items if Path(item["local_path"]).suffix.lower() == ".doc"]


def target_path_for_doc(item: dict, target_dir: Path) -> Path:
    source = Path(item["local_path"])
    return target_dir / f"{item['doc_id']}_{source.stem}.docx"


def should_skip_existing(target: Path, force: bool) -> bool:
    return target.exists() and target.stat().st_size > 0 and not force


def convert_one(
    item: dict,
    soffice: Path,
    work_dir: Path,
    target_dir: Path,
    timeout_seconds: int,
    force: bool = False,
) -> tuple[bool, str]:
    source = Path(item["local_path"])
    target = target_path_for_doc(item, target_dir)
    if should_skip_existing(target, force):
        return True, f"SKIP exists {target.name}"

    work_dir.mkdir(parents=True, exist_ok=True)
    target_dir.mkdir(parents=True, exist_ok=True)

    command = [
        str(soffice),
        "--headless",
        "--convert-to",
        "docx",
        "--outdir",
        str(work_dir),
        str(source),
    ]
    try:
        completed = subprocess.run(
            command,
            check=True,
            timeout=timeout_seconds,
            capture_output=True,
            text=True,
        )
    except subprocess.TimeoutExpired:
        return False, f"TIMEOUT after {timeout_seconds}s: {source.name}"
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        return False, f"FAILED {source.name}: {detail}"

    produced = work_dir / f"{source.stem}.docx"
    if not produced.exists():
        detail = (completed.stderr or completed.stdout or "").strip()
        return False, f"FAILED {source.name}: LibreOffice produced no docx. {detail}"

    shutil.copy2(produced, target)
    return True, f"OK {source.name} -> {target.name}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert legacy .doc files with LibreOffice headless.")
    parser.add_argument("--manifest", default=str(PROJECT_ROOT / "data" / "manifest.json"))
    parser.add_argument("--target-dir", default=str(DEFAULT_TARGET_DIR))
    parser.add_argument("--work-dir", default=str(DEFAULT_WORK_DIR))
    parser.add_argument("--soffice", default=None, help="Explicit path to soffice.exe")
    parser.add_argument("--limit", type=int, default=0, help="0 means all .doc files")
    parser.add_argument("--timeout-seconds", type=int, default=60)
    parser.add_argument("--force", action="store_true", help="Overwrite existing converted cache files.")
    args = parser.parse_args()

    soffice = find_soffice(args.soffice)
    if soffice is None:
        raise SystemExit(
            "LibreOffice not found. Install LibreOffice or pass --soffice "
            r'"C:\Program Files\LibreOffice\program\soffice.exe".'
        )

    items = doc_items(Path(args.manifest))
    if args.limit:
        items = items[:args.limit]
    if not items:
        print("No .doc files found.")
        return

    ok_count = 0
    failures = []
    for item in items:
        ok, message = convert_one(
            item=item,
            soffice=soffice,
            work_dir=Path(args.work_dir),
            target_dir=Path(args.target_dir),
            timeout_seconds=args.timeout_seconds,
            force=args.force,
        )
        print(message, flush=True)
        if ok:
            ok_count += 1
        else:
            failures.append(message)

    print(f"Summary: {ok_count}/{len(items)} converted or cached.")
    if failures:
        print("Failures:")
        for failure in failures:
            print(f"- {failure}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
