# M4ML Studio

여러 사진에서 객체를 클릭해 선택하고, 마스크를 확인한 뒤 GPU 학습으로 **실제 색상을 가진 3D 메시**를 만드는 Ubuntu 로컬 앱입니다. 사진·마스크·모델은 컴퓨터 안에 저장합니다. 로그인이나 클라우드 업로드는 없습니다.

**0.3.0 내부 연구·평가용 빌드입니다.** 기술 검증과 공개 재배포 승인은 별개입니다. SuiteSparse GPL/LGPL 소스 제공·재링크/결합 배포 검토와 원본 비상업 연구 조건 때문에 공개·상업 릴리스는 보류합니다. [배포 판정](docs/M4ML_STUDIO_RELEASE_STATUS.md), [라이선스](docs/M4ML_STUDIO_LICENSES.md), [시험 보고서](docs/TEST_REPORT.md)를 확인하세요. 공개 다운로드 URL은 제공하지 않습니다.

## 지원 환경과 준비

- 실제 검증: **Ubuntu24.04 x86_64, RTX4080 16GB, NVIDIA580.173.02**. 새로운 non-root Ubuntu24.04 컨테이너도 같은 물리 GPU에서 검증했습니다. 다른 GPU/Ubuntu22.04/Wayland 데스크톱 전체는 인증하지 않았습니다. 16GB는 검증 장비 용량이며 최소 VRAM 보장값이 아닙니다.
- 내장 카메라 정합 엔진은 GPU COLMAP4.2.1/CUDA12.6이며 glibc2.39 이상이 필요합니다. 드라이버580에서 실제 동작을 확인했습니다. CUDA12 minor compatibility의525 하한만으로 모든 GPU·PTX 실행을 보장하지 않습니다. 드라이버를 자동 변경하지 않습니다.
- Python3, Git, GCC/G++11, Conda(Miniforge 등), 기본 GL/EGL/GLib/OpenMP 라이브러리를 먼저 준비합니다. 컨테이너의 정확한 준비 패키지/버전과 검증 범위는 [시험 보고서](docs/TEST_REPORT.md)를 보세요. GPU Python 환경은 **Python3.10 / Torch2.5.1+cu118 / NumPy1.24.4** 하나를 유지합니다.
- 최초 환경 설치에는 인터넷과 여유 저장 공간이 필요합니다. 이후 모델과 환경이 준비되면 정적 UI/로컬 계산은 CDN·원격 인증 없이 실행됩니다. 배포본 사용에는 Node가 필요하지 않습니다.

## 설치와 최초 실행

Ubuntu 24.04 X11의 시스템 준비에는 Python3, Git, curl, Miniforge, GCC/G++11과 OpenGL/X11 라이브러리가 필요합니다. Qt 화면에 필요한 `libxcb-cursor0`, `libxkbcommon-x11-0`, `libxcb-icccm4`, `libxcb-keysyms1`, `libxcb-shape0`, `libxcb-xinerama0`, `libxcb-render-util0`, `libegl1`, `libgl1`, `libglib2.0-0`도 준비하세요. 설치 프로그램은 시스템 패키지나 드라이버를 자동으로 변경하지 않습니다. 누락된 라이브러리는 설치·환경 진단에서 안내합니다.

최소 Ubuntu 환경에서는 Qt WebEngine의 `libnss3`, `libxcomposite1`, `libxdamage1`, `libxfixes3`, `libxrandr2`, `libxtst6`, `libxi6`, `libasound2t64`, `libxkbfile1`도 필요합니다. 시스템 관리자가 다음 패키지를 준비한 뒤 사용자 계정에서 설치를 실행할 수 있습니다.

```bash
sudo apt install python3 git curl ca-certificates build-essential gcc-11 g++-11 bzip2 libgl1 libegl1 libglib2.0-0 libxcb-cursor0 libxkbcommon-x11-0 libxcb-icccm4 libxcb-keysyms1 libxcb-shape0 libxcb-xinerama0 libxcb-render-util0 libnss3 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 libxtst6 libxi6 libasound2t64 libxkbfile1
```

내부 검증 압축본과 같은 이름의 SHA256 파일을 받은 폴더에서:

```bash
sha256sum -c M4ML-Studio-0.5.0-linux-x86_64.tar.gz.sha256
tar -xzf M4ML-Studio-0.5.0-linux-x86_64.tar.gz
cd M4ML-Studio-0.5.0
./scripts/install.sh
```

설치 후 Ubuntu 앱 메뉴의 **M4ML Studio** 또는 다음 명령으로 엽니다.

```bash
python3 scripts/launch.py
```

프로그램은 **자체 데스크톱 창**(PySide6 6.8.1 + QtWebEngine)으로 열리며 웹 브라우저를 열지 않습니다. 내부 백엔드는 창이 실행될 때마다 비어 있는 loopback 포트와 새 인증 토큰으로 시작되고, 창을 닫으면 함께 종료됩니다. 창 크기·위치·패널 배치는 다음 실행 때 복원됩니다. 개발용 브라우저 모드는 `python3 scripts/launch.py --browser`(기본 주소 http://127.0.0.1:8765, `STUDIO_PORT`로 변경)입니다. 데스크톱 구성요소나 시스템 라이브러리가 없으면 원인과 설치 안내를 표시하고 종료합니다. 브라우저 모드는 --browser로 직접 선택할 때만 열립니다.

SAM3.1 가중치는 포함하지 않습니다. [공식 모델 안내](https://github.com/facebookresearch/sam3)에서 이용 조건을 확인해 **SAM3.1 multiplex 체크포인트**를 직접 준비하고, 앱 **설정 → 모델 파일**에서 신뢰하는 `.pt` 경로를 저장하세요. 파일 존재 확인 후 최초 추론에서 실제 구조를 검사합니다. 개발 PC의 고정 경로에 의존하지 않습니다.

Conda를 못 찾으면 `STUDIO_CONDA=/실제/conda/경로 ./scripts/install.sh`를 사용합니다. GPU 없는 결과 확인용은 `./scripts/install.sh --viewer-only`입니다. 이 모드는 학습/객체 추론을 다른 모델로 대체하지 않고 차단합니다.

소스 체크아웃은 `./scripts/setup.sh`, `./scripts/start.sh`, `./scripts/doctor.sh`를 사용합니다. UI 재빌드에만 Node22/npm 및 `npm ci --prefix frontend && npm run build --prefix frontend`가 필요합니다.

## 새 프로젝트와 기존 데이터

시작 화면에는 **새 프로젝트**와 **기존 프로젝트 열기** 두 가지만 있습니다.

- **새 프로젝트**: 폴더를 선택하면 사진, COLMAP sparse, 왜곡 보정 사진, 마스크, 학습 결과, 체크포인트, 3D 모델, M4ML 프로젝트 정보를 **읽기 전용으로 자동 분석**하고 추천 시작 단계를 보여 줍니다. 파일이 있다는 것만으로 통과시키지 않습니다. 카메라 결과는 실제로 읽어 사진 이름과 대조하고, 마스크는 이름·크기를 대조하며, 학습 결과는 `cameras.json`의 카메라 중심을 COLMAP 카메라 중심과 비교합니다. **다른 데이터셋에서 나온 결과는 연결하지 않고** 이유를 표시합니다. 원본 폴더는 수정·삭제하지 않고 필요한 파일만 프로젝트로 복사합니다. 경로 직접 지정은 분석 화면의 고급 옵션에 있습니다.
- **기존 프로젝트 열기**: M4ML 프로젝트를 다시 열고 마지막으로 검증된 단계부터 이어갑니다.

화면은 메뉴(파일·편집·보기·작업·창·도움말), 프로젝트 막대, 작업 탭, 프로젝트 탐색기 | 작업 화면 | Inspector, 아래 패널(콘텐츠·작업 관리자·Console·GPU Monitor), 상태 표시줄로 구성됩니다. 자세한 사용법은 [사용 설명서](docs/USER_GUIDE.md), [단축키](docs/SHORTCUTS.md), [오류 해결](docs/TROUBLESHOOTING.md)에 있으며 앱의 **도움말** 메뉴에서도 열 수 있습니다.

객체 안을 클릭하면 포함, **Alt+클릭/오른쪽 클릭**은 제외합니다. 별도 추론 버튼 없이 자동 갱신하며 연속 클릭의 최신 결과만 표시합니다. 첫 클릭은 모델 로딩 시간이 필요하고 이후 모델을 유지합니다. 전파 결과를 확인하거나 유효한 마스크의 남은 검토만 명시적으로 건너뜁니다. 붓 수정은 저장해야 하며 다른 승인 프레임은 보호됩니다.

## 학습·중단·색상 내보내기

마스크 검토 후 **3D 재구성 → 학습 시작**에서 GPU/반복 수를 확인하고 승인합니다. 원본 Object-Aware Loss의 masked L1·polarization·pruning 및2DGS 기하 손실을 사용합니다. 기본30000회를 임의로 줄이지 않습니다. 실제 손실/절대 반복 수/로그를 표시합니다.

**일시정지**는 마지막 저장 지점을 보존하며 입력이 바뀌지 않았으면 그 지점부터 재개합니다. 기본 저장 간격2500회이므로 마지막 저장 후 진행분은 잃을 수 있습니다. 사진·마스크 변경 후에는 이전 체크포인트를 무조건 재사용하지 않습니다.

3D 모델 화면의 **실시간 렌더**는 학습된 Gaussian 자체를 원본 렌더러로 자유 시점에서 실시간 렌더링합니다(색상·불투명도·깊이·법선·객체 점수, 학습 직후 자동 인식). 연구용 외부 뷰어로 2DGS 호환 SIBR remote viewer(`./scripts/build_sibr.sh`)도 같은 렌더러에 연결할 수 있습니다. 자세한 내용은 [Gaussian 뷰어 통합](docs/GAUSSIAN_VIEWER_INTEGRATION.md)을 보세요.

학습 후 실제 TSDF 추출이 자동 실행됩니다. **메시** 뷰포트의 기본 보기는 **색상 메시**(파일의 정점 색상 그대로)이며 정점 색상(조명)·셰이딩·와이어프레임·법선·포인트 클라우드 모드, 앞/뒤/좌/우/위/아래 시점, 원근/직교, 방향 기즈모, 그리드·좌표축, 밝기·조명 방향, 메시 통계, PNG 스크린샷, 다시 불러오기를 지원합니다. **PLY/GLB 내보내기**는 실제 정점 색상을 보존합니다. 색상이 없는 외부 메시에는 색상이 없다고 표시하며 색을 만들어 넣지 않습니다. 가려진/부족한 사진은 부분 표면과 구멍을 만들 수 있고 수밀성을 보장하지 않습니다.

## 저장과 오류 해결

새 사용자의 프로젝트·런타임은 `~/.local/share/m4ml-studio`, 설정은 `~/.config/m4ml-studio`, 실행 로그는 `~/.cache/m4ml-studio`입니다. 기존 Object-Aware 데이터가 있으면 그 위치를 보존합니다. `STUDIO_DATA`, `STUDIO_RUNTIME`, `STUDIO_PORT`로 위치/포트를 지정할 수 있습니다. 변경은 자동 저장되고 붓의 미저장 수정은 따로 표시합니다.

- **GPU/모델 없음**: 설정의 처리 장치·모델 파일, 고급 정보 및 `./scripts/doctor.sh` 결과를 확인하세요. 앱을 열어 결과를 보는 것은 가능합니다.
- **메모리 부족**: 이전 정상 마스크·점·로그가 보존됩니다. 다른 GPU 작업을 정리하거나 고급 설정에서 해상도를 직접 낮춰 재시도하세요.
- **정합 실패**: 매칭/등록 수와 실패 이미지를 확인하고 겹침·흔들림·시점 간격을 개선하세요.
- **마스크 누락/불일치**: 파일별 오류를 수정하거나 카메라만 가져와 마스크를 새로 만드세요. 임의 통과하지 않습니다.
- **중단/재실행**: 프로젝트를 다시 열고 마지막 검증 단계에서 이어갑니다. 부분 출력은 완료로 취급하지 않습니다.
- **제거/업데이트**: 앱 종료 후 `./scripts/install.sh --uninstall`. 실행 메뉴와 앱 설치본만 보관 폴더로 옮기며 프로젝트·런타임은 유지합니다. 다른 버전은 별도 폴더에 설치하고, 같은 버전의 다른 내용은 덮어쓰지 않습니다.

상세한 [사용 설명서](docs/USER_GUIDE.md), [이전 사용자 안내](docs/M4ML_STUDIO_USER_GUIDE.md), [기능 감사](docs/FUNCTIONAL_AUDIT.md), [진행 기록](docs/STATUS.md), [원본 라이선스](LICENSE.md), [NOTICE](NOTICE)를 함께 제공합니다.

아래 원본 연구 README는 기술 출처로 보존합니다.

---

# Object-Aware Loss for Mask-Guided Mesh Reconstruction Based on 2D Gaussian Splatting

Sunghyun Woo, Jeongil Seo, HeeKyung Lee — *Mathematics* (MDPI), 2026

[Paper](https://www.mdpi.com/2227-7390/14/17/3221)

![Overview](assets/pipeline.png)

We add an object-aware loss to 2D Gaussian Splatting for mask-guided, object-level mesh reconstruction: photometric supervision is restricted to the object mask, and a learnable per-Gaussian ObjectMark score is polarized toward the mask and used to prune background Gaussians during training.

## Installation

```bash
git clone --recursive https://github.com/WooSungHyun03/object-aware-loss.git
cd object-aware-loss
conda env create --file environment.yml
conda activate object-aware-2dgs
```

## Dataset

Prepare a COLMAP scene as in [2D Gaussian Splatting](https://github.com/hbb1/2d-gaussian-splatting?tab=readme-ov-file#quick-examples), and additionally provide one binary object mask per view:

```
<scene>/
├── images/
├── mask/          # white = object, black = background; same filename as the image
└── sparse/0/
```

A mask may instead be supplied through the image's alpha channel, as in the preprocessed DTU/BlendedMVS data.

## Training

```bash
python train.py -s <scene> -m <output>
```

## Rendering / mesh extraction

```bash
python render.py -s <scene> -m <output>
```
See the [2DGS README](https://github.com/hbb1/2d-gaussian-splatting#testing) for meshing options.

## Evaluation

`scripts/dtu_eval.py` and `scripts/m360_eval.py` are unchanged from 2DGS; see the [2DGS README](https://github.com/hbb1/2d-gaussian-splatting#full-evaluation) for usage.

## Acknowledgements

This project builds on [2D Gaussian Splatting](https://github.com/hbb1/2d-gaussian-splatting), which builds on [3D Gaussian Splatting](https://github.com/graphdeco-inria/gaussian-splatting). This derivative is released under the inherited [Gaussian-Splatting License](LICENSE.md).

## Citation

```bibtex
@article{woo2026objectaware,
  title   = {Object-Aware Loss for Mask-Guided Mesh Reconstruction Based on 2D Gaussian Splatting},
  author  = {Woo, Sunghyun and Seo, Jeongil and Lee, HeeKyung},
  journal = {Mathematics},
  year    = {2026},
  volume  = {14},
  number  = {17},
  pages   = {3221}
}
```
