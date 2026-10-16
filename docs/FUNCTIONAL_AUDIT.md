# M4ML Studio 0.3.0 기능 감사

2026-10-16 복구 감사. `PASS`는 표의 시험 범위에 한한다. 이전 Claude 실행은 로그와 파일을 재검사한 증거로 구분하며 이번에 새로 학습한 것으로 세지 않는다. 현재 릴리스 최종 판정은 `M4ML_STUDIO_RELEASE_STATUS.md`를 따른다.

| 기능 | 실제 구현 / 변경 파일 | 상태·증거 |
|---|---|---|
| 이미지 import/정규화/중복/EXIF/파일 안전성 | `studio/importer.py`, `stages/ImagesStage.tsx` | PASS:52 회귀, 실제20장 브라우저 import |
| GPU 카메라 정합 / matched≠registered | `providers/camera_colmap.py`, `engines.py`, `CameraStage.tsx` | PASS: 내장4.2.1 실제 GPU 관측·20장 정합. mapper/undistorter는 CPU. 이전128장 측정은 재빌드하지 않고 보존 |
| 선택한 sparse component/왜곡 보정/학습 입력 검사 | `colmap.py`, `colmap_import.py` | PASS: 기존 실제 복수 component·distorted/ASCII import + 현재 회귀 |
| 시작 방식 A/B/C | `ImportPanel.tsx`, API/import/worker | PASS: 이전 `e2e-0.3/result.json`, 이번 `v03-ABC-artifact-reaudit.json`. A6000/B·C1000회 결과를 재검사. 이번 브라우저 A 전체 시험은 별도 TEST_REPORT에 기록 |
| 공식 모델 상주 추론 | `sam31_session.py`, `segmentation_session.py` | PASS: 실제3.1 체크포인트·단일 anchor Python; 실제 클릭마다 모델 재로딩하지 않음. 첫 로딩/엔진 시간/브라우저 왕복 시간 구별 |
| 자동 positive/negative / latest-wins | `live_prompt.py`, `useLivePrompt.ts`, `MaskEditor.tsx` | PASS: 실제 Alt 제외점/5연속 점/프레임 전환. session/reference/revision 일치만 게시. 회귀4개는 GPU 대체 증거가 아님 |
| HUD 클릭/사진 준비/zoom 좌표 | `MaskEditor.tsx`, `ui_e2e.mjs` | 수정·PASS: 상단/하단 안내 pointer-events 통과, 미디코딩 캔버스 입력 차단, focus(preventScroll)로 확대 클릭 시 스크롤 좌표 이동 해결. 이전 실패 로그 보존 |
| 전파/마스크 QA/검토/skip/승인 보호 | `sam31.py`, `worker.py`, `MaskStage.tsx` | PASS: 기존A24/B16 GPU, 이번 브라우저20. 유효한 마스크만 skip; 기존 실패에서 빈 마스크 학습 차단 실제 관찰 |
| 붓/지우개/저장/undo/redo/탐색 | `MaskEditor.tsx`, `MaskStage.tsx`, API | PASS: 기존 실제 UI/manual evidence·현재 회귀. 점 자동 저장과 붓 명시적 저장 구별. 일반 사용자 접근성 연구는 미실시 |
| 원본 학습·loss·선택 GPU | `providers/training_object_aware.py`, worker, `TrainStage.tsx` | PASS: 원본 코드 diff 없음. 이전30K/0.3 A6000 실학습과 이번 영향 범위 회귀. 브라우저 신규 실행 결과는 TEST_REPORT 참조 |
| 일시정지 / checkpoint 재개 / 절대 iteration | training provider/API | PASS: 이전2700중단→2500저장지점→6000재개. 현재 파일149625 Gaussians, checkpoint와 로그 재검사. 입력 fingerprint 변경 시 재개 금지 |
| 전체 loss history | API training-metrics / `LossPlot.tsx` | PASS: 원문 전체 로그를 서버에서 파싱·샘플링. 임의 손실 생성 없음. 재개 이전/이후 절대 iteration 유지 |
| 컬러 TSDF / PLY / GLB | original `render.py`, `mesh.py`, mesh/export providers | PASS: A218825/B35588/C33994정점 RGB와 GLB COLOR_0 현재 재검사. 원본 알고리즘 무변경. sRGB→linear roundtrip5.96e-8 |
| 컬러 기본 Viewer / 회전·pan·zoom·mode·export | `MeshViewer.tsx`, `ModelStage.tsx` | PASS: 실제A 컬러 뷰어1366 캡처, 현재 전체 브라우저 및 별도 viewer 조작/내보내기 시험 PASS. 색상 없는 입력은 색 없음. 부분/구멍 있는 형상은 품질 한계 그대로 표시 |
| 자동 저장 / 재시작 / stage audit | Store/SQLite/manifest | PASS: 이전 재시작·corruption 검사 + 현재54회귀.0.3별 SQLite 백업으로0.2 백업 유지 |
| 설정 schema2 / provider registry | `config.py`, `engines.py`, `providers/*` | PASS: migration/backup/deep merge/unknown provider 계약 테스트. 대체 연구 모델 미포함 |
| GPU/CPU 선택 | camera provider/CameraStage | PASS: 이전 실제 CPU554초/GPU192초 비교 + CPUflag 회귀. GPU 없음은 명확히 차단, 결과 보기 유지 |
| dark/light / 로고 / 고급 정보 | App/style/SettingsDrawer/실제 Logo | PASS: 실제 dark/light·고급 정보·1366/1920 캡처. 기본 작업명, import 파일 형식의 COLMAP 언급은 사용자 선택에 필요하므로 유지 |
| 진단/종료/취소/프로세스 정리 | API/process/session/gpu_lock | PASS: 이전 실제OOM·owner death·취소 + 현재54회귀. 외부 서비스 프로세스를 무차별 종료하지 않음 |
|0.3 설치/이동 경로/읽기 전용/제거 | install/launch/setup/package scripts | PASS: 실제 신규 사용자0.3 설치·read-only·desktop argv·종료·재설치·설치본 A/B/C GPU 모두 통과. hardcoded0.2 제거 오류 수정 |
| 배포 라이선스 | NOTICE/47-lib inventory/원문 고지 | 기술적 고지 PASS, **공개 배포 BLOCKED**. GPL/LGPL source/relinking·결합 검토 및 비상업 제한 미해결. 법률 검토 없음 |

미해결 제한: 공개/상업 재배포 권한·의무 정리, 다른 GPU/드라이버·Ubuntu22.04·GNOME 메뉴 마우스 실행 검증, 실제 외부 신규 사용자의 사용성 연구. 전파는 임의 멀티뷰의 정합성을 수학적으로 보장하지 않으며 출력은 완전/수밀 형상 보장이 아니다. 브라우저 SwiftShader 시험과 실제 CUDA 계산을 혼동하지 않는다.

최종 설치기 추가 회귀: manifest 파일만 원자적으로 설치하며 추출 폴더의 추가 `.env`/weights 등을 복사하지 않는다. 상대 경로 이탈·외부 symlink·잘못된 버전은 차단하고 원본 파일은 보존한다. 실제 파일 기반 회귀를 포함한 최종 Python54 PASS. 고정 아카이브 QA는 번들 옆 QA.json 및 STATUS 마지막 항목에 기록한다.
