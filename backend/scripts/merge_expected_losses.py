"""Takes another platform's PDF claims into the expected-loss manifests (tracker TEST-021A).
The PDF export takes its fonts from the machine, so each platform records its own PDF claims
(app/fidelity/loss_manifest.py). CI records Linux's in every run -- the "expected-loss-linux"
artifact, the manifests as `python -m scripts.export_expected_losses` wrote them there.
Downloaded and unpacked, this takes only that platform's PDF claims from them, nothing else:

    python -m scripts.merge_expected_losses DOWNLOADED_DIR [--platform linux]

Then commit the manifests: from then on CI compares PDF losses too.
"""

import argparse
import json
from pathlib import Path

from scripts.export_expected_losses import FOLDERS

SUFFIX = ".expected-loss.json"


def merge(downloaded: Path, platform: str, folders: tuple[Path, ...] = FOLDERS) -> list[str]:
    """Each manifest here with `platform`'s PDF claims from the one of the same name under
    `downloaded` (at any depth). The names of the manifests changed."""
    found = {path.name: path for path in downloaded.rglob(f"*{SUFFIX}")}
    changed: list[str] = []
    for folder in folders:
        for path in sorted(folder.glob(f"*{SUFFIX}")):
            other = found.get(path.name)
            if other is None:
                continue
            claims = json.loads(other.read_text(encoding="utf-8")).get("pdf", {}).get(platform)
            if claims is None:
                continue
            manifest = json.loads(path.read_text(encoding="utf-8"))
            if manifest.get("pdf", {}).get(platform) == claims:
                continue
            manifest.setdefault("pdf", {})[platform] = claims
            path.write_text(json.dumps(manifest, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
            changed.append(path.name)
    return changed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("downloaded", type=Path)
    parser.add_argument("--platform", default="linux")
    args = parser.parse_args()
    changed = merge(args.downloaded, args.platform)
    for name in changed:
        print(f"merged {args.platform} PDF claims into {name}")
    print(f"{len(changed)} manifest(s) changed")


if __name__ == "__main__":
    main()
