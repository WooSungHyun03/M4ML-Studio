# M4ML Studio — 구현 검증 게이트 / 엔지니어링 지시

## Gate C1 — 컬러 Mesh 결함 추적 (P0)
코드 증거(원본 저장소에서 확인한 구현, 로컬 checkout에서 재검증):
- `utils/mesh_utils.py`: `extract_mesh_bounded()`는 `ScalableTSDFVolume(... color_type=RGB8)` → `RGBDImage.create_from_color_and_depth(... convert_rgb_to_intensity=False)` → `volume.integrate()` → `extract_triangle_mesh()`.
- `extract_mesh_unbounded()`는 마지막에 `mesh.vertex_colors`를 지정하는 코드가 있다.
- `render.py`: `o3d.io.write_triangle_mesh()`를 통해 `fuse.ply`, `fuse_post.ply`를 출력한다.
- `post_process_mesh()`는 deepcopy 후 삼각형/정점 필터링; 색상 지속성은 출력에서 반드시 검증한다.

**진단 프로토콜** (실제 산출물로 실행)
1. 소스 PLY(`fuse.ply`와 `fuse_post.ply`), 사용자가 보는 Viewer URL/API/파일 경로, 변환된 PLY/GLB의 동일성·타임스탬프를 비교한다. 잘못된 파일을 열고 있는지 확인.
2. Open3D로 각 파일을 읽어 `has_vertex_colors()`, vertex count, face count, color min/max/mean/std, `np.isfinite`를 기록. PLY property `red/green/blue` 존재 및 값형을 확인.
3. 소스에 컬러가 있는데 변환 결과에 없으면 변환/압축/서빙 단계 수정. GLB/PLY round-trip 비교.
4. 최종 메시에 색이 있는데 Viewer가 무채색이면 `PLYLoader` 등의 `geometry.getAttribute('color')` 검사, `vertexColors:true`, 재질, attribute dtype/range, lighting, toneMapping, geometry index, frontend cache를 수정. Open3D와 Viewer 스크린샷 비교.
5. 소스 메시에 색이 없으면 RGB maps 생성/TSDF integration/color type/후처리 과정 수정. 없는 색을 랜덤/단색으로 채우지 않는다.
6. 3D viewer `색상` 기본 ON, `형상(흰색/단색)`, `와이어프레임` 전환. 모델의 컬러가 보이는 상태로 최초 로드. `no color`는 안내.
7. export된 원본 PLY와 GLB의 색상 메타데이터 + 샘플 이미지로 회귀 검사; 조건 불충족이면 완료 불가.

## Gate C2 — SAM 실시간 클릭 추론 (P0)
- 프런트에는 `prompt_revision` 정수, 현재 포인트 목록, displayed mask revision, pending revision, infer status를 갖는 단일 상태 흐름.
- 클릭 시 화면 좌표를 원본 이미지 좌표로 변환하고 즉시 점 표시 및 프롬프트 상태 저장. 포함=1, 제외=0. 분리된 예측 세션/이미지 id와 함께 자동 요청.
- 백엔드는 SAM 3.1의 실제 point prompt API 검증. 모든 클릭이 GPU 실행을 유발해야 하는 것은 아니나, **최신 포인트 집합에 대한 재추론 작업은 자동 예약**되어야 한다. 복수 클릭이 빠를 경우 짧은 디바운스/취소와 합치기가 가능하다.
- 입력 이벤트 즉각 표시 목표는 가능하면 <100ms. **GPU 추론 완료 시간 보장하지 말 것.** 수백 ms~수초면 진행 중 메시지를 보여준다.
- 응답에는 `project_id`, `frame_id`, `session_id`, `revision`을 포함하여 수신 당시 최신 값과 일치할 때만 적용. 구 버전 응답은 버린다. 클라이언트·백엔드 모두 동시 추론 상한 관리.
- Undo/redo/point deletion/reset도 재추론 자동 트리거. 서빙 실패 시 직전 정상 mask 유지, 실패 배지와 다시 실행을 제공.
- 브러시/지우개 편집은 즉각적인 로컬 픽셀 조작이며 **클릭 프롬프트 추론과 별도**; 한 번 승인한 mask를 재추론이 덮어쓰지 않게 잠금/버전 동기화.
- 클릭으로 다시 추론 버튼 자체가 필요 없게 설계하되, 네트워크/추론 실패의 명시적 `재시도`는 허용.
- 학습 중 GPU 점유가 예상되면 inference와 훈련 job을 동시에 실행하지 않도록 큐를 설정.

## Gate C3 — COLMAP / COLMAP+Mask Import (P0)
검사 모듈 인터페이스 예: `inspect_colmap_import(root, overrides) -> ImportAudit {images, registered, invalid, camera_model, paths, undistortion_state, selected_sparse, repairs, warnings, blocking_errors}`.

1. 입력 폴더 후보를 찾고 `images/`, `sparse/{model_id}/` 또는 사용자 지정 위치를 선택. 원본 또는 undistorted인지 검사.
2. 실제 COLMAP 모델의 `images.bin|txt`를 파싱해 등록 이미지와 pose를 구축. camera intrinsics/points3D를 읽고 이미지 파일 존재와 디코딩, 순서와 name/path를 확인.
3. Object-Aware `scene/dataset_readers.py`가 지원하는 PINHOLE/SIMPLE_PINHOLE로 만들어진 `images`와 `sparse`의 정합성을 확인. distortion이 남았다면 COLMAP `image_undistorter`만 수행하거나 적절한 안내(전체 SfM 재실행 금지).
4. 서로 다른 sparse model들의 이미지 이름 충돌/중복/포즈 프레임 혼합 금지. 사용자가 기본 largest component 외 변경 가능.
5. C 시작 방식에는 등록된 모든 이미지와 마스크 매핑. mask가 RGB 0/255인지, grayscale, alpha PNG, 1bit, uint8, 해상도 불일치 등을 보고. 명백한 0/255 값 정규화는 사용자 확인 후 안전하게 수행. foreground 반전은 자동 추측만으로 시행하지 않음.
6. 데이터가 통과하면 `stage_source=imported`, `stage_state=verified`, `skip_reason=existing_valid_output`로 이력 저장. 이후 선택한 다음 단계 화면을 바로 표시. 사용자 원본 이미지/마스크/포즈를 읽기 전용 취급.
7. 이미 생성된 마스크는 검토 화면에서 열어 재편집할 수 있으며, 훈련 직전 preflight는 강제.
8. partial import / mask 3장 누락 등의 문제는 파일별 정확한 리포트·재매핑·마스크 생성 옵션을 보여준다. 완전한 C로 위장 금지.

## Gate C4 — 재현 가능한 배포와 안정성 (P1)
- 대상 지원 범위를 정하고 `nvidia-smi`, `colmap -h`, torch CUDA, GPU compute capability, VRAM, free disk, 체크포인트 파일 존재/버전을 자동 진단. 기존 `Object-Aware` Python 3.10/PyTorch 2.5.1/CUDA 11.8 anchor와 SAM 3.1 포트 호환성 증거 유지.
- 의존성 잠금, 앱/백엔드 버전, C++/CUDA 확장 빌드·캐싱, 자산(로고) 포함, 체크포인트 경로 설정, UI 빌드 산출물. 소스 폴더 경로를 패키지에 하드코딩 금지.
- 설치 아티팩트 형식은 검증 기반(예: Ubuntu용 .deb + 필요시 GPU 런타임 setup 또는 portable tarball + `install.sh`/`.desktop`). Electron/PyInstaller/AppImage로 **모든 CUDA 의존성이 자동 해결된다고 가정하지 말 것**.
- 패키지가 `127.0.0.1`에만 서버 바인딩하고, 한 사용자당 중복 백엔드 포트 충돌/종료 후 잔류 프로세스가 없는지 검증. 시스템 전체에 인증 없이 서비스 노출 금지.
- 로그와 작업 파일은 사용자 프로필(XDG), 설치본은 읽기 전용 가능. 사용자 데이터는 제거(언인스톨) 시 기본 보존.
- 장애 시 진단 정보 복사/파일 내보내기. 로그에 홈 경로·개인 파일명 등 민감 정보 포함 여부와 동의 동작 확인.
- 버전 업그레이드 후 프로젝트 형식 마이그레이션·백업, 기존 모델 아티팩트 호환성/데이터 보존 검증.
- 배포 전 라이선스·모델 가중치 재배포 권한 확인. Original Gaussian-Splatting license의 비상업 연구/평가 범위를 무시한 상용 배포 금지.

## Gate C5 — GPU 동작과 리소스
- 사용 GPU 자동 탐지 및 사용자 변경 허용. device index와 `CUDA_VISIBLE_DEVICES` 매핑 검증; 해당 프로세스가 실제 선택 GPU로 계산하는지 로그 증명.
- 실 GPU 종류와 여유 VRAM을 보여주고 batch/resolution/quality 권장, 소량 VRAM에서 OOM 복구(설정을 사용자 동의 없이 바꾸지 않음).
- 학습 중 지연·취소·크래시 후 checkpoint 안전성, 단계별 재실행, GPU 작업 직렬화. CPU-only는 학습 불가를 친절하게 설명하고 GUI/파일 열기는 허용.
- GPU가 없거나 체크포인트가 없는 머신에서도 앱이 다운되지 않고 문제를 설명해야 한다.
