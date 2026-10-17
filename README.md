# M4ML Studio

M4ML Studio는 여러 장의 사진으로 객체의 3D 모델을 만드는 Ubuntu 데스크톱 프로그램입니다. 사진 정리부터 객체 선택, 3D 재구성, 결과 확인과 내보내기까지 하나의 작업 공간에서 진행합니다. 모든 처리는 내 컴퓨터의 NVIDIA GPU에서 이루어집니다.

## 주요 기능

- 사진 폴더를 선택하면 기존 작업 결과를 자동으로 분석해 이어서 작업
- GPU 카메라 정합 (COLMAP)
- 클릭으로 객체 선택, 모든 사진으로 마스크 전파 및 수정 (SAM 3.1)
- 3D 재구성 학습, 일시정지 후 이어서 학습
- 학습 결과 실시간 렌더와 색상 3D 메시 보기
- PLY / GLB 내보내기

## 시스템 요구사항

- Ubuntu 24.04 (x86_64), X11 데스크톱
- NVIDIA GPU와 CUDA 12를 지원하는 드라이버 (RTX 4080 16 GB, 드라이버 580에서 검증)
- 인터넷 연결 (최초 설치 시 실행 환경 다운로드)
- SAM 3.1 모델 파일 `sam3.1_multiplex.pt` — 포함되어 있지 않습니다. [공식 저장소](https://github.com/facebookresearch/sam3)의 이용 조건에 따라 직접 받으세요.

## 설치 및 실행

1. 필요한 시스템 패키지와 [Miniforge](https://github.com/conda-forge/miniforge)를 설치합니다.

   ```bash
   sudo apt install python3 git curl ca-certificates build-essential gcc-11 g++-11 bzip2 libgl1 libegl1 libglib2.0-0 libxcb-cursor0 libxkbcommon-x11-0 libxcb-icccm4 libxcb-keysyms1 libxcb-shape0 libxcb-xinerama0 libxcb-render-util0 libnss3 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 libxtst6 libxi6 libasound2t64 libxkbfile1
   ```

2. [Releases](https://github.com/WooSungHyun03/M4ML-Studio/releases)에서 `M4ML-Studio-1.0.0-linux-x86_64.tar.gz`와 `.sha256` 파일을 받아 설치합니다.

   ```bash
   sha256sum -c M4ML-Studio-1.0.0-linux-x86_64.tar.gz.sha256
   tar -xzf M4ML-Studio-1.0.0-linux-x86_64.tar.gz
   cd M4ML-Studio-1.0.0
   ./scripts/install.sh
   ```

3. 앱 메뉴에서 **M4ML Studio**를 실행합니다. 처음 실행하면 **설정 → 모델 파일**에서 SAM 3.1 모델 파일 경로를 지정합니다.

제거는 `./scripts/install.sh --uninstall`입니다. 프로젝트와 설정은 지워지지 않습니다. 사용법은 앱의 **도움말** 메뉴에 있습니다.

## 라이선스

비상업적 연구·평가 목적으로만 사용할 수 있습니다. [LICENSE.md](LICENSE.md), [NOTICE](NOTICE), [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)를 확인하세요.
