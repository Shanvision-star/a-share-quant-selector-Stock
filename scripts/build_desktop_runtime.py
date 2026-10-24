"""构建独立 Windows 运行包：固定解释器、已验证依赖、白名单源码与无凭证默认配置。"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata as metadata
import json
from pathlib import Path
import shutil
import sys
import sysconfig
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "desktop" / "build"
PYTHON_VERSION = "3.14.9"
PYTHON_URL = f"https://www.python.org/ftp/python/{PYTHON_VERSION}/python-{PYTHON_VERSION}-embed-amd64.zip"
PYTHON_SHA256 = "3c01d7cfc666f746a6f064f60fb2156ab0ec464d3d738ab796371a46a9bb24a2"
CERTIFI_URL = "https://files.pythonhosted.org/packages/c4/51/29046e48f693c54e5b7412216d447a1d8362c9653148d98c02cdf65fa733/certifi-2026.10.19-py3-none-any.whl"
CERTIFI_SHA256 = "42d35340cc5b9ba78e818ddbff0c5b1c2b779de448a340fd1b989f5fa8670e1b"
LOCK = ROOT / "desktop" / "requirements-runtime.lock"
DEV_PACKAGES = {"pip", "pytest", "iniconfig", "pluggy", "pygments"}
SOURCE_DIRS = ("web/backend", "utils", "strategy", "backtest_lab")
SOURCE_SCRIPTS = ("run_desktop_backend.py", "desktop_process_guard.py", "run_web_backend.py", "quant_mcp.py", "quant_tools.py",
                  "run_zettaranc_backtest.py", "extend_history_baostock.py", "backfill_history.py")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def reset_build_dir(path: Path):
    """只清理本脚本拥有的 build 子目录，禁止计算路径越界。"""
    resolved = path.resolve()
    if not resolved.is_relative_to(BUILD.resolve()) or resolved == BUILD.resolve() or path.is_symlink():
        raise ValueError(f"拒绝清理非构建目录：{path}")
    if resolved.exists():
        shutil.rmtree(resolved)
    resolved.mkdir(parents=True)


def write_lock():
    packages = sorted((dist.metadata["Name"], dist.version) for dist in metadata.distributions()
                      if dist.metadata["Name"].lower() not in DEV_PACKAGES)
    LOCK.write_text("# Windows CPython 3.14 x64；来自已通过项目测试的构建环境\n" +
                    "\n".join(f"{name}=={version}" for name, version in packages) + "\n", encoding="utf-8")


def copy_dependencies(destination: Path) -> list[dict]:
    site = Path(sysconfig.get_paths()["purelib"]).resolve()
    packages = []
    for line in LOCK.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        name, version = line.split("==")
        if name.lower() == "certifi":
            continue
        dist = metadata.distribution(name)
        if dist.version != version:
            raise RuntimeError(f"构建环境版本不符：{name} 需要 {version}，当前 {dist.version}")
        for entry in dist.files or []:
            source = Path(dist.locate_file(entry)).resolve()
            if not source.is_file() or not source.is_relative_to(site) or source.suffix == ".pyc":
                continue
            relative = source.relative_to(site)
            # 分发依赖自带的测试数据不参与应用运行；许可证和 dist-info 必须保留。
            if "__pycache__" in relative.parts or "tests" in relative.parts:
                continue
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        packages.append({"name": name, "version": version})
    return packages


def build_python():
    if sys.version_info[:2] != (3, 14) or sys.maxsize <= 2**32:
        raise RuntimeError("请用 Windows CPython 3.14 x64 构建，以匹配已编译依赖")
    cache = BUILD / "downloads"
    cache.mkdir(parents=True, exist_ok=True)
    archive = cache / f"python-{PYTHON_VERSION}-embed-amd64.zip"
    if not archive.exists():
        urllib.request.urlretrieve(PYTHON_URL, archive)
    if digest(archive) != PYTHON_SHA256:
        raise RuntimeError("Python 官方下载 SHA256 不符，停止打包")
    target = BUILD / "python"
    reset_build_dir(target)
    with zipfile.ZipFile(archive) as zipped:
        zipped.extractall(target)
    (target / "python314._pth").write_text("python314.zip\n.\nLib/site-packages\nimport site\n", encoding="utf-8")
    packages = copy_dependencies(target / "Lib" / "site-packages")
    certificates = cache / "certifi-2026.10.19-py3-none-any.whl"
    if not certificates.exists():
        urllib.request.urlretrieve(CERTIFI_URL, certificates)
    if digest(certificates) != CERTIFI_SHA256:
        raise RuntimeError("certifi 官方 wheel SHA256 不符，停止打包")
    with zipfile.ZipFile(certificates) as zipped:
        zipped.extractall(target / "Lib" / "site-packages")
    packages.append({"name": "certifi", "version": "2026.10.19", "sha256": CERTIFI_SHA256})
    (target / "runtime-manifest.json").write_text(json.dumps({"python": PYTHON_VERSION, "python_url": PYTHON_URL,
        "python_sha256": PYTHON_SHA256, "packages": packages}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"python": PYTHON_VERSION, "packages": len(packages), "directory": str(target)}))


def source_files(root: Path):
    for folder in SOURCE_DIRS:
        yield from (root / folder).rglob("*.py")
    for name in ("main.py", "quant_system.py", "web_server.py"):
        yield root / name
    for name in SOURCE_SCRIPTS:
        yield root / "scripts" / name
    for file in (root / "docs").rglob("*"):
        if file.suffix.lower() in {".md", ".png", ".jpg", ".svg"}:
            yield file
    for file in (root / "third_party" / "zettaranc").rglob("*"):
        relative = file.relative_to(root / "third_party" / "zettaranc")
        if any(part.startswith(".") or part in {"data", "tests", "__pycache__"} for part in relative.parts):
            continue
        if file.suffix in {".py", ".md"} or file.name in {"LICENSE", "LICENSE.md"}:
            yield file
    for file in (root / "web" / "frontend" / "dist").rglob("*"):
        if file.is_file() and file.suffix != ".map":
            yield file
    for name in ("LICENSE", "LICENSE.md"):
        if (root / name).exists():
            yield root / name


def build_app():
    if not (ROOT / "web/frontend/dist/index.html").exists():
        raise RuntimeError("先运行前端 build")
    target = BUILD / "app"
    reset_build_dir(target)
    manifest = {}
    for source in source_files(ROOT):
        if not source.is_file() or "__pycache__" in source.parts:
            continue
        relative = source.relative_to(ROOT)
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        manifest[relative.as_posix()] = digest(destination)
    # 首次启动种子与受管理代码分开；升级不覆盖任何现有用户配置。
    defaults = BUILD / "defaults"
    reset_build_dir(defaults)
    (defaults / "config").mkdir()
    import yaml
    config = yaml.safe_load((ROOT / "config/config.yaml.template").read_text(encoding="utf-8"))
    config["dingtalk"] = {"webhook_url": "", "secret": ""}
    (defaults / "config/config.yaml").write_text(yaml.safe_dump(config, allow_unicode=True), encoding="utf-8")
    shutil.copy2(ROOT / "config/strategy_params.yaml", defaults / "config/strategy_params.yaml")
    shutil.copy2(ROOT / "config/llm.yaml.template", defaults / "config/llm.yaml")
    (target / "app-manifest.json").write_text(json.dumps({"files": manifest}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"app_files": len(manifest), "directory": str(target)}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock", action="store_true")
    parser.add_argument("--app-only", action="store_true")
    parser.add_argument("--python-only", action="store_true")
    args = parser.parse_args()
    if args.lock:
        write_lock()
    if not args.app_only:
        build_python()
    if not args.python_only:
        build_app()


if __name__ == "__main__":
    main()
