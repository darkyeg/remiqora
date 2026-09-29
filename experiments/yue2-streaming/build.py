"""Build an isolated YuE2-only host executable against installed ggml DLLs.

No CUDA SDK, model copies, or changes to the installed application are needed.
The source checkout and local CMake/Ninja tools live under external/audio-stream-lab.
"""
from pathlib import Path
import argparse
import os
import re
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[2]
LAB = ROOT / "external/audio-stream-lab"
SOURCE = LAB / "source"


def msvc_environment():
    vswhere = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Microsoft Visual Studio/Installer/vswhere.exe"
    install = subprocess.check_output([
        str(vswhere), "-latest", "-products", "*", "-requires",
        "Microsoft.VisualStudio.Component.VC.Tools.x86.x64", "-property", "installationPath",
    ], text=True).strip()
    if not install:
        raise RuntimeError("MSVC x64 tools are required")
    devcmd = Path(install) / "Common7/Tools/VsDevCmd.bat"
    comspec = os.environ.get("COMSPEC", "cmd.exe")
    bootstrap_env = os.environ.copy()
    bootstrap_env["PATH"] = str(vswhere.parent) + os.pathsep + bootstrap_env["PATH"]
    output = subprocess.check_output(
        f'"{comspec}" /d /s /c "call "{devcmd}" -arch=x64 >nul && set"',
        text=True, errors="replace", env=bootstrap_env)
    env = os.environ.copy()
    for line in output.splitlines():
        key, sep, value = line.partition("=")
        if sep and key:
            env[key] = value
    return env


def run(args, env):
    command = [str(arg) for arg in args]
    command[0] = shutil.which(command[0], path=env["PATH"]) or command[0]
    subprocess.run(command, env=env, check=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine", type=Path, default=Path(os.environ["LOCALAPPDATA"]) / "Remiqora/engines/YuE2")
    parser.add_argument("--configure-only", action="store_true")
    args = parser.parse_args()
    active = subprocess.check_output(["tasklist", "/fo", "csv", "/nh"], text=True, errors="replace").lower()
    if any(name in active for name in ("audiocpp_cli.exe", "audiocpp_server.exe", "ninja.exe", "cl.exe", "nvcc.exe", "cmake.exe")):
        raise RuntimeError("Another engine or build is active; wait before building")
    env = msvc_environment()
    bindir = args.engine.resolve() / "build/windows-cuda-release/bin"
    imported = LAB / "ggml-import"
    imported.mkdir(parents=True, exist_ok=True)
    for name in ("ggml-base", "ggml"):
        dll = bindir / f"{name}.dll"
        exports = subprocess.check_output([shutil.which("dumpbin.exe", path=env["PATH"]), "/exports", str(dll)], env=env, text=True)
        symbols = re.findall(r"^\s+\d+\s+[0-9A-F]+\s+[0-9A-F]+\s+(\S+)", exports, re.MULTILINE)
        if not symbols:
            raise RuntimeError(f"No exports in {dll}")
        definition = imported / f"{name}.def"
        definition.write_text(f"LIBRARY {name}.dll\nEXPORTS\n" + "\n".join(symbols) + "\n")
        run(["lib.exe", "/nologo", "/machine:x64", f"/def:{definition}", f"/out:{imported / (name + '.lib')}"], env)
    includes = (SOURCE / "external/ggml/include").as_posix()
    (imported / "CMakeLists.txt").write_text(f'''cmake_minimum_required(VERSION 3.20)
add_library(ggml-base SHARED IMPORTED GLOBAL)
set_target_properties(ggml-base PROPERTIES
  IMPORTED_IMPLIB "{(imported / 'ggml-base.lib').as_posix()}"
  IMPORTED_LOCATION "{(bindir / 'ggml-base.dll').as_posix()}"
  INTERFACE_INCLUDE_DIRECTORIES "{includes}"
  INTERFACE_COMPILE_DEFINITIONS "GGML_SHARED")
add_library(ggml SHARED IMPORTED GLOBAL)
set_target_properties(ggml PROPERTIES
  IMPORTED_IMPLIB "{(imported / 'ggml.lib').as_posix()}"
  IMPORTED_LOCATION "{(bindir / 'ggml.dll').as_posix()}"
  INTERFACE_INCLUDE_DIRECTORIES "{includes}"
  INTERFACE_COMPILE_DEFINITIONS "GGML_SHARED"
  INTERFACE_LINK_LIBRARIES ggml-base)
''')
    cmake = LAB / "tooling/cmake/data/bin/cmake.exe"
    ninja = LAB / "tooling/bin/ninja.exe"
    run([cmake, "-S", SOURCE, "-B", LAB / "build", "-G", "Ninja",
         f"-DCMAKE_MAKE_PROGRAM={ninja}", "-DCMAKE_BUILD_TYPE=Release",
         "-DCMAKE_POLICY_VERSION_MINIMUM=3.5", "-DAUDIOCPP_MODEL_SET=custom",
         "-DAUDIOCPP_MODELS=yue2", "-DENGINE_ENABLE_CUDA=OFF",
         "-DENGINE_ENABLE_OPENMP=ON", "-DAUDIOCPP_DEPLOYMENT_BUILD=ON",
         f"-DAUDIOCPP_GGML_SOURCE_DIR={imported}"], env)
    if not args.configure_only:
        run([cmake, "--build", LAB / "build", "--target", "audiocpp_cli", "--parallel", "2"], env)


if __name__ == "__main__":
    main()
