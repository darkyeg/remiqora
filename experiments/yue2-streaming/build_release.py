"""Build the adopted Windows engine from clean pinned source, with only KV scratch release."""
from pathlib import Path
import difflib
import shutil
import subprocess

from build import LAB, SOURCE, msvc_environment, run
from workspace_patch import patch

ROOT = Path(__file__).resolve().parents[2]
PIN = "f2b4937306daa25f5c78520f3c626ed31495a37a"
AR = "src/models/yue2/ar_runtime.cpp"
RELEASE_SOURCE = LAB / "release-source"
RELEASE_BUILD = LAB / "release-build"
PATCH = ROOT / "external/patches/yue-workspace-release.patch"
PROGRESS_PATCH = ROOT / "external/patches/yue-progress.patch"
DEST = ROOT / "desktop/native/win32-x64/remiqora_yue2_server.exe"


def main():
    active = subprocess.check_output(["tasklist", "/fo", "csv", "/nh"], text=True, errors="replace").lower()
    if any(name in active for name in ("audiocpp_cli.exe", "audiocpp_server.exe", "ninja.exe", "cl.exe", "nvcc.exe", "cmake.exe")):
        raise RuntimeError("Another native engine or build is active")
    head = subprocess.check_output(["git", "-C", str(SOURCE), "rev-parse", "HEAD"], text=True).strip()
    if head != PIN:
        raise RuntimeError(f"Source is not pinned to {PIN}: {head}")
    if not RELEASE_SOURCE.exists():
        shutil.copytree(SOURCE, RELEASE_SOURCE, ignore=shutil.ignore_patterns(".git", "__pycache__"))
    # The experiment checkout has optional audio hooks. Restore only the four
    # touched files from the pinned commit; leave all submodule content local.
    for relative in (AR, "src/models/yue2/nar_runtime.cpp", "src/models/yue2/pipeline.cpp",
                     "src/models/yue2/session.cpp", "include/engine/models/yue2/nar_runtime.h"):
        original = subprocess.check_output(["git", "-C", str(SOURCE), "show", f"HEAD:{relative}"])
        (RELEASE_SOURCE / relative).write_bytes(original)
    (RELEASE_SOURCE / "src/models/yue2/remiqora_lab.h").unlink(missing_ok=True)
    (RELEASE_SOURCE / "include/engine/models/yue2/remiqora_progress.h").unlink(missing_ok=True)
    before = (RELEASE_SOURCE / AR).read_text(encoding="utf-8")
    after = patch(before, always=True)
    (RELEASE_SOURCE / AR).write_text(after, encoding="utf-8", newline="\n")
    diff = "".join(difflib.unified_diff(before.splitlines(keepends=True), after.splitlines(keepends=True),
                                        fromfile=f"a/{AR}", tofile=f"b/{AR}"))
    PATCH.write_text(diff, encoding="utf-8", newline="\n")
    subprocess.run(["git", "apply", str(PROGRESS_PATCH)], cwd=RELEASE_SOURCE, check=True)

    env = msvc_environment()
    cmake = LAB / "tooling/cmake/data/bin/cmake.exe"
    ninja = LAB / "tooling/bin/ninja.exe"
    imported = LAB / "ggml-import"
    if not (imported / "CMakeLists.txt").is_file():
        raise RuntimeError("Run build.py first to create the installed ggml import libraries")
    run([cmake, "-S", RELEASE_SOURCE, "-B", RELEASE_BUILD, "-G", "Ninja",
         f"-DCMAKE_MAKE_PROGRAM={ninja}", "-DCMAKE_BUILD_TYPE=Release",
         "-DCMAKE_POLICY_VERSION_MINIMUM=3.5", "-DAUDIOCPP_MODEL_SET=custom",
         "-DAUDIOCPP_MODELS=yue2,sheetsage2,muscriptor", "-DENGINE_ENABLE_CUDA=OFF",
         "-DAUDIOCPP_BUILD_NATIVE_MODEL_MANAGER=ON",
         "-DENGINE_ENABLE_OPENMP=ON", "-DAUDIOCPP_DEPLOYMENT_BUILD=ON",
         f"-DAUDIOCPP_GGML_SOURCE_DIR={imported}"], env)
    run([cmake, "--build", RELEASE_BUILD, "--target", "audiocpp_cli", "audiocpp_server", "--parallel", "2"], env)
    DEST.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(RELEASE_BUILD / "bin/audiocpp_server.exe", DEST)
    print(f"Adopted native engine: {DEST}")


if __name__ == "__main__":
    main()
