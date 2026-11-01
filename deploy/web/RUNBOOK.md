# M4ML Studio Web — 운영 절차 (스테이징)

모든 명령은 서버에서 SSH로. 관리 도구는 HTTP로 열려 있지 않다.

```bash
ADMIN="sudo -u m4ml-web env $(cat /etc/m4ml-web/gateway.env | xargs) /srv/m4ml-web/runtime/bin/python -m studio_web.admin"
$ADMIN status            # 세션·슬롯·대기실·GPU 소유자/대기·점검 여부·디스크
$ADMIN audit 50          # 최근 감사 기록 (비밀값 없음)
```

## 연구(점검) 모드 — 데스크톱에서 GPU를 쓰기 전

1. `$ADMIN maintenance on` → 새 GPU 작업 접수·대기 작업 시작 중단(진행 중 작업은 계속).
2. `$ADMIN status`의 `gpu_owner`가 `null`이 될 때까지 대기(학습은 최대 60분 상한).
3. 연구 작업. 끝나면 `$ADMIN maintenance off`.

## 업그레이드

1. 점검 모드 → GPU 소유자 없음 확인.
2. `$ADMIN backup /srv/m4ml-web/data/backups/pre-upgrade-<commit>.sqlite` (integrity true 확인).
3. 새 커밋으로 `sudo deploy/web/scripts/install.sh --apply` (앱 폴더 교체), `systemctl restart m4ml-web-gateway` — 서비스 정지는 세션 백엔드와 실행 중 작업도 멈춘다.
4. `/api/web/ready`, 웹 E2E(`web-harness/scripts/web_e2e.mjs`) 확인 → 점검 모드 해제.

## 되돌리기

- 이전 커밋으로 다시 설치하면 된다. **새 버전이 DB 스키마를 올린 경우 옛 코드는 시작을 거부한다**(시험됨) → 2단계의 `pre-upgrade` 백업을 `/srv/m4ml-web/data/gateway.sqlite`로 복원한 뒤 시작.
- 세션 데이터(사진·결과)는 백업하지 않는다(7일 임시 데이터).

## 장애

| 증상 | 조치 |
|---|---|
| GPU가 계속 잡혀 있음 | `$ADMIN status`로 소유 세션 확인 → 필요하면 `$ADMIN delete-session <id>` (그 세션의 모든 작업 중지·삭제). Gateway는 실제 잠금이 풀리고 GPU 프로세스가 없어야만 임대를 넘긴다 |
| 디스크 부족 | 서버 여유 100 GB 미만이면 새 업로드·작업이 자동 거부됨. 만료 세션은 10분마다 자동 삭제 |
| 봇·요청 폭주 | 429가 자동 응답. 계속되면 Cloudflare 방화벽 규칙 또는 터널 정지(`systemctl stop cloudflared`) |
| Gateway 재시작 후 | 진행 중이던 GPU 임대는 DB에 남고 자동 재실행하지 않는다. 감시 루프가 실제 정리를 확인한 뒤 다음 작업을 시작한다 |

## 백업

`m4ml-web-backup.timer`(매일 04:30) → `deploy/web/scripts/backup.sh` → `/srv/m4ml-web/data/backups/gateway-*.sqlite`, 7일 보관. 내용: 세션 ID·시각·상태, 쿠키 비밀값의 **해시만**, 슬롯·대기·GPU 임대 기록, 감사 이벤트 이름. 사진·프로젝트·토큰 원문은 없다. 개인정보 처리방침의 보존 기간과 맞출 것(T24).
