"""배포판 빌드 스크립트

실행할 때마다 app.py의 VERSION 마지막 자리를 1 올린 뒤
PyInstaller로 빌드하고, ffmpeg.exe와 배포 안내를 넣어 zip으로 압축한다.

    python build.py              # 패치 버전 올리고 빌드 (1.0.1 → 1.0.2)
    python build.py --no-bump    # 현재 버전 그대로 다시 빌드
"""
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
APP = ROOT / "app.py"
DIST = ROOT / "dist" / "pro"
PACKAGE = DIST / "ShortMaker"
ZIP = ROOT / "dist" / "ShortMakerPro-Windows.zip"
PATTERN = re.compile(r'^VERSION = "(\d+)\.(\d+)\.(\d+)"$', re.M)


def read_version():
    match = PATTERN.search(APP.read_text(encoding="utf-8"))
    if not match:
        raise SystemExit("app.py에서 VERSION을 찾지 못했습니다.")
    return tuple(int(part) for part in match.groups())


def bump_version():
    # 패치 자리만 올리고 app.py에 다시 쓴다
    major, minor, patch = read_version()
    version = f"{major}.{minor}.{patch + 1}"
    text = APP.read_text(encoding="utf-8")
    APP.write_text(PATTERN.sub(f'VERSION = "{version}"', text, count=1), encoding="utf-8", newline="")
    return version


def main():
    if not (ROOT / "ffmpeg.exe").is_file():
        raise SystemExit("ffmpeg.exe가 없습니다. README의 안내대로 app.py 옆에 두세요.")
    version = ".".join(map(str, read_version())) if "--no-bump" in sys.argv else bump_version()
    print(f"버전 {version} 빌드 시작")
    subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--distpath", str(DIST), str(ROOT / "ShortMaker.spec")], cwd=ROOT, check=True)
    for name in ("ffmpeg.exe", "배포_안내.txt"):
        shutil.copy2(ROOT / name, PACKAGE / name)
    ZIP.unlink(missing_ok=True)
    shutil.make_archive(str(ZIP.with_suffix("")), "zip", DIST, "ShortMaker")
    print(f"완료: v{version} → {ZIP}")


if __name__ == "__main__":
    main()
