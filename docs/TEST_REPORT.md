# M4ML Studio 0.3.0 시험 보고서

2026-10-16 복구 세션. 실제 장비: Ubuntu24.04 x86_64 / RTX4080 16GB / NVIDIA580.173.02. GPU Python은3.10/Torch2.5.1+cu118/NumPy1.24.4 하나이며 COLMAP4.2.1은 별도 ELF/CUDA12.6 runtime이다. 원본 train.py/render.py/arguments/scene/gaussian_renderer/utils/native source diff는 비어 있다.

## 이번에 직접 실행한 결과

| 분류 | 결과 / 증거 | 범위 |
|---|---|---|
| Python 회귀 | **54 PASS** `v03-final-python.log` | provider/CPUflag/migration/상태/색상/프로세스/입력/기존손실·manual보존·session복구. fixture/contract는GPU대체증거가아님 |
| Frontend | **4 PASS** `v03-final-frontend.log` | zoom/pan mapping, bounds, 최신session/frame/revision,빈legacy prompt |
| Release build | PASS `v03-final-build.log` | TypeScript/Vite. lazy Three.js chunk500KB경고 유지 |
| 전체 Browser E2E | **PASS, console0** `ui-e2e-v03-complete/result.json` | 새프로젝트16실사진upload→실GPU정합→positive/negative→5연속→zoom정확좌표→프레임전환→실전파→eraser/undo/redo/save/skip→명시100 GPU train→자동256TSDF→컬러Viewer.48161정점81624삼각형 |
| 실제20뷰 수정 경로 | 기능 완료, 브라우저종합FAIL이력보존 `ui-e2e-v03-correction/` | 시점전파실패12뷰를 실제클릭재추론/저장→2000 GPU train/512TSDF→99822정점168749삼각형. 원래JSON PASS와달리404콘솔때문에exit1. 완전PASS로세지않음 |
| invalid mask 복구 | **PASS, console0** `v03-mask-recovery-final/` | invalid예측파일요청안함·실사진유지→실모델재클릭→binary저장→다음확인후manual/hash보존 |
| 실제persistent CUDA OOM | **PASS** `v03-sam-persistent-oom.json`, `v03-sam-persistent-oom-fixed.log` | 공식SAM3.1 초기모델로드를명시.002 allocator quota로실패. 글로벌VRAM고갈아님. 이전preview SHA/입력보존·원인안내 |
| OOM UI 재시도 | **PASS, console0** `v03-prompt-failure-browser/` | 같은점/labels/session으로revision1→2재시도. quota유지이므로재실패가정상. 성공추론으로주장하지않음 |
| 실제설치본 A/B/C | **PASS** `v03-clean-installed-ABC.json` | 신규사용자설치경로에서실SAM/원본각100train/256TSDF. A45841정점76468삼각형, B49726/84364, C49751/84361. 전부실RGB/GLB오차5.96e-8 |
| 깨끗한GPU설치 | **PASS** `v03-clean-install-full.log`, `v03-clean-constrained-install-full.log`, `v03-clean-final-doctor.json` | 새HOME·새빈Pythonruntime·nativecompile·공백경로·relocatedCOLMAP ELF/실GPU연결.150실측versionconstraint재설치·pipcheck |
| 설치 lifecycle | **PASS** `v03-clean-lifecycle.json`, `v03-clean-lifecycle-console.log` | non-root UID1101, read-only app,실desktop-entry Exec,중복실행/정상종료/reopen/uninstall/reinstall/project보존 |
| CPU-only 신규설치 | **PASS** `v03-cpu-viewer.json` | Torch/GPU/checkpoint없는별도0.3사용자설치.실RGB PLY8정점12삼각형import. train422차단 |
| Viewer/테마/다운로드 | **PASS, console0** `v03-cpu-viewer-browser/` | 실제렌더픽셀차이로orbit/pan/zoom,fit/reset/4mode/원근·직교/light·dark/고급정보/1366·1920/PLY·GLB다운로드.원본PLY hash일치·GLB색독립읽기 |
| 현재전체화면 | **PASS, console0** `v03-final-screens/` | 실제완료프로젝트6단계+홈1366/1920·light/dark. mock데이터없음 |
| 이전 A/B/C 독립재검사 | **PASS** `v03-prior-A-reaudit.json`, `v03-ABC-artifact-reaudit.json` | 이전6000/1000/1000로그·scene/mask/Gaussian/PLY hash·GLB accessor재읽기. 새학습으로세지않음 |
| License inventory | 기술적고지PASS / **공개배포BLOCKED** |47ELF SHA·Ubuntu원문저작권·staticPoseLib/faiss·OIIOthird-party/CUDA12.6EULA·SAM/GS·NOTICE.소스제공/재링크/결합검토·법률권한미완료 |

최종 고정 tarball의 SHA256/manifest·설치 후 실행 점검은 번들 옆 `QA.json`과 STATUS 최신 기록에 남긴다. 패키지에 실행로그·가중치·사진·사용자프로젝트를 포함하지 않는다.

## 재현 명령

```bash
.runtime/bin/python -m unittest discover -s studio/tests
npm test --prefix frontend
npm run build --prefix frontend
# 실제구동 backend가준비된뒤,테스트전용저장소에서실행
STUDIO_UI_ITERATIONS=100 STUDIO_UI_MESH_RES=256 \
  PW_DIR=/설치된/node_modules CHROME=/실제/chrome \
  node scripts/ui_e2e.mjs http://127.0.0.1:8767 datasets/south-building-sample/images 16 evidence/ui-e2e-v03-complete
python3 scripts/package_release.py --internal-research
```

브라우저는 실제 UI/file chooser/canvas/키보드/확인대화상자로 조작한다. Network 기록은전송된좌표/revision확인용이며숨겨진API로단계를대체하지않는다.100회/256은시험용명시설정이며기본30000/1024를변경하지않는다. 중단된자체시험재개는 `STUDIO_UI_PROJECT=<시험프로젝트UUID>` 및 `STUDIO_UI_FROM=review`를사용한다. 사용자의 다른프로젝트에무단실행하지않는다.

## 실제 실패·원인·수정

- 첫원본script재실행에서2번째Alt클릭차단은해결됐으나사진decode전초기canvas bbox로좌표를측정해6,6모서리를선택했다. `ui-e2e-recovery/`. 테스트는실제픽셀준비를기다리고제품은로딩중입력을차단한다.
- Zoom기대좌표시험에서locator자동스크롤영향을배제해도Y42.8px오차재현. 원인은canvas.focus가좌표계산전에스크롤한것. preventScroll적용후실측기대/전송좌표정확일치. 실패 `ui-e2e-v03-fixed/`, `ui-e2e-v03-verified/` 보존.
- 중앙point가가림나무/작은벽영역을선택해20뷰전파13valid/7invalid,다른재선택은8valid/12invalid. 실제모델의가림·뷰간실패이며skip422차단유지. 수동재프롬프트경로로복구. 쉬운16뷰실사진별도E2E도통과. 임의멀티뷰정확도를주장하지않는다.
- 테스트clear버튼이이미빈frame에서disabled, save접근성명에Enter포함, select순번변경등으로실패해현재UI에맞게수정했다. 재전파대기는이전완료표시가아닌실제시작→완료를기다린다. 모든실패로그보존. 동시TSDF중15초create대기는60초로조정; 생성된프로젝트는보존했다.
- 알려진invalid mask가없는PNG를요청해404발생. valid플래그에따라실사진/프롬프트만표시해수정. script는console오류가있으면JSON도FAIL/exit1로일치시킨다.
- 새mask PNG decode전이전binary저장방지, 재확인시manual분류유지,0.2고정version/uninstall/DBbackup을0.3에맞게수정. 원본픽셀과과학손실변경없음.
- Persistent모델초기OOM이모호한'응답없음'으로표시됨을실재현후메모리안내/같은입력재시도추가. 현재프로세스로그offset으로지난OOM오인방지,죽은cached process의GPUflock을대체시작전에해제.
- 첫recovery-ui시험은서버startup artifact audit중접속해connection-refused. 서버준비후같은시험재실행PASS, `v03-mask-recovery.log`에실패보존.

## 이전 세션에서 확인한 증거

`e2e-0.3/result.json`은A24뷰GPU정합·24전파·manual/skip·2700중단→2500checkpoint→6000재개, B/C16뷰각1000학습/mesh를보존한다. non-gray A81.8%/B85.4%/C86.9%. 이번에파일을독립재검사했다. `gpu-colmap-128/verification.json`192초와`cpu-colmap-128/verification.json`554초/128등록은이전실측이다.189초별도slim측정과혼합하지않았다. 검증된CUDA빌드를다시빌드하지않았다. 이전30K/1024,실cancel/ownerdeath/원본trainOOM·CPUviewer이력은STATUS원문에남긴다.

## 깨끗한 설치 범위와 미검증

기존Docker이미지태그0.2.0은Ubuntu24.04시스템준비/Miniforge24.11.3-2만재사용한다. 새container·UID1101·새HOME·빈Python환경에0.3을설치했고개발checkout/HOME을mount하지않았다. release·officialcheckpoint·사진fixture만read-onlymount했다. 시스템준비패키지는 python3/git/curl/ca-certificates/build-essential/gcc-11/g++-11/colmap/libgl1/libglib2.0-0/libegl1/libgomp1/xdg-utils/desktop-file-utils/bzip2였다. 시스템COLMAP이있어도내장origin/hash/실행을검사했다. 실측150Python버전제약은wheel해시잠금이아니다.

동일물리RTX4080의DockerGPUpassthrough이다. GNOME메뉴마우스클릭·다른물리GPU/driver·Ubuntu22.04/glibc2.35·FUSE/AppImage·외부신규사용자연구·전체스크린리더인증은NOT TESTED이다. source/runtime라이선스법률검토와공개재배포는BLOCKED이다. 수밀·완전형상·연구벤치마크품질보장없음.

## 최종 고정 압축본의 직접 재검증 (2026-10-16)

최종 SHA256은 `909b1137317f33e8fa47081f968318130a19d6691d73c51cefd40e5014208362`다.103589769 bytes/2052 파일의 모든 manifest hash·실행 권한·데이터/가중치 제외를 다시 검사했다. 공식 SAM Python 모듈 경로의 `datasets/`를 사용자 데이터로 오인한 최초 감사 규칙은 archive 최상단 데이터 경로 검사로 바로잡았으며, 실제 사용자 데이터가 발견된 것은 아니다. SHA 검사 CWD 실수도 올바른 release 폴더에서 재실행해 해결했다. 원래 실패 이력은 `v03-final-archive-audit-first-failure.log`에 남겼다.

동일 압축본을 새 Ubuntu 사용자 환경에 다시 설치하고 실제 A/B/C 각100회 GPU 학습·256 TSDF까지 완료했다. `v03-clean-exact-final-ABC.json`: A40141정점/66102삼각형, B49668/84252, C49738/84381. 모든 RGB/GLB 오차5.96e-8. A의 특징점 추출과 매칭에서 실제 COLMAP GPU 사용도 관측했다. 이전 candidate 수치와 혼합하지 않는다.

**동일 최종 설치본에 대한 전체 브라우저 E2E도 PASS/console0** (`ui-e2e-v03-exact-release/`): 새16사진 입력부터 클릭/연속/zoom/전환/전파/실제 수정·검토/100학습/256mesh/Viewer까지 수행했다. 나머지 source/storage 변경을 포함한 post-install Python54 PASS와4 frontend PASS를 구분해 기록했다.

현재 사용자에도 정식 설치 경로/실제 `.desktop`을 등록하고 **gtk-launch를 통한 실제 데스크톱 항목 활성화**에 성공했다. 메뉴를 마우스로 누른 시험은 아니다. 일반 앱은8765이며 기존30K 프로젝트가 모든 단계 완료로 복원됐다. 원본 PLY 다운로드 SHA908958e0...은 유지되고, 수정된 GLB/기본 컬러 뷰어와 실제 조작/다운로드 시험은 console0이다. 원본 native CUDA forward/backward/optimizer는 같은0.8145585656으로 PASS했다. 모델 경로 설정은 사용자 XDG에만 저장되며 번들에 개발 PC 경로/가중치를 넣지 않았다.

최종 상세 QA는 아카이브 옆 `M4ML-Studio-0.3.0-QA.json`이다. 이 문서의 최종 QA 추가 기록은 고정 아카이브 이후 저장되는 감사 기록이며 아카이브 자체를 다시 변경하지 않는다. 일반 앱만 남기고 테스트 서버/컨테이너는 안전하게 종료하되 데이터·런타임은 보존한다. 공개 배포 BLOCKED 판정은 변하지 않는다.

## 실시간 렌더(Gaussian 뷰어) 통합 검증 (2026-10-16, 0.5.0)

실제 장비: Ubuntu 24.04, RTX 4080 16GB, 드라이버 580.173.02, X11. 상세는 `docs/GAUSSIAN_VIEWER_INTEGRATION.md`.

**실제 GPU 증거** (합성 데이터 아님):
- **원본 대비 동일성.** 원본 `view.py`와 M4ML 렌더러 프로세스에 같은 카메라를 넣었습니다. 모델은 30K 학습 결과(437,838 Gaussian)입니다. RGB·Alpha·Normal·Depth·Edge·Curvature 모두 픽셀 최대 차이 0이었습니다.
- **SIBR 소스 빌드와 연결.** Gaussian-Splatting-Monitor `2b6190c`를 Ubuntu 24.04용 패치와 함께 소스에서 빌드했습니다. 이 SIBR는 원본 `view.py`와 M4ML 렌더러 양쪽에 연결되어 실제 Gaussian 프레임을 표시했습니다. 앱의 외부 뷰어 버튼도 같은 렌더러에 연결된 뒤 세션과 함께 종료되었습니다.
- **브라우저 E2E** `scripts/ui_live_render_e2e.mjs`: 21/21 PASS, 콘솔 오류 0. 프레임 해시로 다음을 확인했습니다.
  - 회전·확대·이동·모드 5종·크기 변경·전체 화면·스크린샷이 실제로 화면을 바꿈
  - 메시 전환 시 렌더러 종료, 다시 열기
  - 다른 프로젝트(이번 세션에서 실제 학습한 3,000회 모델, 92,004 Gaussian) 전환
- **실제 데스크톱 창 QA** `scripts/desktop_live_render_qa.mjs`: 9/9 PASS.
  - 입력은 M4ML 페이지에만 DevTools로 전달했습니다(§8 참고).
  - 지속 드래그 62 fps, 응답 16 ms.
  - 패널을 숨겨 뷰포트 크기가 바뀌면 새 비율로 다시 렌더합니다.
- **GPU 정책.** 다음 네 가지를 확인했습니다.
  - 학습을 시작하면 렌더러가 해제됨
  - GPU 작업 중 실시간 렌더 시작은 409로 거부됨
  - 다른 앱 인스턴스의 객체 선택 세션이 GPU를 잡고 있으면 "GPU 사용 중"으로 표시됨
  - 백엔드를 SIGKILL하면 147 ms 안에 렌더러가 종료되고, 창을 닫으면 모든 프로세스가 종료되어 VRAM이 반환됨
- **회귀.** 이번 세션에서 실제 3,000회 학습(58초)과 메시 생성(6초)을 실행했고, PLY/GLB가 HTTP 200으로 내보내졌습니다. 메시 뷰어는 편집기 E2E 28/28 PASS입니다.
- **배포.** 0.5.0 압축본을 임시 XDG 위치에 설치했습니다(`--no-setup`, 기존 런타임 재사용). 폴더 열기 → 렌더러가 설치 경로에서 실행되었고, 개발본과 프레임이 동일했습니다(최대 차이 0).

**자동 테스트:** Python 76/76(실시간 렌더 10개 포함: 프로토콜·카메라 변환·모델 검증·API 계약), 프론트엔드 4/4, TypeScript·빌드 통과.

**미검증:**
- Wayland 세션, 다른 GPU/드라이버, 다른 Ubuntu 버전
- 0.5.0의 깨끗한 컨테이너 전체 설치(`setup.sh`)
- 시스템 라이브러리가 없는 환경에서 SIBR 외부 뷰어 동작. 내부 뷰포트는 SIBR 없이 동작하도록 설계했지만, 그 상태 자체는 별도로 시험하지 않았습니다.

## Quality harness verification (2026-10-16, actual0.5 source)

-87 Python PASS (baseline76), frontend4 and TS/Vite PASS; frontend source unchanged.
- Real CPU children/locks/sockets reproduce and verify failed renderer-start cleanup; actual RTX4080 failure-after-load/retry and five original modes pass.
- Direct malformed renderer packets rejected before CUDA; valid five-mode PNGs byte-identical to before bounds. Real browser live21/editor28 PASS/console0.
- Actual Qt foreign main-frame page previously received token/native bridge (booleans only); exact-origin navigation/bootstrap fix verified by native5 security and9 live-GPU checks.
- Actual new Qt editor100-step original training→automatic TSDF256→color mesh/viewer PASS on copied16-view+mask dataset.2816 Gaussians, loss0.77123,49706 vertices/84310 triangles; independent PLY/GLB error5.96e-08. Final test resumes only the viewer portion of a retained completed run. Earlier harness failures and Qt DevTools dialog acknowledgement discrepancy remain in E-005. This smoke proves connectivity, not final geometry quality or fresh camera/SAM inference.
- Own processes/ports cleaned, normal installed8765 preserved. Clean0.5 install/native file dialogs/DnD/Wayland/otherGPU remain UNVERIFIED; public/commercial HOLD unchanged. Commands/logs/limits: `quality-harness/state/EVIDENCE.md` (E-001–E-006).

## Current0.5 Quality Harness — 2026-10-16

Detailed scoped results: QUALITY_HARNESS_REPORT.md; actualcommands E-008–E-015 in quality-harness/state/EVIDENCE.md.94Python20.086s/5frontend/build/editor28/Gaussianbrowser23/importtransitions2/nativeI/O6/CPUfault3/100photo-theme7 PASS. NewfullA30000/TSDF1024 plusinstalledB/C1000/TSDF256 are realGPUruns, separately labelled. Independent378433-color-vertex PLY/GLB error5.96e-08; loss992finite/last0.19404. Actualwrong-PID/cancel500/React310/Qtmissinglibrary FAIL evidence retained beforefixes. Fullsourcebundle2builds bytesidentical SHA70613bb5ce282efcef0935b54e0eba98ed8edcd07374474c62abc8ba9fd55870; finalfreeze QA recorded beside archive. No formal external novice/otherGPU/Wayland/overnightclaim. Public/commercial HOLD.

Finaladditionalboundary: cf31a76 cancel-before-PID realSQLite/CPUworker regression,95PythonPASS30.154s. Privateupdateproject342files/Python2preserved; recompilednative2hasheschanged, original64GaussianCUDAfixtureall4lossvaluesexactmatchbaseline. See continuous/cancel-start-window-{before,verified}.log, final-95-python.log, update-preservation-classified.json, native-numerical-regression.json.
