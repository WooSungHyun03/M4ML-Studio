# M4ML Studio — 제품화 Acceptance Tests

**수칙:** 모든 항목에 `PASS / FAIL / NOT TESTED` 및 실행 명령/브라우저·GPU 정보/산출물/로그를 기록. Mock/fixture의 통과를 실제 GPU E2E로 간주하지 않는다. 아래의 `P0`는 배포 차단.

| ID | 우선순위 | 시험 항목 | 관찰 가능한 합격 조건 |
|---|---|---|---|
| A01 | P0 | 제품명 | 설치 화면·창 타이틀·헤더·About·README 등 모두 `M4ML Studio` |
| A02 | P0 | 로고 | 실제 `Logo/` 원본에서 선택, UI와 앱 아이콘에 일관되게 표시, 비율 왜곡·손상 없음 |
| A03 | P1 | UI 스타일 | 주요 화면 1366×768·1920×1080 캡처; 읽기 쉬운 정보계층, 불필요한 템플릿 장식 제거 |
| A04 | P1 | 키보드/접근성 | 마스크 주요 기능과 탐색이 키보드 사용 가능; 포커스·레이블·명암 정상 |
| A05 | P0 | 이미지 시작(A) | 원본 다중 이미지 import 후 실제 COLMAP 및 등록 이미지 결과 표시 |
| A06 | P0 | COLMAP import(B) | 이미 검증된 sparse+이미지로 진입, COLMAP 재실행 없이 SAM 단계로 이동 |
| A07 | P0 | COLMAP+Mask import(C) | 카메라/마스크 매핑 검증 후 SAM 재생성 없이 학습 준비 단계로 이동 |
| A08 | P0 | Import B 오류 | sparse 모델 또는 등록 이미지가 손상/누락되면 정확한 원인과 파일명 표시, 잘못된 건너뛰기 금지 |
| A09 | P0 | Import C 오류 | 마스크 일부 누락/잘못된 크기/다른 이름이면 학습 차단 및 파일별 수리 안내 |
| A10 | P0 | COLMAP 구성 요소 | 서로 다른 sparse components를 임의로 합치지 않으며 사용자가 선택 가능 |
| A11 | P0 | 카메라 좌표/이미지 | undistorted 이미지와 PINHOLE intrinsics/pose 정합성 검사, 필요할 때만 undistorter 실행 |
| A12 | P0 | 프롬프트 positive | positive 1회 클릭으로 점 즉시 나타나고 실제 SAM 3.1 새 예측 자동 실행(별도 버튼 없음) |
| A13 | P0 | 프롬프트 negative | negative 클릭으로 해당 점을 포함한 새 예측 자동 실행 |
| A14 | P0 | 빠른 연속 클릭 | 연속 5회 이상의 비동기 요청에서도 최신 프롬프트 revision mask만 화면 반영 |
| A15 | P0 | Undo/redo | 점 삭제/undo/redo 후 자동으로 mask 재추론되고 저장된 최종 점 상태와 일치 |
| A16 | P0 | 클릭 중 GPU 실패 | 실패를 표시하고 기존 정상 mask와 사용자 입력을 보존, 재시도 가능 |
| A17 | P0 | 수동 마스크 수정 | 브러시/지우개 반영 즉각적; 저장 후 재열기/승인/학습 입력까지 동일 |
| A18 | P0 | mask propagation | SAM 3.1 실제 모델 + 체크포인트로 여러 등록 프레임에 후보 마스크 생성; 잘못된 프레임 수정 가능 |
| A19 | P0 | 승인 잠금 | 임의 재전파로 이미 승인된 다른 프레임 mask를 묵시적으로 덮어쓰지 않음 |
| A20 | P0 | mask review skip | 건너뛴 프레임은 `검토 생략`, 잘못된 마스크까지 유효 승인하지 않음 |
| A21 | P0 | 기존 Mesh color | color PLY/GLB 가져오면 실제 원본 색상이 기본 Viewer에 정상 표시 |
| A22 | P0 | 추출된 Mesh color | Object-Aware `render.py` bounded TSDF로 생성한 `fuse.ply` 또는 `_post.ply`가 실색상을 가지고 Viewer에 정확히 표시 |
| A23 | P0 | 색상 round-trip | PLY → GLB → Viewer에서 정점 색상이 유지되고 color 정보 유무가 검증됨 |
| A24 | P0 | Mesh loss diagnostic | 원본/변환 파일 중 color가 사라지는 구간을 검사하고 실패 로그가 남음 |
| A25 | P1 | Mesh UI | 회전·pan·zoom·fit·reset·컬러/형상/와이어프레임 전환 정상 |
| A26 | P0 | 실제 학습 | 원본 Object-Aware loss/pruning 과정으로 실 CUDA 학습 시작, Loss/iteration 체크·유효 checkpoint |
| A27 | P0 | GPU 선택 | 선택한 NVIDIA GPU가 실제 subprocess CUDA 연산에 사용됨을 로그로 검증 |
| A28 | P0 | 프로젝트 영속성 | 앱 재실행 후 import mapping, 승인 mask, 훈련/메시 상태 복구 |
| A29 | P0 | 취소·안전 | COLMAP/학습 취소와 재시도 시 남은 프로세스/부분 파일이 파괴적 결함을 유발하지 않음 |
| A30 | P0 | 새 설치 | 깨끗한 지원 Ubuntu 환경에 문서만 따라 설치하고 실행 아이콘으로 로고 포함 앱을 띄울 수 있음 |
| A31 | P0 | 첫 실행 검사 | GPU/드라이버/환경/COLMAP/체크포인트 누락 시 앱 종료 대신 명확한 안내 |
| A32 | P0 | 독립 설치경로 | `/home/m4ml` 없는 신규 사용자 계정에서도 앱 시작 및 적절한 데이터 경로 사용 가능 |
| A33 | P0 | 배포 라이선스 | 서드파티 LICENSE/NOTICE, SAM weights 재배포, GS 비상업 조건 검토/문서화 |
| A34 | P1 | 개인정보 | localhost-only, 임의 네트워크 업로드 없음, 로그 경로/데이터 안전성 검증 |
| A35 | P1 | 사용자 매뉴얼 | 3개 시작 방법, 이미지 품질 팁, mask edit, 학습, Mesh export, 자주 생기는 오류 해결 설명 |
| A36 | P1 | 배포 업데이트 | 기존 사용자 프로젝트 데이터 유지한 상태에서 앱 업데이트/재설치 가능 |
| A37 | P0 | 회귀 테스트 | 기존 처음부터 E2E 경로의 주요 기능이 업데이트 이후에도 작동 |

## 필수 실물 Fixture
1. 원본 촬영 이미지가 있고 COLMAP pose 등록이 되는 작은 실데이터(테스트 목적 사용 허가 필요).
2. 이미 COLMAP이 성공한 실제 데이터(이미지와 sparse 포함).
3. B의 데이터에 사용자 지정 0/255 바이너리 mask가 있는 실제 데이터.
4. 고유한 빨강·초록·파랑을 가진 정점 색상 PLY, 해당 색상 유지 GLB.
5. 기존 Object-Aware 학습으로 생성한 실 `fuse.ply` / `fuse_post.ply`.
6. 누락된 mask/잘못된 intrinsics/빈 mesh/중복 이름 등 네거티브 fixture.

테스트 실데이터가 로컬에 없으면 해당 테스트를 `NOT TESTED`로 남기고 재현 스크립트까지 구현한다. 실제 PLY 색상 유무가 검증되지 않았는데 뷰어만 교체했다고 A22를 PASS하지 않는다.
