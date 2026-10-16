"""Check Qt's Linux platform dependencies without starting a GUI or importing CUDA."""
import importlib.util
from pathlib import Path
import subprocess


def desktop_dependencies():
    spec = importlib.util.find_spec("PySide6")
    if not spec or not spec.submodule_search_locations:
        return {"exit_code": 1, "output": "데스크톱 구성요소가 없습니다. ./scripts/setup.sh를 다시 실행하세요."}
    root = Path(next(iter(spec.submodule_search_locations)))
    libraries = [root / "Qt/plugins/platforms/libqxcb.so", root / "Qt/lib/libQt6WebEngineCore.so.6"]
    missing = set()
    try:
        for library in libraries:
            result = subprocess.run(["ldd", str(library)], capture_output=True, text=True, timeout=10)
            missing.update(line.split()[0] for line in result.stdout.splitlines() if "not found" in line)
            if result.returncode:
                missing.add(library.name)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"exit_code": 1, "output": f"데스크톱 시스템 라이브러리를 검사하지 못했습니다: {exc}"}
    if missing:
        detail = ", ".join(sorted(missing))
        return {"exit_code": 1, "missing": sorted(missing),
                "output": f"데스크톱 실행에 필요한 Ubuntu 시스템 라이브러리가 없습니다: {detail}. README의 시스템 준비 항목을 확인하세요. libxcb-cursor.so.0은 libxcb-cursor0, libsmime3.so는 libnss3 패키지로 설치할 수 있습니다. 런타임과 프로젝트는 보존했습니다."}
    return {"exit_code": 0, "missing": [], "output": "Qt X11 시스템 라이브러리 확인"}


if __name__ == "__main__":
    result = desktop_dependencies()
    print(result["output"])
    raise SystemExit(result["exit_code"])
