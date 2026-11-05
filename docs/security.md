# 보안 현황과 계획

> 이 문서는 **지금 무엇이 막혀 있고, 무엇이 비어 있고, 무엇을 정해야 하는지**를 한곳에 적는다(#1430). 값·정책을 바꾸면 이 문서도 같이 고친다.
> 작성 시점 2026-11-06. 「확인 못 함」은 코드·설정에서 아직 확인하지 않았다는 뜻이다 — 없다는 뜻이 아니다.

## 1. 지금 있는 방어 (코드 근거)

| 영역 | 내용 | 근거 |
|---|---|---|
| 세션 | 무상태 HMAC-SHA256 서명 토큰, TTL 30일. 로그아웃·탈퇴는 `users.sessions_valid_after`로 이전 토큰을 무효화 | `docs/tech-stack.md`, `backend/auth/` |
| 쿠키 | `session`·`kakao_oauth_state`·`pending_account` 모두 HttpOnly, SameSite=Lax. 운영은 Secure 강제 | `backend/auth/router.py`, `backend/common/settings.py`(COOKIE_SECURE 가드) |
| 로그인 CSRF | 서버가 만든 `state`를 서명 쿠키에 넣고 콜백에서 대조. 콜백 링크는 한 번만 쓴다 | `docs/CHANGELOG-api.md`(로그인 CSRF 항목) |
| 운영 설정 가드 | CORS `*` 금지, 비밀값 32자 이상·기본값 금지, DB TLS(sslmode), 주소 https·호스트 일치 | `backend/common/settings.py`(#1210) |
| 요청 제한 | 검색·링크 가져오기·피드백·게스트 입장에 인메모리 슬라이딩 윈도 | `backend/common/ratelimit.py` — 프로세스 재시작 시 초기화, 인스턴스가 여럿이면 각자 센다 |
| 저장소 | secret scanning, push protection 켜짐. `develop` 브랜치 보호(필수 검사 `contracts`·`pytest`·`frontend`, 관리자 포함) | GitHub 설정 |
| 의존성 | Dependabot alerts 켜짐 | GitHub 설정 |

## 2. 알려진 빈 곳

| # | 빈 곳 | 상태 |
|---|---|---|
| 1 | 의존성 취약점 점검이 CI에 없었다 | **이 PR(#1430)에서 알림 전용으로 추가**(`.github/workflows/security-audit.yml`) |
| 2 | 보안 응답 헤더(HSTS, `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, CSP) | `deploy/Caddyfile`에는 `X-Robots-Tag`뿐이다. 카카오 로그인 리다이렉트·카카오맵 SDK에 영향이 있을 수 있어 스테이징에서 확인 후 적용 |
| 3 | 요청 제한이 닿지 않는 엔드포인트(로그인·초대 수락·일반 쓰기 등) | 전수 점검 안 함(확인 못 함). 인메모리라 다중 인스턴스에서 약하다 — 앞단(Caddy) IP 기준 제한 검토 |
| 4 | 보안 이벤트(로그인 실패·권한 거부·429 급증) 감사 로그와 알림 | 모으는 곳을 확인하지 못함 |
| 5 | GitHub Actions를 태그(`@v4`)로 쓴다 — SHA 고정이 아니다. `develop` 필수 리뷰 승인 수 미설정 | 팀 운영 방식과 걸려 있어 결정 필요 |
| 6 | 서버·비밀값 운영(SSH 접근, 보안그룹, 비밀값 로테이션, 백업 암호화) | `deploy/`는 확인했으나 인프라 설정은 확인 못 함 — 인프라 담당 확인 필요 |
| 7 | 로그에 개인정보(좌표·이메일·토큰)가 남지 않는지 | 로그 가드가 일부 있다. 전수 점검 안 함 |

## 3. 의존성 점검 결과 (2026-11-06, 로컬 실행)

CI가 같은 점검을 매주·의존성 변경 때 돈다. 아래는 이 문서를 쓴 날의 결과다.

**backend/requirements.txt (pip-audit)** — 2개 패키지 4건(같은 ID 2건씩).
- `python-dotenv==1.0.1` → 수정 버전 1.2.2 (PYSEC-2026-2270)
- `pytest==8.3.3` → 수정 버전 9.0.3 (PYSEC-2026-1845). 테스트 도구인데 운영 요구 파일에 들어 있다 — 분리 여부는 별도 판단

**frontend (npm audit)** — 17건(낮음 1·보통 8·높음 8).
- 대부분 `shadcn` CLI(`dependencies`에 있다)가 끌어오는 하위 패키지다(`@modelcontextprotocol/sdk`, `hono`, `body-parser`, `undici`, `systeminformation`, `zod` 등). 화면 번들에는 들어가지 않는 개발 도구로 보이나, 실제 번들 포함 여부는 확인 못 함
- `vite`(devDependencies) — 업데이트로 해결된다고 보고됨
- `shadcn` 자체는 수정에 주 버전 변경이 필요하다고 나온다 — 올리기 전에 영향 확인
- 대부분 `npm audit fix`로 해결 가능하다고 나오지만, **적용 전에 빌드·화면 시험이 필요하다**

**contracts, e2e** — 0건.

처리 원칙: 취약점이 나왔다고 바로 올리지 않는다. 운영 코드에 닿는지, 올려도 테스트가 통과하는지 확인한 뒤 PR 단위로 처리한다.

## 4. 다음 단계 (결정 대기)

1. **Dependabot 보안 업데이트·묶음 업데이트 켜기** — GitHub 저장소 설정(사용자). 버전 업데이트(`dependabot.yml`)는 PR이 계속 올라와 지금은 켜지 않는다
2. 보안 응답 헤더 — 스테이징에서 로그인·지도 화면 확인 뒤 적용(HSTS·`X-Content-Type-Options`·`Referrer-Policy`·`X-Frame-Options` 먼저, CSP는 카카오 허용 목록이 필요해 나중)
3. 요청 제한 전수 점검과 앞단 IP 기준 제한 — 임계값은 측정 뒤 결정(같은 학교·회사 IP 공유 사용자가 막히지 않게)
4. 이 점검을 CI **차단**으로 올릴지 — 결과가 안정된 뒤 결정(처음에는 알림만)
5. GitHub Actions SHA 고정, 필수 리뷰 승인 수 설정
6. 감사 로그와 이상 징후 알림(디스코드 연동 후보: `uptime.yml`, `notify-discord.yml`)
7. 인프라 항목(§2의 6번) — 인프라 담당 확인

## 5. 하지 않는 것

- 스테이징 주소 접근 차단(2026-11-06 결정: 하지 않는다)
