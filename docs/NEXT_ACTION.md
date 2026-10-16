# M4ML Studio0.3 — 다음 세션 재개

2026-10-16 최종 기술 검증 완료. **공개·상업 배포는 라이선스 의무/권한 검토 때문에 BLOCKED**이다. Phase0부터 다시 만들거나 이미 완료한30K 학습을 무조건 반복하지 않는다. STATUS 최신 항목과 TEST_REPORT를 먼저 읽는다.

## 현재 실행

일반 설치 앱: `~/.local/share/m4ml-studio/apps/0.3.0`.
기존 단일 GPU 런타임: `/home/m4ml/Desktop/Object-Aware/.runtime` (전역 Conda 환경 아님).
실제 데스크톱 등록: `~/.local/share/applications/m4ml-studio.desktop`.
공식 체크포인트는 기존 `models/sam3.1` 파일을 XDG 설정으로 지정했고 패키지에 복사하지 않았다.

```bash
gtk-launch m4ml-studio
```

이미 실행 중이면 기존 서버를 재사용한다. 주소: http://127.0.0.1:8765/?project=cba71418-86e9-4d0b-9e74-c3bbacf70839
기존30K 프로젝트는 legacy XDG data 경로에 그대로 있으며 전체6단계 완료/원본 PLY hash가 유지된다. 테스트 데이터를 일반 사용자 저장소에 섞지 않는다.

## 고정 산출물

- `release/M4ML-Studio-0.3.0-linux-x86_64.tar.gz`
- SHA256 `909b1137317f33e8fa47081f968318130a19d6691d73c51cefd40e5014208362`,103589769 bytes,2052 manifest 파일.
- 같은 폴더의 `.sha256`과 `M4ML-Studio-0.3.0-QA.json`이 최종 무결성/실행 판정이다.
- application source commit: `9e61c4967be67918f0b505e868c5704c40f0af97`; 앞선 구현 `fc678be`, 설치 안전성 `d306c13`. 이후 문서 커밋은 `git log -4`로 확인한다. 원격 push 없음.

## 검증 재현

```bash
.runtime/bin/python -m unittest discover -s studio/tests
npm test --prefix frontend
npm run build --prefix frontend
```

최종54 Python/4 frontend 및 native CUDA loss0.8145585656 PASS. 실제 최종 설치본 A/B/C GPU100/256와 전체 브라우저16사진 E2E도 PASS. 기존30K와 별도2000/512, 이전6000 resume는 독립 이력이다. GPU 성능/형상 품질 검증으로 smoke 결과를 과장하지 않는다.

브라우저: `scripts/ui_e2e.mjs`, `ui_mask_recovery.mjs`, `ui_prompt_failure.mjs`, `ui_viewer_regression.mjs`, `ui_product_capture.mjs`. 실제 사용 중인 프로젝트 대신 별도 STUDIO_DATA/포트에 시험한다. `PW_DIR`/`CHROME`은 로컬 설치 경로를 지정한다. OOM 시험은 별도 서버의 명시 allocator quota이며 일반 앱에는 적용하지 않는다.

## 보존된 데이터와 남은 일

- 원본 연구 코드·체크포인트·사진·모든 로그·이전 아카이브/설치본을 보존했다. SAM submodule의3개 수정은 tracked patches에서 재현되는 의도된 상태이며 reset하지 않는다.
- `evidence/`와 릴리스/런타임/모델은 Git에 넣지 않는다. supplied design mockup도 로컬 참고 자료로 보존됐으며 GPU 증거가 아니다.
- 별도 Ubuntu 테스트 컨테이너 `m4ml-studio-v03-clean-test`, `m4ml-studio-v03-cpu-test`는 종료 후 보존한다. 삭제하지 않았다. 다른 서비스/컨테이너를 중지하지 않는다.
- 다음 실제 게이트는 SuiteSparse GPL/LGPL corresponding-source·relinking·결합 라이선스, 원본 비상업 조건 및 필요한 권한/법률 검토다. NOTICE와 LICENSE 문구를 임의 변경하거나 공개/상업 승인으로 표시하지 않는다.
- 다른 GPU/드라이버·Ubuntu22.04·GNOME 메뉴 마우스 조작·외부 신규 사용자 연구는 미검증이다. 필요하면 새 검증으로 추가한다. 현재의 로컬 기술 구현을 다시 시작할 이유는 없다.
