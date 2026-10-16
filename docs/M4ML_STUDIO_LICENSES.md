# M4ML Studio 0.3.0 — 라이선스 및 배포 판정

**현재 산출물은 내부 연구·평가용 설치 검증 번들이다. 공개·상업 배포는 보류한다. 법률 전문가 검토는 받지 않았다.** 설치 성공과 재배포 권한 확보는 별도 조건이다. 이번 작업에서 외부 업로드는 수행하지 않는다.

| 포함 요소 | 실제 출처와 고지 | 판정 |
|---|---|---|
| Object-Aware / 2DGS 및 native extensions | 원본 `LICENSE.md`, `submodules/` 라이선스, `SOURCES.json` pin | 비상업 연구·평가 제한 유지. 상업 권한 별도 필요 |
| SAM3.1 코드·호환 패치 | `vendor/sam3/LICENSE`, `licenses/SAM-source-LICENSE`, `patches/` | SAM License 유지, 변경 내역 별도 보존 |
| SAM 체크포인트 | `licenses/SAM-checkpoint-LICENSE` | 가중치 미포함·자동 다운로드 없음. 사용자가 공식 출처 조건을 확인하고 취득 |
| React/ReactDOM/Three/Lucide | `licenses/frontend-MIT-NOTICES` | 해당 MIT/ISC 고지 포함 |
| COLMAP 자체 | `licenses/colmap-runtime/COLMAP-COPYING.txt` BSD-3 | 종속 라이브러리 조건은 별도 |
| 실제 내장47 shared libraries | `licenses/colmap-runtime/inventory.json`에 파일별 SHA256·빌드 패키지·고지 매핑 | 고지는 수집 완료. 결합 바이너리 공개 재배포 검토는 미완료 |
| PoseLib / faiss (정적) | 같은 폴더 BSD-3 / MIT 원문 | 고지 포함 |
| 최소 OpenImageIO2.5.19.1 | Apache-2.0 원문, 실제 custom build 명시 | 고지 포함 |
| SuiteSparse7.6: CHOLMOD/SPQR/AMD 등 | Ubuntu 실제 패키지 copyright + GPL/LGPL 원문 포함 | GPL/LGPL 혼합. corresponding source·relinking·결합 라이선스 검토 필요 |
| cudart12.6.77 | 실제 conda 패키지 CUDA12.6 EULA 원문 | NVIDIA 재배포 가능 구성요소 범위·조건 확인 필요. 드라이버 미포함 |
| SIBR remote viewer (Gaussian-Splatting-Monitor @2b6190c, `runtime/sibr`) | `runtime/sibr/licenses/` (Inria SIBR, GRAPHDECO GS 라이선스), `patches/sibr/`, `SOURCES.json` | 비상업 연구·평가 전용. SIBR 자체 라이브러리만 포함, Ubuntu 시스템 라이브러리(FFmpeg·OpenCV·Qt5 등)는 재배포하지 않음 |
| PySide6 / Qt 6.8.1 (데스크톱 창) | 설치 시 PyPI에서 받는 `PySide6-Essentials/Addons`, `shiboken6` wheel. Qt·PySide6는 LGPL-3.0(일부 모듈 GPL/상용 이중), QtWebEngine은 Chromium 구성요소 고지 포함 | 번들에 넣지 않고 설치 단계에서 받는다. 수정 없이 동적 링크 wheel로 사용. 공개 배포 시 LGPL 고지·교체 가능성 확인 필요(미검토) |
| Logo | 제공된 원본과 원본에서 자른 아이콘 | 제품 식별에 사용. 별도 공개 이용권을 부여하지 않음 |

`NOTICE`는 위 제한을 번들 최상단에서 안내한다. `scripts/collect_colmap_notices.py`는 빌드 호스트의 실제 패키지 저작권 원문을 복사하고47개 라이브러리 매핑과 hash를 기록한다. 단순히 고지를 넣는 것만으로 GPL/LGPL의 소스 제공·재링크 의무가 충족되지는 않는다. 실제 배포 경로에 맞는 corresponding-source 제공, 수정/빌드 자료, relinking 정책과 라이선스 호환성 해결 전에는 공개 가능한 최종 릴리스로 표시하지 않는다. `package_release.py`도 내장 바이너리 포함 시 `--internal-research`를 요구하고 manifest에 공개 승인 `false`를 기록한다.

Python/Torch/Open3D/Conda 패키지는 설치 시 각 배포처에서 별도로 받는다. 개인 Python 환경·NVIDIA 드라이버는 번들에 포함하지 않는다. 이들 패키지의 자체 라이선스도 적용된다. 체크포인트·사진·프로젝트·실행 로그·비밀 키는 Git/번들에서 제외한다.

공식 검토 근거(2026-10-16 확인): [SAM License](https://github.com/facebookresearch/sam3/blob/main/LICENSE), [SuiteSparse 공식 저장소](https://github.com/DrTimothyAldenDavis/SuiteSparse), COLMAP 로컬 COPYING의 종속 라이선스 별도 적용 문구. 보존한 로컬 pin의 원문이 이 번들의 기준이다. 모델 취득은 [공식 SAM 저장소](https://github.com/facebookresearch/sam3)의 SAM3.1 안내/공식 가중치 링크에서 수행한 뒤 **설정 → 객체 선택 모델 파일**에 경로를 지정한다. 가중치 재배포 권한을 제품이 대신 부여하지 않는다.

## 내부 사용과 공개 배포의 구분

| 구분 | 현재 상태 |
|---|---|
| 내부 연구·평가용 설치(이 저장소/내부 압축본) | 허용 범위에서 사용 가능. 원본 비상업 조건과 SAM 이용 조건을 따른다 |
| 공개 다운로드·외부 배포 | **보류**. SuiteSparse GPL/LGPL 소스 제공·재링크, CUDA 재배포 조건, Qt/PySide6 LGPL 고지 검토가 끝나지 않았다 |
| 상업적 사용 | **불가**(원본 Gaussian Splatting 계열 라이선스가 비상업 연구·평가로 제한). 별도 권리 확보 필요 |

이 문서는 법률 검토 결과가 아니며, 위 항목이 해결되었다고 주장하지 않는다.
