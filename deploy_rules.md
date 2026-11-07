# 배포 절차

코드를 올리는 것만으로 끝나지 않는 단계를 적는다. 데이터 적재, 재계산, 예약 실행, 환경 변수처럼 코드 밖에서 맞춰야 하는 것이다. 이 단계가 문서에 없으면 새 코드가 옛 데이터 위에서 돈다(멘토 리뷰 #680: 옛 규칙으로 계산된 `can_recommend`가 남아 정예가 아닌 13만여 곳이 추천 후보였다, #743).

## 이 문서를 고치는 규칙

- 코드 밖 단계를 새로 만들거나 바꾸는 PR은 이 문서를 같은 PR에서 고친다. 적재 명령, 재계산, 예약 실행, 새 환경 변수가 모두 해당한다.
- 같은 값을 두 곳에 저장해서 재계산 단계가 생기면, 먼저 저장한 칸을 없애고 원본을 바로 읽을 수 있는지 본다(#743). 재계산 단계는 그래도 필요할 때만 둔다.
- 확인되지 않은 것은 "미정"이나 "아직 없음"으로 적고 이슈 번호를 단다.

## 배포 구성 (2026-10-28 결정, #168)

멘토 리뷰(「남은 2주」, 「배포」 절)를 받아 정했다. 서버는 부트캠프가 준 AWS 서버 1대(t3.medium, 2 vCPU, 4GB, 디스크 50GB, Ubuntu 24.04, 서울 리전, 2026-11-20까지)다. 사용 규칙은 운영진 안내를 따른다 — 접속은 SSM으로만 하고 22번 포트를 열지 않는다, GitHub Actions는 OIDC 역할(`ktc-github-deploy`)로 붙는다.

| 결정 | 선택 | 이유 | 다시 볼 조건 |
|---|---|---|---|
| 배치 | 서버 1대에 Docker Compose(`deploy/compose.yml`). 맨 앞의 Caddy가 HTTPS(Let's Encrypt 자동)를 맡는다 | 서버가 1대뿐이다. 인증서 발급과 갱신이 자동이다 | 서버가 늘 때 |
| 주소 | 운영 `ktc-pingopingo.duckdns.org`, 스테이징 `staging.ktc-pingopingo.duckdns.org`(DuckDNS 무료, 하위 이름은 자동으로 같은 IP). 서버에 고정 IP(Elastic IP 3.38.14.223)를 붙였다 | 소셜 로그인은 IP 주소를 redirect로 받지 않는다. 고정 IP라 서버를 껐다 켜도 주소가 산다. 처음 등록하려던 `pingopingo`는 다른 계정이 이미 쓰고 있어 `ktc-pingopingo`로 바꿨다(2026-10-28) | 이름을 바꿀 때 |
| 화면 캐시 | 빌드 파일(`/assets/*`, 이름에 해시)은 1년 캐시, 화면(index.html)은 **어느 주소로 받든** `no-cache`, `/assets`에 없는 파일은 404(`frontend/deploy/Caddyfile`) | 화면 주소(`/maps/...`)로 받는 index.html에 캐시 헤더가 없거나, 없는 빌드 파일을 index.html로 대신 주면 배포 직후 깊은 주소에서 새로고침한 사람이 빈 화면을 본다(멘토 리뷰). 배포 뒤 `curl -I <주소>/maps/x`가 `no-cache`, `curl -I <주소>/assets/없는파일.js`가 404인지 본다 | 화면을 코드 분할(lazy)할 때 — 열려 있던 탭이 옛 조각을 못 받으면 새로고침하게 한다 |
| 한 주소로 서빙 | 환경마다 `/api/*`는 API(앞의 `/api`를 떼고 넘긴다), 나머지는 화면 정적 파일. 화면은 `VITE_API_BASE_URL=/api`로 빌드한다. API는 `UVICORN_ROOT_PATH=/api`(`deploy/compose.yml`)로 자기 공개 경로를 안다(`/docs`, 접근 로그) | 세션 쿠키가 `SameSite=lax`라 화면과 API가 같은 사이트여야 로그인이 된다. CORS도 필요 없다. 백엔드 경로는 그대로다 | — |
| 환경 | 운영과 스테이징을 같은 서버에서 나눈다(컨테이너, DB 이름, 비밀값이 다르다) | 멘토 「환경 분리」. 서버가 1대다 | 서버를 더 받을 때 |
| DB | RDS(PostgreSQL 17.11, PostGIS 3.5.6, 2026-10-30 승인) 한 대에 DB `pingo_prod`, `pingo_staging`. 앱은 환경마다 전용 계정(`pingo_prod_app`, `pingo_staging_app`)으로 SSL(`sslmode=require`)로 붙는다. 옮기기 전까지는 서버 안 PostgreSQL 컨테이너(`compose.db.yml`)다. 옮기는 법은 아래 「RDS로 옮기기」(#873) | 자동 백업 7일, 삭제 방지, 팀 EC2에서만 접속. 마스터 비밀번호는 Secrets Manager가 30일마다 바꾸므로 앱은 마스터를 쓰지 않는다. 앱 계정은 자기 DB만 열어 환경이 나뉜다 | 2026-11-20(AWS 종료) |
| 프로세스 | 환경마다 API 프로세스 1개(uvicorn 워커 1) | 메모리 요청 상한, 서버 시작 시 정리, 관찰 lease가 이 전제에서 안전하다. 4GB에 두 환경이 들어간다 | 응답이 느려지거나 워커를 늘릴 때. 그 전에 아래 「타협」을 고친다 |
| 이미지 | GitHub Actions가 API, 화면 이미지를 만들어 팀 계정 ECR(`pingo-api`, `pingo-web`, 최근 40개 보관)에 올린다(`.github/workflows/images.yml`). 태그는 `sha-<7자리>`, 브랜치 이름, `v0.x.y` | 빌드와 배포를 나눈다(멘토). 서버는 자기 역할로 ECR에서 받는다(저장한 비밀 없음) | — |
| 배포 | `.github/workflows/deploy.yml`이 OIDC 역할로 SSM 명령을 보내 서버의 `deploy/deploy.sh <환경> <태그>`를 돌린다. develop은 이미지가 만들어지면 스테이징에 자동, 운영은 사람이 v 태그를 골라 수동 | 22번 포트와 서버 키가 없다. 운영은 태그를 골라 올린다(멘토) | — |
| 확인 | 스테이징에서 QA 하네스(`qa/harness/run_api_cases.py --base-url`)로 핵심 흐름을 돈다. 통과한 `main` 커밋에만 태그를 단다 | 멘토 「배포된 주소의 핵심 흐름 테스트, 통과한 커밋에만 태그」 | — |
| 환경 맞추기 | 운영, CI, 로컬, 배포 도구가 같은 Python(3.12)과 PostgreSQL/PostGIS(17 / 3.5)를 쓴다. Python은 `backend/.python-version`이 정본이고 CI가 읽는다. 이미지, CI, 로컬, 배포 스크립트의 버전과 아래 DB 줄의 운영 버전은 `backend/integration/test_env_parity.py`가 대조한다(#916) | CI는 운영에서 돌 것을 미리 확인하는 곳이라 환경이 다르면 운영을 대신하지 못한다(멘토). 처음에는 CI만 3.10, PostGIS 16이었다 | 버전을 올릴 때 — 한쪽만 올리면 테스트가 실패한다 |
| 비밀 | 서버의 `deploy/env/*.env`(권한 600). 세션 비밀, DB 비밀번호, QA 비밀은 서버에서 만들었고 외부 키(카카오, 모델 제공자 OpenAI)만 옮겼다. 저장소, 이미지, 채팅에 남기지 않는다. 값마다 새면 열리는 범위와 바꾸는 법은 아래 「비밀이 새면」 | 서버 1대에 가장 단순하다. 보관함으로 옮겨도 서버가 값을 읽어야 해서 침입당한 서버에서 새는 범위는 비슷하다(멘토) | 사람이나 서버가 늘 때 보관함과 접근 기록 |
| 주기 작업 | 서버 cron(`deploy/crontab`). 두 번 돌아도 안전한 작업만 둔다 | 멘토 「주기 작업은 바깥에서 부르되 두 번 돌아도 안전하게」 | — |

### 타협과 다시 볼 조건

멘토: 이유가 빠진 타협은 나중에 원래 그런 구조로 읽힌다. 프로세스나 서버를 늘리기 전에 아래를 먼저 고친다.

| 타협 | 왜 지금은 괜찮나 | 다시 볼 때 |
|---|---|---|
| 요청 상한 5곳(`common.ratelimit`)이 메모리에서 센다 | 환경마다 프로세스가 하나다. 배포로 다시 뜨면 셈이 처음부터다 | 워커나 서버를 늘리기 전에 같은 모양(`SlidingWindowLimiter`)으로 Postgres에 옮긴다 |
| AI 코스 계산이 응답 뒤 `BackgroundTasks`로 돈다 | 서버(VM)는 요청이 끝나도 CPU를 준다. 배포로 다시 뜨면 그 run은 시작 정리(5분 넘은 것)나 조회(15분 넘은 것)가 끝낸다 | 작업 큐로 옮길 때 |
| DB가 같은 서버에 있고 덤프도 같은 디스크에 있다 | 시연까지의 데이터다 | RDS로 옮기면 풀린다(#873, RDS 자동 백업). 옮긴 뒤에도 `backup.sh` 덤프는 서버 디스크에 쌓인다 |
| 운영과 스테이징이 RDS 한 대를 나눠 쓴다 | DB와 계정이 나뉘어 서로 열지 못한다. 부하가 작다 | 스테이징 부하(측정, QA)가 운영 응답을 늦추면 |

### 비밀이 새면 (멘토 리뷰, 2026-10-30)

보관 장소를 바꿔도(파라미터 스토어 등) 서버가 값을 읽어야 하므로, 침입당한 서버에서 새는 범위는 비슷하다(멘토). 그래서 먼저 값마다 새면 어디까지 열리는지와 그때 무엇을 바꾸는지를 적는다. 교체 절차는 아직 리허설하지 않았다.

| 값 | 있는 곳 | 새면 열리는 것 | 바꾸는 법 | 바꾸면 생기는 일 |
|---|---|---|---|---|
| `SESSION_SECRET` | `env/<환경>.env`, 환경마다 다르다 | 그 환경의 아무 사용자로 세션 쿠키를 만들 수 있다(세션 토큰과 카카오 로그인 state를 서명한다). 다른 환경에는 통하지 않는다 | 새 무작위 값으로 바꾸고 그 환경 API를 다시 올린다(`docker compose up -d --no-deps --force-recreate api-<환경>`) | 그 환경의 모든 사용자가 로그아웃된다. 데이터는 그대로다 |
| DB 앱 계정 비밀번호(`DATABASE_URL`) | `env/<환경>.env`, `pingo_prod_app`과 `pingo_staging_app`이 따로다(#873) | 그 환경 DB 전부(사유 글, 구성원). 다른 환경 DB에는 접속이 거절된다. RDS는 팀 EC2에서만 붙으므로 서버 밖에서는 이 값만으로 못 들어온다 | 마스터로 `ALTER ROLE pingo_<환경>_app PASSWORD '…'` → `env/<환경>.env`의 `DATABASE_URL` 고치기 → API 다시 올리기 | 다시 올리는 몇 초 동안 그 환경이 열리지 않는다 |
| RDS 마스터(`pingo_admin`) | Secrets Manager. 서버에 저장하지 않는다 | 두 환경 DB 전부, 계정 만들기와 지우기 | Secrets Manager가 30일마다 바꾼다. 급하면 콘솔에서 즉시 교체 | 앱은 마스터를 쓰지 않아 영향이 없다 |
| 카카오 `KAKAO_CLIENT_SECRET`, `KAKAO_REST_API_KEY` | `env/<환경>.env` | 우리 앱 이름으로 로그인 코드 교환, 로컬 API 호출(호출 한도를 쓴다). 두 환경이 같은 카카오 앱이면(「서버 처음 준비」 8번) 한쪽에서 새도 둘 다다 — 같은 앱인지 확인 필요 | 카카오 Developers에서 다시 발급 → 두 환경 env 고치기 → 다시 올리기 | 그 사이 로그인과 장소 검색이 실패한다 |
| 모델 제공자 `ELICE_ML_API_KEY`(2026-11-02부터 OpenAI 프로젝트 키, 이름만 ELICE로 남았다, #1120) | `env/<환경>.env`. 환경마다 OpenAI 프로젝트와 키가 따로다 | 팀 비용으로 모델 호출(그 프로젝트의 월 예산 한도까지 쓴다). 사유 글이 모델로 간다 | OpenAI에서 새 키 발급 → env 고치기 → 다시 올리기. 순서는 아래 「모델 제공자 키 바꾸기」. 옛 키는 OpenAI에서 지운다 | 그 사이 추천의 사유 구조화와 AI 코스가 실패한다 |
| `QA_LOGIN_SECRET` | `env/staging.env`만. 운영에 있으면 서버가 뜨지 않는다(#789) | 스테이징에 사용자를 만들 수 있다. 운영에는 경로가 없다 | 새 값으로 바꾸고 스테이징 API 다시 올리기 | 없음(하네스는 서버 안에서 같은 값을 읽는다) |
| DuckDNS 토큰 | `/srv/pingo/secrets/duckdns_token` | 주소가 가리키는 IP를 바꿔 사용자를 다른 서버로 보낼 수 있다 | DuckDNS에서 토큰 재발급 | 없음(고정 IP라 갱신 작업을 꺼 두었다) |
| 옛 서버 안 DB 비밀번호 | `env/db.env`, `env/<환경>.env.before-rds` | 멈춘 컨테이너 DB(되돌리기용 볼륨). 외부 포트가 없다 | 11/20에 볼륨과 함께 없앤다 | 없음 |

키가 아닌 신원으로 붙는 것: GitHub Actions는 OIDC 역할(`ktc-github-deploy`)로 저장한 키 없이 붙는다. 대신 저장소에 쓸 수 있는 사람은 워크플로로 서버에 명령을 보낼 수 있다(그 권한이 곧 서버 권한이다). 서버는 인스턴스 역할로 ECR에서 이미지를 받는다. 이 자격증명은 짧게 살지만, 침입자가 서버 안에 있는 동안은 같은 권한으로 쓸 수 있다.

값이 아닌데 새면 큰 것: `/srv/pingo/backups/*.dump`(운영 DB 전체 덤프, 14일 보관, 암호화 안 됨)는 DB 비밀번호보다 넓다 — 데이터 자체다.

**서버가 통째로 새면**(env 파일, 덤프, 인스턴스 역할이 한꺼번에): 1) 보안 그룹에서 80과 443을 닫아 격리한다 2) 덤프가 있었으니 데이터가 나갔다고 보고 운영진에게 알린다 3) DB 앱 계정 비밀번호 → `SESSION_SECRET` → 카카오, 모델 제공자(OpenAI) 키 순서로 바꾼다(앞의 둘은 우리가 바로 바꿀 수 있고, 데이터와 사용자 사칭을 막는다).

다시 볼 때: 사람이나 서버가 늘 때(보관함과 접근 기록), 위 교체를 한 번 리허설할 때(바꾸는 법 칸이 실제로 맞는지).

## 서버 처음 준비

한 번만 한다. 2026-10-28에 했다.

1. 이 PC에 AWS CLI와 Session Manager 플러그인을 설치하고 SSO 프로필을 만든다(운영진 안내). 콘솔에서는 EC2 → 연결 → Session Manager.
2. 서버에 고정 IP를 붙이고 보안 그룹은 80과 443만 연다(22번은 열지 않는다). DuckDNS의 IP를 고정 IP로 맞춘다.
3. ECR 저장소 `pingo-api`, `pingo-web`을 만든다.
4. `sudo bash deploy/bootstrap.sh ubuntu <계정ID>.dkr.ecr.ap-northeast-2.amazonaws.com` — Docker, compose, ECR 도우미, cron, 서울 시간대, 스왑 2GB, `/srv/pingo` 폴더.
5. `/srv/pingo/deploy`에 `deploy/` 파일을 놓고(이후로는 배포 때 `sync.sh`가 맞춘다) `.env`(`.env.example` 참고)와 `env/prod.env`, `env/staging.env`, `env/db.env`(견본 `env/*.example`)를 만든다.
6. `docker compose up -d db` → 환경마다 마이그레이션 → 장소 적재(아래 「장소 데이터 적재」, 서버에서는 `deploy/load-places.sh <환경> /srv/pingo/data/places`) → `deploy.sh`로 앱을 올린다.
7. `crontab /srv/pingo/deploy/crontab`.
8. 카카오 Developers에 두 주소의 Redirect URI(`https://<주소>/api/auth/kakao/callback`)와 Web 사이트 도메인을 등록한다.

## RDS로 옮기기 (#873)

한 번만 한다. 스테이징을 먼저 옮기고 확인한 뒤 운영을 옮긴다. 운영은 옮기는 동안(덤프, 복원, 행 수 대조) 몇 분 열리지 않으니 사용자가 없는 시간에 한다.

1. **첫 설정(사람이 한 번)**: 콘솔 EC2 → 연결 → Session Manager로 서버에 들어가 `cd /srv/pingo/deploy`. `.env`에 `RDS_HOST=<엔드포인트>`를 적고 `./rds-setup.sh`. 마스터(`pingo_admin`) 비밀번호를 물으면 Secrets Manager의 값을 붙여 넣는다(화면에 안 보인다). 스크립트가 `rds/setup.sql`로 환경별 앱 계정, DB `pingo_staging`, 확장(`postgis`, `pg_trgm`)을 만들고, 출력 끝에 두 DB의 `postgis_full_version()`을 보인다. 앱 계정 비밀번호는 스크립트가 만들어 `env/<환경>.env`의 `RDS_DATABASE_URL`에만 적는다. 마스터 비밀번호는 저장하지 않는다.
2. **스테이징 옮기기**: Actions `move-to-rds`를 `staging`, `move`로 돌린다. API 정지 → 덤프(`backup.sh`) → RDS에 복원(확장과 `spatial_ref_sys`는 빼고, 소유자는 앱 계정) → 표마다 행 수 대조 → `DATABASE_URL` 교체(옛 파일은 `env/staging.env.before-rds`) → 재시작 → 건강 확인. 실패하면 `DATABASE_URL`을 바꾸지 않은 채 API를 다시 올린다.
3. **확인**: Actions `staging-check`를 돌린다.
4. **운영 옮기기**: `move-to-rds`를 `prod`, `move`, confirm에 `prod move`로 돌린다. 이어서 운영 주소에서 로그인과 지도를 한 번 열어 본다.
5. **마무리**: 두 환경이 모두 RDS면 `move-to-rds`를 `finish`(confirm `finish`)로 돌린다. 서버 안 DB 컨테이너를 멈추고 `.env`의 `COMPOSE_FILE`에서 `compose.db.yml`을 뺀다. 볼륨(`pgdata`)은 지우지 않는다.

- **되돌리기**: `move-to-rds`를 그 환경, `rollback`으로 돌린다. 서버 안 DB(마무리로 멈췄으면 다시 켠다)와 옮기기 전 `DATABASE_URL`로 돌아간다. 옮긴 뒤 RDS에 쓴 데이터는 따라오지 않는다.
- **실패했을 때**: 복원 중 실패면 단일 트랜잭션이라 RDS는 비어 있어 그대로 다시 돌리면 된다. 복원 뒤 행 수 대조에서 실패했으면 RDS에 테이블이 남아 다음 move가 거절한다 — 그 환경의 앱 계정으로 `DROP OWNED BY pingo_<환경>_app;`(확장은 마스터 것이라 남는다)을 하고 다시 돌린다.
- 첫 설정이 중간에 실패하면(계정은 만들었는데 DB에서 멈춤 등) `setup.sql`을 그대로 다시 돌릴 수 없다. 만들어진 것을 마스터로 확인해 지우고 다시 돌린다.
- 로컬 리허설(2026-10-30, `pingo_eval` 크기 그대로: 장소 199,211곳, 라벨 약 191만 건): 슈퍼유저가 아닌 마스터 역할로 `setup.sql`의 계정·소유자·접속 권한 단계 통과(postgis 생성만 RDS의 `rds_superuser` 몫), 앱 계정으로 복원 22초, 표 33개 행 수 일치, 앱 계정으로 PostGIS 거리 질의·pg_trgm 유사도·`alembic upgrade head` 통과, 운영 계정은 스테이징 DB에 접속 거절.
- 옮긴 뒤 `deploy.sh`의 마이그레이션은 앱 계정으로 돈다. 새 확장이 필요한 마이그레이션은 마스터로 확장을 먼저 만든다(앱 계정은 만들 수 없다).

### 기록 (2026-10-30)

- 첫 설정(`rds-setup.sh`) 완료. 스테이징 19:10에 옮김(표 33개 일치, 그 뒤 staging-check PASS 71·FAIL 0, INFO와 SKIP은 옮기기 전과 같음). 운영 19:20에 옮김(표 32개 일치 — 운영은 0043 전 버전이라 하나 적다, 열리지 않은 시간 약 36초).
- 스테이징 이전은 성공했지만 마지막 기록 줄의 버그로 실패 표시가 났다(#875에서 고침).
- **운영 배포 예외**: 옮긴 뒤 운영 로그인이 안 됐다. RDS 문제가 아니라 운영 이미지가 #819(카카오 state 쿠키 경로) 수정 전 코드라, 쿠키가 `/auth/kakao`에 붙어 `/api/auth/kakao/callback`으로 돌아올 때 브라우저가 보내지 않았다(옮기기 전부터 같은 상태). `deploy` 워크플로는 운영에 `v` 태그만 받아서, Session Manager에서 `./deploy.sh prod sha-17dd07d`(develop, 스테이징과 같은 이미지)로 직접 올렸다. RDS 앱 계정으로 백업, 마이그레이션(0043)까지 통과했고 로그인과 지도 열기를 확인했다. 다음 정식 릴리스(develop → main → `v` 태그)부터 규칙대로 돌아간다.
- `finish`(19:33) 뒤 서버의 모든 `docker compose` 명령이 `depends on undefined service "db"`로 실패했다. `compose.yml`의 API가 `depends_on: db (required: false)`를 갖고 있었는데, Compose v5는 정의되지 않은 서비스는 required가 false여도 거절한다. 돌던 컨테이너는 영향이 없었다. DB 의존을 `compose.db.yml`로 옮겨 고쳤다(#877). 머지하면 스테이징 배포의 `sync.sh`가 서버 파일을 맞춘다.

### AWS가 끝나기 전에(2026-11-20)

서버와 RDS가 함께 끝난다. 그 전에 운영 DB 덤프(`backup.sh prod`)를 받아 저장소 밖에 보관한다. 시연은 그 뒤에도 로컬(`docs/demo-guide.md`)에서 돈다. RDS는 삭제 방지가 켜져 있어 지우려면 운영진에게 요청한다.

## 배포할 때마다

- **스테이징**: develop에 머지하면 `images.yml`이 이미지를 만들고 스테이징에 올린다. 따로 할 일이 없다.
  - 배포로 API·화면 컨테이너가 다시 뜨는 10~30초 동안 앞단 프록시(Caddy)는 연결을 최대 30초 다시 시도한다(`deploy/Caddyfile`의 `lb_try_duration 30s`, #1403). 그동안 요청은 느려질 뿐 502로 실패하지 않는다. 연결을 잡고 있던 SSE는 끊기고 FE가 마지막 `id`로 다시 연결한다. Caddy 설정은 `sync.sh`가 배포 때마다 다시 읽는다(`caddy reload`).
- **운영(릴리스)**: 1) develop → main PR(멘토 리뷰)을 머지한다. 2) Actions의 `deploy`를 스테이징, `sha-<main 커밋 7자리>`로 돌린다. 3) Actions의 `staging-check`(QA 하네스를 서버의 스테이징 컨테이너 안에서 공개 주소로 돈다, 비밀은 서버 밖으로 나오지 않는다)를 그 커밋으로 돌린다. 매일 06:00에도 develop으로 돈다. 4) 통과하면 그 main 커밋에 `v0.x.y` 태그를 단다 → `images.yml`이 그 태그로 이미지를 만든다. 5) `deploy`를 운영, `v0.x.y`로 돌린다. 운영은 배포 직전에 DB를 덤프한다(`deploy/backup.sh`). 6) 아래 「지울 칸」 표를 본다. 줄의 칸을 읽던 코드가 방금 올린 태그에 없으면 그 줄의 줄이기 이슈를 진행한다. 이 태그가 이제 이전 릴리스 호환 검사의 기준이라 그 칸을 지우는 PR이 통과한다(#1465).
- **롤백**: `deploy`를 운영, 이전 `v` 태그로 돌린다. 버그는 그 버전 위에서 고치지 않고 develop에서 고쳐 다음 버전으로 올린다(멘토). 건강 확인에 실패한 배포는 `deploy.sh`가 이전 태그로 되돌린다.
- **환경 변수를 바꿀 때**: 서버의 `deploy/env/<환경>.env`를 고치고 그 환경을 다시 올린다. 새 키를 더한 PR은 `backend/.env.example`과 `deploy/env/*.env.example`을 같이 고친다. 값은 저장소나 채팅에 남기지 않는다.
- 이번 배포에 아래 「데이터가 바뀔 때」 단계가 있는지 확인한다. 마이그레이션 head는 하나여야 하고 CI(backend-test)가 확인한다.

## DB 연결 수

API 프로세스마다 SQLAlchemy 풀이 연결을 연다(`common/database.py`, 설정은 `common/settings.py`의 `DB_POOL_SIZE`, `DB_MAX_OVERFLOW`, `DB_POOL_PRE_PING`, `DB_POOL_RECYCLE_S`, #810). 기본은 풀 5 + 넘침 10, `pool_pre_ping`은 켬이다. 풀은 1 이상, 넘침은 0 이상, 재활용은 -1 또는 1 이상만 받고 그 밖은 기동에서 막는다(0 이하는 SQLAlchemy에서 연결 무제한이다). 이 계산이 DB의 `max_connections`를 넘지 않게 맞춘다.

`환경 2 × 프로세스 1 × (풀 + 넘침) + 작업 여유 ≤ DB max_connections` — `deploy/compose.yml`의 API 컨테이너 둘이 각각 `backend/Dockerfile`의 `--workers 1`로 돈다. 기본 상한은 2 × 1 × (5 + 10) = 30이다. 서버 안 DB의 `max_connections=60` 기준으로 남은 30 안에 정리·백업·마이그레이션·psql과 재배포 중 겹치는 프로세스의 연결을 모두 잡는다. 프로세스(워커)를 늘리면 곱하는 수가 늘어나니 풀 값을 같이 줄인다. 현재 RDS에서는 실제 `SHOW max_connections` 결과를 확인하고 같은 식으로 센다(60으로 가정하지 않는다). 별도 명령 프로세스도 자기 풀이 생기므로 명령 개수와 풀 상한을 작업 여유에 포함한다.

## 스키마를 바꿀 때

운영은 이전 태그로 돌아갈 수 있어야 한다. 그래서 테이블 변경은 이전 버전의 코드도 새 스키마에서 돌게 나눠서 한다(expand/contract, 멘토).

1. **늘리기(expand)**: 칸, 테이블, 인덱스를 더한다. 새 칸은 비어도 되거나 기본값이 있다. 이전 코드는 새 칸을 모른 채 돈다.
2. 새 코드를 배포한다. 새 코드는 새 칸을 쓰고, 필요하면 옛 칸에도 같이 쓴다.
3. **줄이기(contract)**: 다음 버전에서 옛 칸을 지운다. 지우는 마이그레이션은 그 칸을 읽는 코드가 운영에서 모두 빠진 뒤에만 넣는다.

- 칸 이름이나 뜻을 바꾸는 것은 「새 칸 더하기 → 옮기기 → 옛 칸 지우기」로 나눈다.
- API는 하위 호환으로 바꾼다. 필드는 더하기만 하고, 지우기는 화면이 쓰지 않게 된 다음에 한다.
- 모델에서 칸을 빼도 마이그레이션은 그 칸을 지우지 않는다. 남는 칸이 NOT NULL이면 새 코드의 INSERT를 위해 기본값을 건다. 지우는 일은 아래 「지울 칸」 표에 적고 다음 릴리스에 한다.

검사가 이 규칙을 지킨다(`backend/integration/test_schema_compat.py`, #1464). 빈 DB에 head까지 올리고 이전 릴리스(최신 `v` 태그, 없으면 `origin/main`)의 모델과 비교한다. 이전 코드가 쓰는 테이블·칸이 없거나, 이전 코드가 모르는 NOT NULL 칸에 기본값이 없거나, NULL을 허용하던 칸이 NOT NULL이 되면 실패한다. 그래서 줄이기는 그 칸을 읽는 코드가 이전 릴리스에서도 빠져야 통과한다. 이전 코드의 raw SQL, 이전 코드가 모르는 값, 칸의 뜻 변경은 검사가 못 보니 리뷰로 본다. 이 검사가 생기기 전 0062가 칸 삭제와 기본값 제거를 같은 마이그레이션에서 했다(멘토 리뷰, 0062를 고치고 0067이 되살렸다).

### 지울 칸

모델에서는 뺐지만 DB에 남겨 둔 테이블과 칸이다. 같은 검사가 지금 모델과 head 스키마를 비교해서, 모델에 없는 칸이 이 표에 없거나 표의 줄이 실제와 다르면 실패한다. 줄이기 마이그레이션을 넣을 때 그 줄을 지운다. 언제 지워도 되는지는 검사가 알리지 않으니 운영 릴리스 6단계에서 이 표를 본다.

| 테이블.칸 | 남긴 이유 | 줄이기 |
|---|---|---|
| `agent_course_runs.snapshot_pin_ids` | 일정 version(`snapshot_version`)이 대신한다(#1321). 이전 릴리스가 읽고 쓴다. 새 코드는 쓰지 않아 기본값 `'[]'`가 들어간다 | #1465 — 칸 삭제와 `snapshot_version` 기본값(`'legacy'`) 제거. 운영에 #1321 코드가 올라간 다음 릴리스 |

## 데이터가 바뀔 때

| 단계 | 언제 | 명령 | 주의 |
|---|---|---|---|
| 장소 적재 | 처음 한 번, 정예DB 공유본이 새로 나왔을 때 | 아래 "장소 데이터 적재" 순서 전체 | 정예를 먼저 `--authoritative`로, 커버리지(인허가)는 그다음. 끝에 나오는 `[curated] 분류별 정예 / 정예 아님` 수를 확인한다 |
| 영업시간(`place_hours`) | 장소 적재 뒤, 정예 라벨이 바뀌었을 때 | `python -m places.load place-hours --file <라벨 JSON>` | 장소를 먼저 넣는다(못 찾은 장소는 건수만 보고한다). 칸이 없는 장소는 행을 만들지 않고, 영업 여부는 "확인 필요"로 통과한다. 추천(「영업 종료 제거」)과 AI 코스(휴무 요일)가 함께 읽는다(#747) |
| 광고 | 광고를 넣거나 뺄 때 | `python -m ads.scripts.register --csv <경로>`, `python -m ads.scripts.deactivate <ad_id>` | `docs/ads.md`. 광고는 추천 후보 여부(`curated`)를 바꾸지 않는다. 장소를 새 DB에 다시 넣으면 장소 id가 바뀌므로 광고도 다시 등록한다 |

추천 후보 여부는 재계산할 것이 없다. 후보 조회가 `places.curated`를 바로 읽는다(#743). 정예가 늘면 정예 적재만 하면 된다.

**알려진 문제(#880, 고치는 건 데모 뒤)**: `curated`는 한 번 true가 되면 내려가지 않아, 다음 판에서 빠진 정예 장소가 추천 후보에 남는다. 같은 가게가 출처나 원본 번호가 달라 두 장소로 들어간 쌍도 약 700쌍 있다. 출처 기록(`place_sources`, 판)과 같은 가게 합치기로 고친다(`docs/data-model.md` 「출처 기록과 같은 가게 합치기」, #886 #887 #888).

### 장소 데이터 적재

지금 데이터는 정예DB 최종본 2026-11-04판이다(`정예DB_final_2026-11-04_서울`·`_타지역` 두 묶음, 한 폴더에 합쳐 쓴다)(서울, 그리고 v2 범위인 대전, 춘천, 광주, 대구, 부산). 폴더는 저장소 밖에 둔다. 명령은 `backend`에서 돌리고, 윈도는 먼저 `PYTHONUTF8=1`을 켠다. 공유본 안의 `README.md`가 명령의 정본이고, 아래는 그 순서를 옮긴 것이다.

1. 새 공유본으로 바꿀 때는 새 DB에서 시작한다. 로더는 파일에서 빠진 장소와 라벨을 지우지 않는다(공유본 `서울/README.md` "적재만으로는 지워지지 않는 것"). 새 DB를 만들고 `python -m alembic upgrade head`를 먼저 한다. **운영 DB는 예외다** — 사용자의 지도와 핀이 장소 id를 가리켜 새 DB로 갈아탈 수 없다. 운영에 새 판을 넣는 절차(제자리 갱신: 장소 id 유지, 출처 기록만 더하고, 빠진 정예는 추천 후보에서만 빠짐)는 #886이 끝나야 생긴다. 그 전에는 운영에 새 판을 넣지 않는다.
2. 서울 정예: `restaurants`, `cafes`, `tourapi` 순서로 `--authoritative --file <장소> --labels <라벨>`. 관광지 라벨은 JSON이 아니라 CSV다. 음식점 다음에 카페를 넣어 두 파일에 겹치는 6곳을 카페로 둔다(#507).
3. 서울 커버리지: `permit --encoding cp949`에 인허가 파일 3개를 `--file`로 한 번에 준다. 이어서 `restaurant-labels --file permit_cover_labels.json`.
4. 지역마다(v2): 2와 3을 `--all-regions`를 붙여 같은 순서로 한다(`restaurant-labels`에는 붙이지 않는다).
0. 시·도 경계(#1385): 장소보다 먼저 `boundaries --dir <폴더>/시도경계`. 통계청 2018 시·도 경계 17개 파일(`11.json` … `39.json`)이고 정본은 화면의 `frontend/src/features/map/regionBoundaries/`다. 데이터 폴더의 `시도경계/`에 그 파일을 **그대로** 복사해 둔다. 로더가 내용 해시를 `places/boundaries.py`의 기대값과 비교해 정본과 다른 파일이나 빠진 파일은 거절한다(17개를 모두 읽은 뒤에만 쓴다). 멱등이라 다시 돌려도 같은 코드는 덮어쓴다. `load-places.sh`는 데이터 폴더에 `시도경계/`가 없으면 경고만 하고 이 단계를 건너뛰며(장소 적재는 계속, 끝에 「경계 미적재」 안내, `DRY_RUN=1`도 같다), `boundaries`만 요청했는데 폴더가 없으면 중단한다. 이 표가 비어 있으면 `sido_at`은 가장 가까운 장소 주소로 시·도를 읽는 옛 방식으로 돌아가고(표가 있어도 경계에 안 드는 해안·섬·바다 점은 같은 방식으로 한 번 더 본다), `circle_outside_region`은 None(모름)이라 아무것도 막지 않는다. **이미 도는 DB(운영 포함)에는 마이그레이션(0064) 뒤에 `deploy/load-places.sh <환경> <데이터 폴더> boundaries`로 이 단계만 넣을 수 있다**(장소·라벨은 건드리지 않는다). 화면 경계 파일을 바꾸면 `places/boundaries.py`의 기대 해시를 같은 PR에서 고치고(`test_sido_boundaries_1385`가 어긋남을 잡는다), 서버 사본과 표를 다시 넣는다.
5. 영업시간: 장소를 모두 넣은 뒤 `place-hours`. 서울은 음식점 라벨 JSON, 카페 라벨 JSON, 관광지 `tourist_seoul_closed_days.json`. 지역은 음식점, 카페, 관광지 라벨 JSON에 `--all-regions`.

- 모든 명령은 `--dry-run`을 지원한다. 처음 한 명령은 dry-run으로 경로와 건수를 확인한다.
- 기존 DB를 유지한 채 인허가만 새로 받을 때 `permit --close-missing`을 쓴다(파일에 없는 커버리지를 폐업으로 바꾼다). 지역 커버리지에 쓰면 서울 커버리지가 닫히지 않는지 먼저 `--dry-run`으로 본다. 새 DB에서는 닫을 행이 없어 쓰지 않는다.
- 2026-10-27 로컬 실측(새 DB, 서울과 5개 지역 전부): 장소 199,211곳(정예 13,901), 라벨 약 191만 건, 영업시간 12,843곳.

## 스테이징

운영과 같은 방식으로 배포하고 실제 사용자는 없는 시험 서버다(`https://staging.ktc-pingopingo.duckdns.org`). QA 하네스(`qa/harness/run_api_cases.py --base-url`)가 이 주소로 핵심 흐름을 실제 HTTP로 돌린다(#788). 로컬에서는 `uvicorn`을 `PINGO_ENV=staging`으로 띄워 같은 방식으로 돌린다.

- `PINGO_ENV=staging`. 운영과 같은 기동 가드를 받는다(스텁 금지, CORS, `SESSION_SECRET`, `FRONTEND_BASE_URL`).
- `SESSION_SECRET`은 운영과 다른 값이다. 스테이징에서 만든 세션 쿠키가 운영에서 통하지 않게 한다.
- `QA_LOGIN_SECRET`이 있을 때만 `POST /auth/qa-login`이 붙는다(#789). 운영에는 이 값을 넣지 않는다. 넣으면 서버가 뜨지 않는다.
- `CREDIT_AD_PROVIDER=fake`면 잔액 부족 안내에 「광고 보고 크레딧 받기」가 뜨고 테스트 광고 창(7초)을 연다(docs/credits-reviews.md 3.7, #1037). 비우면 버튼이 없다. 확인은 잔액이 크레딧 가격보다 적은 계정으로 한다. 운영에 `fake`를 넣으면 서버가 뜨지 않는다(#1038). 운영은 비워 두고, 실제 광고(`adsense`, `gpt`)는 화면에 그 제공자가 생긴 뒤 켠다(아직 없음).
- DB는 운영과 나눈다. 운영 DB를 복사하지 않는다(실사용자 데이터, #53).
- 값은 저장소나 채팅에 남기지 않는다.

## 예약 실행

| 작업 | 명령 | 주기 | 상태 |
|---|---|---|---|
| 정기 정리: 지도, 알림, 게스트, 모델 호출 사용량, 멱등 키, 탈퇴 계정, 이벤트, 삭제된 핀(#1063) | `deploy/run.sh <환경> python -m maintenance.run` | 하루 한 번(03:30 운영, 03:40 스테이징). 단계마다 비지 않으면 라운드·시간 상한까지 되풀이하고, 그래도 남으면 로그에 「정리 적체」(WARNING, 탈퇴 정리는 ERROR). 마지막 성공은 로그 「정리 마지막 성공」(#1213) | 서버 cron(`deploy/crontab`) |
| 운영 DB 덤프 | `deploy/backup.sh prod` | 하루 한 번(04:00), 14일 보관 | 서버 cron. 운영 배포 직전에도 한다 |
| v2 계획 보조 에이전트 관찰 | cron이 `python -m agent.tick`을 부른다(#812). 지도마다 lease와 token으로 겹쳐 돌아도 안전하다 | 5분(`docs/agent-v2.md` 12.1) | 서버 cron |
| agent 일일 정리 | 없음 | 서버 안에서 돈다 | 따로 예약하지 않는다(`backend/maintenance/CLAUDE.md`) |
| 헬스 체크 경보: 운영·스테이징의 화면(`/`)과 `/api/health` | `.github/workflows/uptime.yml`. 두 번(30초 간격) 다 실패하면 이슈 「[경보] 운영·스테이징 헬스 체크 실패」를 열고, 회복하면 닫는다(#1280) | 10분 안팎(GitHub 예약 실행) | GitHub Actions — 서버 밖에서 본다 |
| 장소 후기 신고 확인 | 아래 「후기 신고 확인과 숨김」 | 매일(운영) | **사람이 한다.** 신고가 와도 알림이 없다 — 자동 알림은 아직 없다 |

### 후기 신고 확인과 숨김

장소 후기(#432, `docs/credits-reviews.md` 5절·10절)는 다른 지도 사람에게도 보이는 글이라 신고를 받는다. 관리 화면은 없고(D8) 서버에서 스크립트로 본다. 권리침해 게시물 임시조치는 요청을 받으면 지체 없이 해야 하므로 **운영은 매일 한 번 확인한다.** 신고만으로는 숨겨지지 않는다.

1. 콘솔 EC2 → 연결 → Session Manager로 서버에 들어가 `cd /srv/pingo/deploy`.
2. 신고 목록(숨기지 않은 후기, 신고 많은 순 20개):
   ```
   ./run.sh prod python -m reviews.scripts.reports
   ./run.sh prod python -m reviews.scripts.reports --limit 50   # 더 보기
   ./run.sh prod python -m reviews.scripts.reports --all        # 숨긴 것도 [숨김] 표시와 함께
   ```
   후기 id, 신고 수, 마지막 신고 시각, 장소 이름, 별점, 글이 나온다. 작성자와 신고자는 나오지 않는다(숨길지는 글로 정한다).
3. 숨길 글이면(욕설, 비방, 개인정보, 장소와 무관한 글, 권리침해 주장):
   ```
   ./run.sh prod python -m reviews.scripts.hide <review_id>          # 숨기기
   ./run.sh prod python -m reviews.scripts.hide <review_id> --undo   # 잘못 숨겼으면 되돌리기
   ```
   숨긴 후기는 목록·평균·개수에서 빠지고 작성자에게도 안 보인다. 작성자가 고치거나 지웠다 다시 써서 숨김을 풀 수 없다.

- 스테이징은 `prod` 대신 `staging`.
- **출력은 터미널에서만 본다.** 모르는 사람이 쓴 글이라 파일·디스코드·이슈로 옮기지 않는다. 판단을 남길 때는 후기 id만 적는다.
- 하루 신고 수, 숨김 수, 신고에서 숨김까지 걸린 시간을 보는 SQL은 `backend/reviews/scripts/README.md`.

## 배포 뒤 볼 지표

지도가 늘면 v2 관찰(tick)이 가장 먼저 걸린다(멘토 리뷰 #680). tick은 5분마다 지도를 최대 `TICK_MAX_MAPS`(6)곳 관찰한다(`agent/constants.py`). 자동 경보는 두지 않고 아래 기준을 사람이 하루 한 번 본다(2026-11-02 결정, #1072).

| 지표 | 읽는 법 | 이렇게 보이면 |
|---|---|---|
| stale로 버린 관찰 비율 | `select outcome, count(*) from agent_runs where trigger in ('activity', 'time') and started_at > now() - interval '1 day' group by 1` 에서 stale ÷ 전체 | 늘면 관찰이 겹치거나 늦게 끝나고 있다. 결과가 틀리지는 않지만(저장할 때 지도 행을 잠그고 다시 확인한다) 모델 호출을 버린다 |
| tick당 처리 수와 미룬 지도 수, 걸린 시간 | tick 끝의 로그 한 줄 `agent tick due= observed= deferred_by_max= deferred_by_budget= elapsed_ms=`(#756). 차례였던 지도, 관찰한 수, `TICK_MAX_MAPS`로 미룬 수, 시간 예산으로 미룬 수, 걸린 ms. 시간 예산으로 미룬 지도가 있으면 warning | 미룬 지도가 tick마다 남으면 처리 수나 주기를 바꾼다. 시간 예산으로 미룬 지도가 연속 3 tick이면 본다(#1072). 시간 예산은 150초(`TICK_BUDGET_SEC`)로 두고 이 지표로 본다(#754). 걸린 시간이 lease(180초)를 넘는 tick이 보이면 105초(`LEASE_SEC − 75`)로 낮춘다. 로그는 서버의 `/srv/pingo/logs/agent-tick-<환경>.log`다 |
| 진단 실패 비율 | `select outcome, count(*) from agent_runs where used_model and trigger in ('activity', 'time') and started_at > now() - interval '1 day' group by 1` 에서 model_failed와 invalid_schema ÷ 전체 | 20% 이상이면 모델 제공자 상태를 본다(#1072). 진단만 실패하고 다른 기능은 돈다. 진단 전체를 끄는 장치는 두지 않았다(`docs/agent-v2.md` 21.3) |
| 관찰 예외 | `select outcome_detail->>'stage', outcome_detail->>'error', count(*) from agent_runs where outcome = 'error' and started_at > now() - interval '1 day' group by 1, 2` | 1건부터 본다(#1072). 코드 오류다. 그 지도는 30분, 2시간, 6시간 뒤 다시 관찰된다 |
| 서비스 일일 예산과 웹 확인 | `select date_trunc('day', created_at at time zone 'Asia/Seoul') d, feature, count(*), sum(web_searches), round(sum(cost_krw)) from llm_calls where created_at > now() - interval '7 days' group by 1, 2 order by 1, 2`. 막힌 날은 API 로그의 `llm daily budget paused` | 예산(`LLM_DAILY_BUDGET_KRW`, 3,000원)에 닿는 날이 이어지면 웹 확인 대상(제안당 1줄)이나 예산을 다시 본다. 웹 검색 요금은 OpenAI 대시보드의 web search 줄과 `sum(web_searches)`를 대조한다(#1216). 웹 확인을 끄려면 `LLM_DAILY_BUDGET_KRW=0` 뒤 API 다시 만들기 |

### 에이전트 개입 라벨링 표본 (#1072)

v2 지도 제안이 쓸모 있었는지(탐지 정밀도, `docs/agent-v2.md` 21.5)를 재려고 스테이징의 제안 표본을 뽑아 사람이 라벨을 붙인다. QA로 지도가 쌓인 뒤 한다. **운영에서는 돌리지 않는다**(운영 DB를 밖으로 옮기지 않는다, #53). 명령은 PINGO_ENV가 staging이 아니면 `--staging`을 거부한다(#1076).

1. 콘솔 EC2 → 연결 → Session Manager로 서버에 들어가 `cd /srv/pingo/deploy`.
2. 표본 뽑기(유형마다 25건까지, 같은 seed면 같은 표본):
   ```
   ./run.sh staging python -m agent.label_sample --staging --out - > /tmp/agent-labels.csv
   ./run.sh staging python -m agent.label_sample --staging --per-type 40 --seed 3 --out - > /tmp/agent-labels.csv
   ```
   유형별 건수는 화면(표준 오류)에 나오고 파일에는 CSV만 간다. 모두 0이면 아직 관찰된 제안이 없는 것이다.
3. 파일 가져오기: 브라우저 터미널에는 내려받기가 없어 `cat /tmp/agent-labels.csv`로 띄워 복사하고, 이 PC에서 `.csv`로 저장한다. 엑셀에서 한글이 깨지면 데이터 → 텍스트/CSV에서 UTF-8로 연다.
4. 서버의 파일 지우기: `rm /tmp/agent-labels.csv`. CSV는 저장소에 커밋하지 않는다.
5. 「개입할 만했나」와 메모 칸을 채우고(판정 기준은 `docs/agent-v2.md` 21.5), 유형별 수를 21.5 표에 옮긴다.

CSV에는 사유 원문, 구성원 이름, 인용 글, 실시간 핀 검색어가 없다. 인용은 「[인용]」, 핀 이름은 「[핀]」으로 바뀌어 나온다(`agent/label_sample.py`).

### 모델 제공자 키 바꾸기 (#1120)

모델은 2026-11-02부터 OpenAI API를 직접 부른다(`gpt-6-luna`). 환경 변수 이름은 `ELICE_ML_API_*`로 남아 있다. 키를 새로 넣거나 새서 바꿀 때 이 순서로 한다. 환경마다 OpenAI 프로젝트와 키를 따로 쓴다(로컬, 스테이징, 운영).

1. OpenAI 플랫폼에서 그 환경 프로젝트의 새 키를 만든다. 키는 만들 때 한 번만 보인다. 프로젝트마다 월 예산 한도를 걸어 둔다. 코드의 서비스 일일 예산(`LLM_DAILY_BUDGET_KRW`, 하루 3,000원)은 넘으면 웹 확인만 끄고 진단, 현황 문단, 추천, AI 코스는 그대로 부른다(`docs/agent-v2.md` 19절). 그래서 모든 호출을 막는 지출 방어선은 이 프로젝트 한도뿐이다.
2. 서버 Session Manager에서 `bash`로 바꾼 뒤(기본 셸이 sh라 `read -s`가 안 된다) 키가 화면과 기록에 남지 않게 넣는다. `<환경>`은 `staging` 또는 `prod`다.
   ```
   bash
   cd /srv/pingo/deploy
   cp -p env/<환경>.env env/<환경>.env.before-key
   sed -i 's|^ELICE_ML_API_BASE_URL=.*|ELICE_ML_API_BASE_URL=https://api.openai.com/v1|' env/<환경>.env
   read -s -p "키: " K; echo
   sed -i "s|^ELICE_ML_API_KEY=.*|ELICE_ML_API_KEY=$K|" env/<환경>.env; unset K
   docker compose up -d --no-deps --force-recreate api-<환경>
   docker compose ps api-<환경>        # 1~2분 안에 (healthy)
   ```
   `env/<환경>.env`를 `cat`으로 통째로 보지 않는다(비밀값이 나온다). 확인은 주소 줄만 `grep '^ELICE_ML_API_BASE_URL'`로 한다. 키 입력 칸은 붙여 넣어도 화면에 아무것도 안 보이는 것이 정상이다. 여러 줄을 한꺼번에 붙여 넣으면 다음 줄이 키로 들어가므로 한 줄씩 한다.
3. 키가 통하는지 컨테이너 안에서 본다. 출력은 모델 이름이나 오류 클래스뿐이다.
   ```
   docker compose exec -T api-<환경> python -c "
   from common.settings import settings
   from openai import OpenAI
   try:
       print(OpenAI(base_url=settings.elice_ml_api_base_url, api_key=settings.elice_ml_api_key).models.retrieve('gpt-6-luna').id)
   except Exception as e:
       print(type(e).__name__, getattr(e, 'status_code', ''))
   "
   ```
   `gpt-6-luna`가 나오면 된다. `AuthenticationError 401`은 키가 틀렸거나 붙여 넣을 때 잘못 들어간 것이다. `NotFoundError 404`, `PermissionDeniedError 403`은 그 프로젝트에 모델 접근이 없는 것이다.
4. 스테이징이면 Actions의 `staging-check`를 돌리고 화면에서 추천과 AI 코스를 한 번씩 누른다.
5. 되돌리기: `cp -p env/<환경>.env.before-key env/<환경>.env` 뒤 같은 `up` 명령. 사본은 바꾸기 전 값이다. 새서 바꾼 거라면 사본을 지운다(`rm`).

## 배포 전에 정할 것

- 모델 제공자를 OpenAI 직접 호출로 바꾼 뒤(#1120) 정하지 않은 것: 사유 글이 미국 OpenAI로 가는 데 따른 개인정보 국외 이전 고지(`최종기획안.md` 12절, 개인정보처리방침), 결제 주체(개인 카드인지 팀 계정인지), 운영 전환 시기. 운영은 아직 엘리스 때의 설정이다.
- `event_log` 오래된 행 삭제: 읽기는 24시간으로 자르지만(`realtime.service.RETENTION`) 지우는 작업은 아직 없다. `created_at` 인덱스는 삭제용으로 있다. 정기 정리(`maintenance.run`)에 단계로 넣을지 정한다.
- auth의 세션·state·선택 대기 쿠키의 `Secure`는 모두 `settings.cookie_secure`를 쓴다(#810). `COOKIE_SECURE` 기본은 staging, prod에서 켬이고 dev, test에서 끔이다. 응답의 `Set-Cookie`는 `auth/tests/test_cookie_secure.py`에서 검증한다. 로컬 http로 staging을 띄워 하네스를 돌릴 때만 `COOKIE_SECURE=0`으로 끈다. 배포 서버에서는 기본값을 유지한다.
- staging, prod 기동 가드는 CORS, `SESSION_SECRET`, `FRONTEND_BASE_URL`에 더해 실제 어댑터의 키가 비거나 공백뿐이면 `ConfigError`로 막는다(#810). `PLACES_MODE=real`일 때 `PLACES_SOURCES`에 `kakao`가 있으면 `KAKAO_REST_API_KEY`(비면 `KAKAO_CLIENT_ID`로 폴백), `naver`가 있으면 `NAVER_SEARCH_CLIENT_ID`와 `NAVER_SEARCH_CLIENT_SECRET`이 필요하다. 선택하지 않은 소스의 키는 요구하지 않는다. 로그인용 `KAKAO_CLIENT_SECRET`, `KAKAO_REDIRECT_URI`는 장소 어댑터 키가 아니며 로그인 설정은 별도로 채운다. `LLM_MODE=real`이면 `ELICE_ML_API_BASE_URL`, `ELICE_ML_API_KEY`가 필요하다(2026-11-02부터 이 두 값은 OpenAI 주소와 프로젝트 키이고 이름만 ELICE로 남았다, #1120). dev, test에서는 키 없이도 기동한다. 오류에는 누락된 변수 이름만 담고 키 값은 담지 않는다.
- uvicorn 접근 로그는 모든 경로의 쿼리스트링(code·state·검색어·좌표)을 지우고 초대 토큰 경로는 `/invites/{token}`으로 바꿔 찍는다. DB 오류의 예외 로그는 SQL 매개변수 없이 종류와 호출 위치만 남긴다(`common/logguard.py`, #473, #1201). Dockerfile의 uvicorn 실행 인자는 바꾸지 않았다. 앞단 Caddy는 접근 로그를 켜지 않는다(`deploy/Caddyfile`, #473). 켜야 하면 쿼리스트링을 지우는 형식으로 켠다.
- 비로그인 `GET /invites/{token}`에는 호출 상한이 없다. 토큰이 256비트라 추측은 비현실적이지만, 넣을지 정한다(#168).
- 개발 중 로컬 DB에 쌓인 카카오 좌표와 이름은 배포 전에 지운다(`docs/architecture.md`, #53). 배포 DB를 로컬 DB에서 복사하지 않는다.
