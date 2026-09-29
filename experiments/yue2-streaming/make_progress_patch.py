"""Record the optional YuE2 progress hooks as a replayable release patch."""
from pathlib import Path
import difflib
import subprocess
import tempfile

from build import LAB, SOURCE
from workspace_patch import patch as workspace_patch

ROOT = Path(__file__).resolve().parents[2]
RELEASE_SOURCE = LAB / "release-source"
OUT = ROOT / "external/patches/yue-progress.patch"
FILES = (
    "src/models/yue2/ar_runtime.cpp",
    "src/models/yue2/nar_runtime.cpp",
    "src/models/yue2/pipeline.cpp",
    "src/models/yue2/session.cpp",
    "include/engine/models/yue2/remiqora_progress.h",
)


def main():
    changes = []
    for relative in FILES:
        if relative.endswith("remiqora_progress.h"):
            before = ""
            fromfile = "/dev/null"
        else:
            before = subprocess.check_output(
                ["git", "-C", str(SOURCE), "show", f"HEAD:{relative}"],
            ).decode("utf-8")
            if relative == "src/models/yue2/ar_runtime.cpp":
                before = workspace_patch(before, always=True)
            fromfile = f"a/{relative}"
        after = (RELEASE_SOURCE / relative).read_text(encoding="utf-8")
        changes.extend(difflib.unified_diff(
            before.splitlines(keepends=True), after.splitlines(keepends=True),
            fromfile=fromfile, tofile=f"b/{relative}",
        ))
    OUT.write_text("".join(changes), encoding="utf-8", newline="\n")
    with tempfile.TemporaryDirectory(prefix="remiqora-progress-") as temporary:
        staging = Path(temporary)
        for relative in FILES[:-1]:
            original = subprocess.check_output(
                ["git", "-C", str(SOURCE), "show", f"HEAD:{relative}"],
            ).decode("utf-8")
            if relative == "src/models/yue2/ar_runtime.cpp":
                original = workspace_patch(original, always=True)
            target = staging / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(original, encoding="utf-8", newline="\n")
        subprocess.run(["git", "apply", "--check", str(OUT)], cwd=staging, check=True)
        subprocess.run(["git", "apply", str(OUT)], cwd=staging, check=True)
        for relative in FILES:
            if (staging / relative).read_text(encoding="utf-8") != (RELEASE_SOURCE / relative).read_text(encoding="utf-8"):
                raise RuntimeError(f"Progress patch replay differs: {relative}")
    print(OUT)


if __name__ == "__main__":
    main()
