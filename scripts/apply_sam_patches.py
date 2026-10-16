"""Idempotently apply reviewed patch files to the pinned SAM submodule only."""

from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
SAM = ROOT / "vendor/sam3"
PIN = "7f473cfd983d5eb43040ff608f66bff0d7bdcb53"


def main():
    revision = (
        subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=SAM, text=True
        ).strip()
        if (SAM / ".git").exists()
        else (SAM / ".source-revision").read_text().strip()
    )
    if revision != PIN:
        raise SystemExit(f"SAM 소스 버전을 확인하세요: {revision}; 필요 버전: {PIN}")
    for patch in sorted((ROOT / "patches/sam3").glob("*.patch")):
        args = ["git", "apply", "--check", str(patch)]
        if subprocess.run(args, cwd=SAM, capture_output=True).returncode == 0:
            subprocess.run(["git", "apply", str(patch)], cwd=SAM, check=True)
            print("적용:", patch.name)
        elif (
            subprocess.run(
                ["git", "apply", "--reverse", "--check", str(patch)],
                cwd=SAM,
                capture_output=True,
            ).returncode
            == 0
        ):
            print("이미 적용됨:", patch.name)
        else:
            raise SystemExit(f"패치 충돌: {patch}; 로컬 수정을 보존했습니다.")


if __name__ == "__main__":
    main()
