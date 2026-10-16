# Object-Aware Reconstruction Studio

Ubuntu/Linux에서 사진을 불러오고, **실제 COLMAP → SAM 3.1 → 마스크 검토 → 원본 Object-Aware 학습 → 원본 2DGS/TSDF → 3D 메시**를 실행하는 로컬 앱입니다. 일반 실행에는 외부 서버·계정·CDN이 필요하지 않습니다.

## 설치와 실행

이 저장소와 하위 모듈, 로컬 SAM 3.1 체크포인트가 필요합니다. 체크포인트는 배포에 포함되지 않으며, 자동으로 내려받지 않습니다.

```bash
cd /home/m4ml/Desktop/Object-Aware
./scripts/setup.sh
./scripts/start.sh
```

브라우저에서 [스튜디오 열기](http://127.0.0.1:8765)를 선택하세요. 종료는 실행 터미널의 `Ctrl+C`입니다. 서버 종료 시 실행 작업도 중지하며, 파일과 로그를 보존합니다.

설치에는 인터넷, Conda, Node/npm, COLMAP, GCC/G++11 및 NVIDIA 드라이버가 필요합니다. 기존 전역 Python/Conda 환경을 수정하지 않고 이 프로젝트의 `.runtime/`만 구성합니다. 설치 스크립트는 Python3.10, Torch2.5.1/cu118, torchvision0.20.1, NumPy1.24.4와 CUDA11.8 빌드 도구를 사용합니다. Node는 UI 빌드 때만 사용합니다.

- Conda 위치가 다르면 `STUDIO_CONDA=/경로/conda ./scripts/setup.sh`로 지정합니다.
- 이미 설치된 COLMAP·GCC·드라이버를 먼저 확인하세요. 시스템 패키지는 설치 스크립트가 `sudo`로 변경하지 않습니다.
- 검증한 장비는 Ubuntu24.04 / RTX4080 16GB / NVIDIA580.173.02입니다. 다른 GPU·드라이버 조합은 먼저 진단과 실제 추론 검증을 실행해야 합니다. CUDA11.8로 빌드할 수 없는 최신 GPU에 대해 Torch를 자동 업그레이드하지 않습니다.
- 원본 소스를 새로 받을 때에는 `git clone --recursive`를 사용합니다. 기존 작업 폴더에 덮어쓰지 마세요.

```bash
./scripts/doctor.sh
./scripts/smoke.sh
```

`doctor`는 설치·GPU·원본 확장·체크포인트 목록을 확인합니다. 이 명령의 성공만으로 SAM/학습 E2E를 통과했다고 표시하지 않습니다. 실제 GPU 증거와 알려진 한계는 [검증 기록](docs/STATUS.md)에 있습니다.

## 작업 순서

1. **새 프로젝트**를 만들고 파일·폴더 선택 또는 드래그로 사진을 불러옵니다. 방향과 파일 이름을 정리하고, 중복·손상·흐림 가능성을 표시합니다. 원본은 수정하지 않습니다. 최소2개의 다른 사진이 필요하며, 충분히 겹치는 여러 시점을 권장합니다.
2. **불러오기 완료·재구성 시작**을 누릅니다. COLMAP 특징점·검증된 매칭·실제 등록 카메라를 각각 확인합니다. 기본으로 가장 큰 일관된 그룹을 선택하며 다른 그룹을 직접 선택할 수 있습니다. 한 그룹의 왜곡 보정된 사진만 다음 단계로 갑니다.
3. 등록 사진에서 **대상 추가(+)**와 **배경 제외(−)**를 클릭합니다. Alt/오른쪽 클릭도 배경 제외입니다. **SAM 3.1 미리보기**를 실행하고 대상을 확인한 뒤 **대상 확인·전체 전파**를 누릅니다.
4. **이전 / 다음**, 붓·지우개, 확대·이동, 실행 취소·다시 실행으로 수정하고 **저장·승인**합니다. Shift+드래그는 사진 이동입니다. **남은 검토 모두 건너뛰기**는 확인 후 유효한 자동 마스크에만 적용됩니다. 누락·빈 마스크·잘못된 크기는 학습을 계속 차단합니다.
5. GPU, 마스크 검증, 반복 횟수, 사진 해상도를 확인하고 **학습 시작**을 명시적으로 승인합니다. 원본 기본값은30,000회입니다. 원본 손실·가지치기 수식과 일정은 바꾸지 않았습니다. 진행 수치와 손실은 실제 프로세스 로그에서 읽습니다.
6. 학습 파일 검증 후 원본 TSDF 추출이 자동 실행됩니다. 실제 삼각형 메시를 회전·이동·확대하고 맞춤·와이어프레임·정점 색상·조명을 조정합니다. 원본 PLY 또는 검증된 GLB 변환본을 내보낼 수 있습니다.

학습을 시작하기 전에 검토·대상 확인을 생략하지 않습니다. 중지·오류·재시작 시 실행을 완료로 꾸미지 않으며, 기존 파일을 남긴 새 실행으로 다시 시도합니다. 검증되지 않은 체크포인트 이어 학습은 UI에 노출하지 않습니다.

## 저장 위치와 설정

기본 작업 저장 위치는 `~/.local/share/object-aware-studio/`입니다. 프로젝트별 `manifest.json`, 정규화 사진/원본 스냅샷, COLMAP DB/컴포넌트, 마스크·프롬프트·검토 상태, 학습·메시·로그를 보관합니다. SQLite/WAL 상태와 실제 결과 파일을 재시작 시 다시 확인합니다. 파일이 사라지거나 바뀌면 관련 완료 상태를 취소합니다.

```bash
STUDIO_DATA=/큰디스크/작업 STUDIO_PORT=8765 ./scripts/start.sh
STUDIO_SAM_CHECKPOINT=/신뢰할수있는/체크포인트.pt ./scripts/start.sh
```

서버는 `127.0.0.1`에만 바인딩합니다. 체크포인트는 공식 SAM3.1 구조와 전체 가중치 키·크기가 일치해야 합니다. 기존 `models/sam3.1/sam3.1_multiplex.pt`는 실제 검사한 기본 경로입니다. 원본 코드와 체크포인트 출처를 확인하세요.

## 문제 해결과 한계

- **등록 실패:** 대상 주변을 겹치게 촬영한 선명한 사진을 추가하고, 전체/인접 매칭 방식과 실제 등록 수를 확인하세요. 매칭 성공이 카메라 등록을 뜻하지 않습니다.
- **전파 오류:** SAM3.1은 시간 순서 추적 모델입니다. 카메라 위치·방향으로 순서를 정해도 임의의 넓은 시점 간 일관성을 보장하지 않습니다. 가림·시점 점프·면적 변화 경고를 확인하고 클릭이나 붓으로 수정하세요. 승인된 마스크는 재전파로 덮어쓰지 않습니다. 새 대상은 새 프로젝트로 작업하세요.
- **GPU 메모리 부족:** 실행 로그를 확인하고 다른 GPU 작업을 종료하세요. 학습 해상도를 명시적으로 낮춰 재시도할 수 있습니다. 손실 가중치를 자동으로 바꾸지 않습니다.
- **설치 중 `cicc` 오류:** 시스템의 nvcc 심볼릭 링크만으로는 툴킷이 충분하지 않습니다. 스크립트가 설치하는 `.runtime`의 CUDA11.8 전체 컴파일 경로를 사용합니다.
- **메시가 불완전함:** 추출 성공이 품질·수밀성·완전한 형상을 보장하지 않습니다. 검증 샘플은 건물 일부가 나무에 가려진16시점이므로 부분 표면과 구멍이 있습니다. 대상 주위를 충분히 촬영한 입력과 마스크 검토가 필요합니다.
- **브라우저3D 오류:** 하드웨어 가속/WebGL을 확인하세요. 실제 PLY는 그대로 보존됩니다.

## 라이선스와 연구 출처

원본 Gaussian-Splatting 계열은 **비상업적 연구·평가용** 제한이 있습니다. 상업적 배포 권한을 보장하지 않습니다. [원본 라이선스](LICENSE.md), 하위 모듈 라이선스, [SAM 소스 및 체크포인트 약관](licenses/SAM-checkpoint-LICENSE), [프런트엔드 고지](licenses/frontend-MIT-NOTICES)를 함께 확인하세요. 모델·데이터·사용자 결과는 Git에 포함하지 않습니다.

- 원본 학습/추출: [WooSungHyun03/object-aware-loss](https://github.com/WooSungHyun03/object-aware-loss), SHA `3221821b165865dc77b7636598e55675043b87f4`.
- 공식 SAM3.1: [facebookresearch/sam3](https://github.com/facebookresearch/sam3), SHA `7f473cfd983d5eb43040ff608f66bff0d7bdcb53`; 최소 호환 패치는 [patches/sam3](patches/sam3/README.md)에 기록했습니다.
- [원 논문](https://www.mdpi.com/2227-7390/14/17/3221).

아래는 보존한 원본 저장소 README입니다.

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
