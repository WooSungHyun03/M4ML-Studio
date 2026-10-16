# M4ML Studio

여러 사진에서 객체를 클릭해 선택하고, 마스크를 확인한 뒤 GPU 학습으로 **실제 색상을 가진 3D 메시**를 만드는 Ubuntu 로컬 앱입니다. 사진·마스크·모델은 컴퓨터 안에 저장합니다. 로그인이나 클라우드 업로드는 없습니다.

**0.3.0 내부 연구·평가용 빌드입니다.** 기술 검증과 공개 재배포 승인은 별개입니다. SuiteSparse GPL/LGPL 소스 제공·재링크/결합 배포 검토와 원본 비상업 연구 조건 때문에 공개·상업 릴리스는 보류합니다. [배포 판정](docs/M4ML_STUDIO_RELEASE_STATUS.md), [라이선스](docs/M4ML_STUDIO_LICENSES.md), [시험 보고서](docs/TEST_REPORT.md)를 확인하세요. 공개 다운로드 URL은 제공하지 않습니다.

## 지원 환경과 준비

- 실제 검증: **Ubuntu24.04 x86_64, RTX4080 16GB, NVIDIA580.173.02**. 새로운 non-root Ubuntu24.04 컨테이너도 같은 물리 GPU에서 검증했습니다. 다른 GPU/Ubuntu22.04/Wayland 데스크톱 전체는 인증하지 않았습니다. 16GB는 검증 장비 용량이며 최소 VRAM 보장값이 아닙니다.
- 내장 카메라 정합 엔진은 GPU COLMAP4.2.1/CUDA12.6이며 glibc2.39 이상이 필요합니다. 드라이버580에서 실제 동작을 확인했습니다. CUDA12 minor compatibility의525 하한만으로 모든 GPU·PTX 실행을 보장하지 않습니다. 드라이버를 자동 변경하지 않습니다.
- Python3, Git, GCC/G++11, Conda(Miniforge 등), 기본 GL/EGL/GLib/OpenMP 라이브러리를 먼저 준비합니다. 컨테이너의 정확한 준비 패키지/버전과 검증 범위는 [시험 보고서](docs/TEST_REPORT.md)를 보세요. GPU Python 환경은 **Python3.10 / Torch2.5.1+cu118 / NumPy1.24.4** 하나를 유지합니다.
- 최초 환경 설치에는 인터넷과 여유 저장 공간이 필요합니다. 이후 모델과 환경이 준비되면 정적 UI/로컬 계산은 CDN·원격 인증 없이 실행됩니다. 배포본 사용에는 Node가 필요하지 않습니다.

## 설치와 최초 실행

내부 검증 압축본과 같은 이름의 SHA256 파일을 받은 폴더에서:

```bash
sha256sum -c M4ML-Studio-0.3.0-linux-x86_64.tar.gz.sha256
tar -xzf M4ML-Studio-0.3.0-linux-x86_64.tar.gz
cd M4ML-Studio-0.3.0
./scripts/install.sh
```

설치 후 Ubuntu 앱 메뉴의 **M4ML Studio** 또는 다음 명령으로 엽니다.

```bash
python3 scripts/launch.py
```

기본 접속 주소는 http://127.0.0.1:8765 입니다. 실행 아이콘의 등록·실제 Exec 인자 실행은 컨테이너에서 시험하며, GNOME 메뉴를 마우스로 누르는 전체 데스크톱 시험은 별도입니다.

SAM3.1 가중치는 포함하지 않습니다. [공식 모델 안내](https://github.com/facebookresearch/sam3)에서 이용 조건을 확인해 **SAM3.1 multiplex 체크포인트**를 직접 준비하고, 앱 **설정 → 모델 파일**에서 신뢰하는 `.pt` 경로를 저장하세요. 파일 존재 확인 후 최초 추론에서 실제 구조를 검사합니다. 개발 PC의 고정 경로에 의존하지 않습니다.

Conda를 못 찾으면 `STUDIO_CONDA=/실제/conda/경로 ./scripts/install.sh`를 사용합니다. GPU 없는 결과 확인용은 `./scripts/install.sh --viewer-only`입니다. 이 모드는 학습/객체 추론을 다른 모델로 대체하지 않고 차단합니다.

소스 체크아웃은 `./scripts/setup.sh`, `./scripts/start.sh`, `./scripts/doctor.sh`를 사용합니다. UI 재빌드에만 Node22/npm 및 `npm ci --prefix frontend && npm run build --prefix frontend`가 필요합니다.

## 새 프로젝트와 기존 데이터

홈에서 프로젝트 이름과 시작 방식을 선택합니다.

1. **이미지부터 시작(A)**: 겹치는 선명한 사진을 불러오고 **불러오기 완료**를 누릅니다. GPU 특징점·매칭, CPU 자세 추정·왜곡 보정을 거친 **등록 성공 이미지**만 다음으로 전달됩니다. 매칭 성공과 포즈 등록은 별도 표시합니다.
2. **카메라 정합 결과 가져오기(B)**: 사진과 `sparse/0/{cameras,images,points3D}.bin` 또는 `.txt` 폴더를 지정합니다. 기존 카메라를 검증해 재사용하며 처음부터 정합하지 않습니다. 필요할 때 왜곡 보정만 실행합니다.
3. **카메라 정합 + 마스크 가져오기(C)**: B 자료와 이미지별0/255 마스크를 함께 가져옵니다. 기본값은 흰색=객체입니다. 이름·크기·반전/알파 설정을 확인합니다. 누락·손상 파일이 있으면 학습을 차단하며 파일별 원인을 표시합니다.

객체 안을 클릭하면 포함, **Alt+클릭/오른쪽 클릭**은 제외합니다. 별도 추론 버튼 없이 자동 갱신하며 연속 클릭의 최신 결과만 표시합니다. 첫 클릭은 모델 로딩 시간이 필요하고 이후 모델을 유지합니다. 전파 결과를 확인하거나 유효한 마스크의 남은 검토만 명시적으로 건너뜁니다. 붓 수정은 저장해야 하며 다른 승인 프레임은 보호됩니다.

## 학습·중단·색상 내보내기

마스크 검토 후 **3D 재구성 → 학습 시작**에서 GPU/반복 수를 확인하고 승인합니다. 원본 Object-Aware Loss의 masked L1·polarization·pruning 및2DGS 기하 손실을 사용합니다. 기본30000회를 임의로 줄이지 않습니다. 실제 손실/절대 반복 수/로그를 표시합니다.

**일시정지**는 마지막 저장 지점을 보존하며 입력이 바뀌지 않았으면 그 지점부터 재개합니다. 기본 저장 간격2500회이므로 마지막 저장 후 진행분은 잃을 수 있습니다. 사진·마스크 변경 후에는 이전 체크포인트를 무조건 재사용하지 않습니다.

학습 후 실제 TSDF 추출이 자동 실행됩니다. 기본 보기는 **컬러**이며 형상/와이어프레임·회전·이동·확대·화면 맞춤을 지원합니다. **PLY/GLB 내보내기**는 실제 정점 색상을 보존합니다. 색상이 없는 외부 메시에는 색상이 없다고 표시하며 색을 만들어 넣지 않습니다. 가려진/부족한 사진은 부분 표면과 구멍을 만들 수 있고 수밀성을 보장하지 않습니다.

## 저장과 오류 해결

새 사용자의 프로젝트·런타임은 `~/.local/share/m4ml-studio`, 설정은 `~/.config/m4ml-studio`, 실행 로그는 `~/.cache/m4ml-studio`입니다. 기존 Object-Aware 데이터가 있으면 그 위치를 보존합니다. `STUDIO_DATA`, `STUDIO_RUNTIME`, `STUDIO_PORT`로 위치/포트를 지정할 수 있습니다. 변경은 자동 저장되고 붓의 미저장 수정은 따로 표시합니다.

- **GPU/모델 없음**: 설정의 처리 장치·모델 파일, 고급 정보 및 `./scripts/doctor.sh` 결과를 확인하세요. 앱을 열어 결과를 보는 것은 가능합니다.
- **메모리 부족**: 이전 정상 마스크·점·로그가 보존됩니다. 다른 GPU 작업을 정리하거나 고급 설정에서 해상도를 직접 낮춰 재시도하세요.
- **정합 실패**: 매칭/등록 수와 실패 이미지를 확인하고 겹침·흔들림·시점 간격을 개선하세요.
- **마스크 누락/불일치**: 파일별 오류를 수정하거나 카메라만 가져와 마스크를 새로 만드세요. 임의 통과하지 않습니다.
- **중단/재실행**: 프로젝트를 다시 열고 마지막 검증 단계에서 이어갑니다. 부분 출력은 완료로 취급하지 않습니다.
- **제거/업데이트**: 앱 종료 후 `./scripts/install.sh --uninstall`. 실행 메뉴와 앱 설치본만 보관 폴더로 옮기며 프로젝트·런타임은 유지합니다. 다른 버전은 별도 폴더에 설치하고, 같은 버전의 다른 내용은 덮어쓰지 않습니다.

상세한 [사용자 안내](docs/M4ML_STUDIO_USER_GUIDE.md), [기능 감사](docs/FUNCTIONAL_AUDIT.md), [진행 기록](docs/STATUS.md), [원본 라이선스](LICENSE.md), [NOTICE](NOTICE)를 함께 제공합니다.

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
