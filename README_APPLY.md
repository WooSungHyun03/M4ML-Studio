# M4ML Studio: 기존 Codex 프로젝트용 비파괴 추가 명세

이 패키지는 **실제 Ubuntu 프로젝트를 여기서 수정한 결과물이 아니라**, 그 컴퓨터에서 실행 중인 Codex가 수행할 구체적인 추가 작업 명세다.

## 설치
1. 기존 `/home/m4ml/Desktop/Object-Aware`의 파일을 변경/삭제하지 않는다.
2. 이 ZIP을 `/home/m4ml/Desktop/Object-Aware`에 압축 해제하면 신규 파일(`M4ML_STUDIO_RESUME_PROMPT.md`, `docs/M4ML_STUDIO_*.md`)만 추가된다.
3. Codex 6.1 Sol에서 `M4ML_STUDIO_RESUME_PROMPT.md`를 실행 프롬프트로 입력한다.
4. Codex가 기존 `AGENTS.md`, `CODEX_PROMPT.md`, 진행 중 코드와 문서를 확인하고, 해당 파일을 수정하며 실제 테스트해야 한다.

이미 동일한 파일명이 있을 경우 압축 해제 전 비교한다. `AGENTS.md`, 기존 설계 문서, `docs/STATUS.md`, 소스코드, 체크포인트/데이터는 ZIP에 포함하지 않아 덮어쓰지 않는다.

## 포함 문서
- `M4ML_STUDIO_RESUME_PROMPT.md`: Codex 실행용 상세 프롬프트(중단 재개/최신 사용자 요구).
- `docs/M4ML_STUDIO_PRODUCT_SPEC.md`: 입력 A/B/C·마스크·색상 메시·데이터/UI 제품 동작.
- `docs/M4ML_STUDIO_TECHNICAL_GATES.md`: PLY 컬러 원인 진단, click concurrency, COLMAP import 유효성, GPU·설치 기술 게이트.
- `docs/M4ML_STUDIO_BRAND_UX.md`: M4ML Studio 실제 로고 및 과장 없는 전문 소프트웨어 디자인.
- `docs/M4ML_STUDIO_ACCEPTANCE.md`: 수용 테스트 37개, 샘플/실 CUDA E2E 구분.
- `docs/M4ML_STUDIO_RELEASE.md`: 배포 품질, 설치·라이선스·데이터 보호·지원 범위.

## 안전하고 확실한 작업 시작

```bash
cd /home/m4ml/Desktop/Object-Aware
# 저장된 ZIP을 이곳으로 옮긴 후 실행
unzip -n M4ML_Studio_Production_Upgrade.zip
```

전체 원본 프로젝트 백업/커밋을 권장하되 학습 데이터와 모델 파일은 버전 관리에 커밋하지 않는다. 이 문서와 프롬프트를 읽은 Codex가 제품 소스코드를 실제 수정해야 한다.
