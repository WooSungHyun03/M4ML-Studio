# M4ML Studio 0.5 — 현재 Quality Harness 판정

2026-10-16: 내부 연구용 실제 검증 범위는 [Quality Harness 보고서](QUALITY_HARNESS_REPORT.md)를 기준으로 한다. 새16장 GPU COLMAP/SAM3.1/원본30000회/TSDF1024 컬러 메시,12500회 재개, 신규 non-root 설치본 B/C 각1000회, 네이티브 파일 I/O를 실행했다. **공개·상업 배포 HOLD**이며 직접 SIBR 소켓의 로컬 사용자 인증과 다른 하드웨어/Wayland/외부 초보자 연구는 미해결·미검증이다. 최신 고정 압축본의 체크섬·설치 결과는 번들 옆 QA 및 quality-harness/state/EVIDENCE.md에 기록한다.

아래0.3 보고는 과거 증거로 보존한다. 현재0.5의 모든 게이트가 통과했다는 뜻이 아니다.

---

# M4ML Studio 0.3.0 릴리스 판정

2026-10-16: **실제 GPU 파이프라인·브라우저·신규 사용자 설치 검증 PASS / 내부 연구·평가 빌드. 공개·상업 배포 BLOCKED.** 최종 고정 아카이브의 무결성·설치 후 실행 기록은 번들 옆 QA 기록과 `STATUS.md` 최신 항목을 함께 확인한다. 여기의 PASS는 명시된 장비/시험 범위에 한한다.

검증 장비는 Ubuntu24.04 x86_64 / RTX4080 16GB / NVIDIA580.173.02이다. 깨끗한 사용자 환경은 별도 Docker 컨테이너·UID1101·새 HOME·새 Python runtime을 사용했다. 동일 물리 GPU를 공유하므로 다른 GPU 인증은 아니다. 모델은 사용자 제공 공식 체크포인트를 read-only로 지정했다.

| ID | 판정 | 실제 증거 / 범위 |
|---|---|---|
| A01 | PASS |0.3 UI/title/API/README/install branding, 버전 불일치 수정 |
| A02 | PASS | 실제 Logo 원본2종·파생 아이콘, 실제 설치 desktop entry/스크린샷 |
| A03 | PASS | `v03-final-screens/`:6단계·홈·테마1366/1920. 자동 흐름/육안 점검, 외부 사용자 연구는 미실시 |
| A04 | PASS (기능 범위) | 실제 클릭/Alt/키보드undo·redo·Space/탐색, 레이블·포커스 및 픽셀 좌표. 전체 스크린리더/WCAG 인증 미실시 |
| A05 | PASS | `ui-e2e-v03-complete/`:원본16장 새GPU 정합→학습/mesh. 설치본A도 PASS |
| A06 | PASS | 설치본 B 기존 pose 재사용, 정합 재실행 없음 |
| A07 | PASS | 설치본 C 기존 pose/mask 재사용, SAM/정합 재실행 없음 |
| A08 | PASS | importer 음성/파일별 실패 회귀, 기존 실제ASCII/distorted 변형 증거 |
| A09 | PASS | 누락/크기/값/이름/중복 mask 차단 회귀, 실제 invalid skip422 |
| A10 | PASS | 기존 실제복수 component·선택 및 현재원본loader/회귀; 임의합치기없음 |
| A11 | PASS | 실 설치A/B/C undistorted scene→원본training, hash/dimension/binary 검사 |
| A12 | PASS | 실제1 positive→자동예측. 초기사진준비 전 클릭 차단 |
| A13 | PASS | 실제Alt negative→자동예측, HUD클릭 차단 해제 |
| A14 | PASS | 브라우저5연속 점/최신revision + 설치본 B revision6·지연응답 계약 회귀 |
| A15 | PASS | 실제point/brush undo·redo·저장 및4 frontendtests |
| A16 | PASS | `v03-sam-persistent-oom.json`, `v03-prompt-failure-browser/`:실제CUDA OOM·같은 입력 재시도·이전preview hash 보존 |
| A17 | PASS | 실제eraser/undo/redo/save→학습입력, `v03-mask-recovery-final/` 재확인 후manual/hash보존 |
| A18 | PASS | 실제SAM3.1 strict checkpoint·16/20뷰 전파. 실패뷰는 실 재프롬프트; 정확도보장아님 |
| A19 | PASS | 현재보호계약 회귀·재전파에서기존manual/approved유지 |
| A20 | PASS |16뷰14skip,20뷰수정/검토/skip. invalid12개는 강제통과 없이 재추론·저장 |
| A21 | PASS | CPU-only RGB8 PLY→기본컬러Viewer, 실제download hash·GLB색상독립읽기 |
| A22 | PASS | 설치본A/B/C100회실train→원본256TSDF RGB. 별도브라우저2000/512·기존30K/1024 |
| A23 | PASS | 모든설치본 sRGB roundtrip max5.96e-8, independent GLB accessor |
| A24 | PASS | 원본PLY/GLB/RGB구간분석·exporter3·없는색상구분. 기존색상데이터보존 |
| A25 | PASS | `v03-cpu-viewer-browser/`:렌더픽셀변화로orbit/pan/zoom확인,fit/reset/4mode/원근/직교/내보내기 |
| A26 | PASS | 원본train/loss/pruning소스무변경,현재브라우저100/2000·설치본각100,기존A6000/30K이력분리 |
| A27 | PASS | 실제NVIDIA/worker CUDA device로그·COLMAP GPU관측. 다중물리GPU는NOT TESTED |
| A28 | PASS | fresh lifecycle 종료/재개/project재열기/manifest·SQLite,원본30K보존 |
| A29 | PASS |54회귀,기존real cancel/owner-death/OOM·현재persistentOOM·dead-session lockcleanup계약 |
| A30 | PASS (컨테이너 범위) | 신규Ubuntu24사용자빈환경설치·read-onlyapp·실desktop Exec. GNOME 메뉴 마우스 조작NOT TESTED |
| A31 | PASS | GPU/CPU-only0.3첫실행실진단·모델없어도결과보기·명확한추론차단 |
| A32 | PASS | UID1101/HOME새경로/공백경로,개발HOME/checkout mount없이설치·실GPU3경로 |
| A33 | BLOCKED (공개배포) |47라이브러리·정적deps·SAM/GS고지수집완료. GPL/LGPL source/relinking/결합조건·법률검토미완료 |
| A34 | PASS (현재범위) | 실제loopback만bind,Host/Origin/token/path회귀,외부CDN/업로드없음. 모든서드파티공급망보안인증주장없음 |
| A35 | PASS | 최신README·USER_GUIDE·TEST_REPORT·FUNCTIONAL_AUDIT·NOTICE |
| A36 | PASS | actual新UIDinstall/uninstall/reinstall·project/runtime보존,다른sameversion거부 |
| A37 | PASS | Python54/Frontend4/build·전체browser·설치본A/B/C GPU실행. 이전증거와이번직접실행구분 |

**공개 배포를 막는 조건:** SuiteSparse GPL/LGPL의 corresponding-source·재링크와 결합 라이선스 검토, 원본 비상업 연구 제한, 법률 전문가 검토/필요 권한 확인. 고지 복사나 설치 성공이 권한 해결을 뜻하지 않는다. `NOTICE`, `M4ML_STUDIO_LICENSES.md`에 범위와 후속 조치를 기록했다. 따라서 이 빌드를 정식 공개·상업 배포 완료로 표시하지 않는다.

**미검증/품질 한계:** 다른 물리 GPU/드라이버, Ubuntu22.04/glibc2.35, GNOME 메뉴 마우스 조작·FUSE/AppImage, 외부 처음 사용자 연구·전체보조공학인증은 NOT TESTED. 모델 전파는 가림/시점변화로 실패할 수 있고 수정이 필요하다. 실제부분표면·구멍을 포함하며 완전성/수밀성/연구벤치마크성능을 보장하지 않는다.
