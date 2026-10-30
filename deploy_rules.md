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
| 한 주소로 서빙 | 환경마다 `/api/*`는 API(앞의 `/api`를 떼고 넘긴다), 나머지는 화면 정적 파일. 화면은 `VITE_API_BASE_URL=/api`로 빌드한다. API는 `UVICORN_ROOT_PATH=/api`(`deploy/compose.yml`)로 자기 공개 경로를 안다(`/docs`, 접근 로그) | 세션 쿠키가 `SameSite=lax`라 화면과 API가 같은 사이트여야 로그인이 된다. CORS도 필요 없다. 백엔드 경로는 그대로다 | — |
| 환경 | 운영과 스테이징을 같은 서버에서 나눈다(컨테이너, DB 이름, 비밀값이 다르다) | 멘토 「환경 분리」. 서버가 1대다 | 서버를 더 받을 때 |
| DB | RDS(PostgreSQL 17.11, PostGIS 3.5.6, 2026-10-30 승인) 한 대에 DB `pingo_prod`, `pingo_staging`. 앱은 환경마다 전용 계정(`pingo_prod_app`, `pingo_staging_app`)으로 SSL(`sslmode=require`)로 붙는다. 옮기기 전까지는 서버 안 PostgreSQL 컨테이너(`compose.db.yml`)다. 옮기는 법은 아래 「RDS로 옮기기」(#873) | 자동 백업 7일, 삭제 방지, 팀 EC2에서만 접속. 마스터 비밀번호는 Secrets Manager가 30일마다 바꾸므로 앱은 마스터를 쓰지 않는다. 앱 계정은 자기 DB만 열어 환경이 나뉜다 | 2026-11-20(AWS 종료) |
| 프로세스 | 환경마다 API 프로세스 1개(uvicorn 워커 1) | 메모리 요청 상한, 서버 시작 시 정리, 관찰 lease가 이 전제에서 안전하다. 4GB에 두 환경이 들어간다 | 응답이 느려지거나 워커를 늘릴 때. 그 전에 아래 「타협」을 고친다 |
| 이미지 | GitHub Actions가 API, 화면 이미지를 만들어 팀 계정 ECR(`pingo-api`, `pingo-web`, 최근 40개 보관)에 올린다(`.github/workflows/images.yml`). 태그는 `sha-<7자리>`, 브랜치 이름, `v0.x.y` | 빌드와 배포를 나눈다(멘토). 서버는 자기 역할로 ECR에서 받는다(저장한 비밀 없음) | — |
| 배포 | `.github/workflows/deploy.yml`이 OIDC 역할로 SSM 명령을 보내 서버의 `deploy/deploy.sh <환경> <태그>`를 돌린다. develop은 이미지가 만들어지면 스테이징에 자동, 운영은 사람이 v 태그를 골라 수동 | 22번 포트와 서버 키가 없다. 운영은 태그를 골라 올린다(멘토) | — |
| 확인 | 스테이징에서 QA 하네스(`qa/harness/run_api_cases.py --base-url`)로 핵심 흐름을 돈다. 통과한 `main` 커밋에만 태그를 단다 | 멘토 「배포된 주소의 핵심 흐름 테스트, 통과한 커밋에만 태그」 | — |
| 비밀 | 서버의 `deploy/env/*.env`(권한 600). 세션 비밀, DB 비밀번호, QA 비밀은 서버에서 만들었고 외부 키(카카오, 엘리스)만 옮겼다. 저장소, 이미지, 채팅에 남기지 않는다 | 서버 1대에 가장 단순하다 | 사람이나 서버가 늘 때 SSM 파라미터 스토어 |
| 주기 작업 | 서버 cron(`deploy/crontab`). 두 번 돌아도 안전한 작업만 둔다 | 멘토 「주기 작업은 바깥에서 부르되 두 번 돌아도 안전하게」 | — |

### 타협과 다시 볼 조건

멘토: 이유가 빠진 타협은 나중에 원래 그런 구조로 읽힌다. 프로세스나 서버를 늘리기 전에 아래를 먼저 고친다.

| 타협 | 왜 지금은 괜찮나 | 다시 볼 때 |
|---|---|---|
| 요청 상한 5곳(`common.ratelimit`)이 메모리에서 센다 | 환경마다 프로세스가 하나다. 배포로 다시 뜨면 셈이 처음부터다 | 워커나 서버를 늘리기 전에 같은 모양(`SlidingWindowLimiter`)으로 Postgres에 옮긴다 |
| 서버 시작 시 진행 중인 AI 코스 run을 모두 끝낸다(`interrupt_unfinished_runs`) | 프로세스가 하나라 끝내는 run은 모두 죽은 프로세스의 것이다 | 프로세스가 둘 이상이면 다른 프로세스의 run을 끊는다 — 마지막 진행이 오래된 run만 끝내게 고친다(#813) |
| AI 코스 계산이 응답 뒤 `BackgroundTasks`로 돈다 | 서버(VM)는 요청이 끝나도 CPU를 준다. 배포로 다시 뜨면 그 run은 위 정리로 끝난다 | 작업 큐로 옮길 때 |
| 관찰 tick이 프로세스 안 반복 작업(`AGENT_LOOP_IN_PROCESS=1`)으로 돈다 | 프로세스가 하나라 한 번만 돈다 | 관찰 tick 명령(`python -m agent.tick`)과 lease fencing이 생기면 cron으로 옮긴다(#812) |
| DB가 같은 서버에 있고 덤프도 같은 디스크에 있다 | 시연까지의 데이터다 | RDS로 옮기면 풀린다(#873, RDS 자동 백업). 옮긴 뒤에도 `backup.sh` 덤프는 서버 디스크에 쌓인다 |
| 운영과 스테이징이 RDS 한 대를 나눠 쓴다 | DB와 계정이 나뉘어 서로 열지 못한다. 부하가 작다 | 스테이징 부하(측정, QA)가 운영 응답을 늦추면 |

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
- **운영(릴리스)**: 1) develop → main PR(멘토 리뷰)을 머지한다. 2) Actions의 `deploy`를 스테이징, `sha-<main 커밋 7자리>`로 돌린다. 3) Actions의 `staging-check`(QA 하네스를 서버의 스테이징 컨테이너 안에서 공개 주소로 돈다, 비밀은 서버 밖으로 나오지 않는다)를 그 커밋으로 돌린다. 매일 06:00에도 develop으로 돈다. 4) 통과하면 그 main 커밋에 `v0.x.y` 태그를 단다 → `images.yml`이 그 태그로 이미지를 만든다. 5) `deploy`를 운영, `v0.x.y`로 돌린다. 운영은 배포 직전에 DB를 덤프한다(`deploy/backup.sh`).
- **롤백**: `deploy`를 운영, 이전 `v` 태그로 돌린다. 버그는 그 버전 위에서 고치지 않고 develop에서 고쳐 다음 버전으로 올린다(멘토). 건강 확인에 실패한 배포는 `deploy.sh`가 이전 태그로 되돌린다.
- **환경 변수를 바꿀 때**: 서버의 `deploy/env/<환경>.env`를 고치고 그 환경을 다시 올린다. 새 키를 더한 PR은 `backend/.env.example`과 `deploy/env/*.env.example`을 같이 고친다. 값은 저장소나 채팅에 남기지 않는다.
- 이번 배포에 아래 「데이터가 바뀔 때」 단계가 있는지 확인한다. 마이그레이션 head는 하나여야 하고 CI(backend-test)가 확인한다.

## DB 연결 수

API 프로세스마다 SQLAlchemy 풀이 연결을 연다(`common/database.py`, 설정은 `common/settings.py`의 `DB_POOL_SIZE`, `DB_MAX_OVERFLOW`, `DB_POOL_PRE_PING`, `DB_POOL_RECYCLE_S`, #810). 기본은 풀 5 + 넘침 10, `pool_pre_ping`은 켬이다. 풀은 1 이상, 넘침은 0 이상, 재활용은 -1 또는 1 이상만 받고 그 밖은 기동에서 막는다(0 이하는 SQLAlchemy에서 연결 무제한이다). 이 계산이 DB의 `max_connections`를 넘지 않게 맞춘다.

`환경 2 × 프로세스 1 × (풀 + 넘침) + 작업 여유 ≤ DB max_connections` — 서버 안 DB는 `max_connections`가 60이라 2 × 1 × 15 = 30에 정리·백업·psql 작업 여유가 들어간다. 프로세스(워커)를 늘리면 곱하는 수가 늘어나니 풀 값을 같이 줄인다. RDS는 인스턴스 크기에 따른 `max_connections`를 확인하고 같은 식으로 센다.

## 스키마를 바꿀 때

운영은 이전 태그로 돌아갈 수 있어야 한다. 그래서 테이블 변경은 이전 버전의 코드도 새 스키마에서 돌게 나눠서 한다(expand/contract, 멘토).

1. **늘리기(expand)**: 칸, 테이블, 인덱스를 더한다. 새 칸은 비어도 되거나 기본값이 있다. 이전 코드는 새 칸을 모른 채 돈다.
2. 새 코드를 배포한다. 새 코드는 새 칸을 쓰고, 필요하면 옛 칸에도 같이 쓴다.
3. **줄이기(contract)**: 다음 버전에서 옛 칸을 지운다. 지우는 마이그레이션은 그 칸을 읽는 코드가 운영에서 모두 빠진 뒤에만 넣는다.

- 칸 이름이나 뜻을 바꾸는 것은 「새 칸 더하기 → 옮기기 → 옛 칸 지우기」로 나눈다.
- API는 하위 호환으로 바꾼다. 필드는 더하기만 하고, 지우기는 화면이 쓰지 않게 된 다음에 한다.

## 데이터가 바뀔 때

| 단계 | 언제 | 명령 | 주의 |
|---|---|---|---|
| 장소 적재 | 처음 한 번, 정예DB 공유본이 새로 나왔을 때 | 아래 "장소 데이터 적재" 순서 전체 | 정예를 먼저 `--authoritative`로, 커버리지(인허가)는 그다음. 끝에 나오는 `[curated] 분류별 정예 / 정예 아님` 수를 확인한다 |
| 영업시간(`place_hours`) | 장소 적재 뒤, 정예 라벨이 바뀌었을 때 | `python -m places.load place-hours --file <라벨 JSON>` | 장소를 먼저 넣는다(못 찾은 장소는 건수만 보고한다). 칸이 없는 장소는 행을 만들지 않고, 영업 여부는 "확인 필요"로 통과한다. 추천(「영업 종료 제거」)과 AI 코스(휴무 요일)가 함께 읽는다(#747) |
| 광고 | 광고를 넣거나 뺄 때 | `python -m ads.scripts.register --csv <경로>`, `python -m ads.scripts.deactivate <ad_id>` | `docs/ads.md`. 광고는 추천 후보 여부(`curated`)를 바꾸지 않는다. 장소를 새 DB에 다시 넣으면 장소 id가 바뀌므로 광고도 다시 등록한다 |

추천 후보 여부는 재계산할 것이 없다. 후보 조회가 `places.curated`를 바로 읽는다(#743). 정예가 늘면 정예 적재만 하면 된다.

**알려진 문제(#880, 고치는 건 데모 뒤)**: `curated`는 한 번 true가 되면 내려가지 않아, 다음 판에서 빠진 정예 장소가 추천 후보에 남는다. 같은 가게가 출처나 원본 번호가 달라 두 장소로 들어간 쌍도 약 700쌍 있다. 출처 기록(`place_sources`, 판)과 같은 가게 합치기로 고친다(`docs/data-model.md` 「출처 기록과 같은 가게 합치기」, #886 #887 #888).

### 장소 데이터 적재

지금 데이터는 정예DB 공유본 2026-10-25판이다(서울, 그리고 v2 범위인 대전, 춘천, 광주, 대구, 부산). 폴더는 저장소 밖에 둔다. 명령은 `backend`에서 돌리고, 윈도는 먼저 `PYTHONUTF8=1`을 켠다. 공유본 안의 `README.md`가 명령의 정본이고, 아래는 그 순서를 옮긴 것이다.

1. 새 공유본으로 바꿀 때는 새 DB에서 시작한다. 로더는 파일에서 빠진 장소와 라벨을 지우지 않는다(공유본 `서울/README.md` "적재만으로는 지워지지 않는 것"). 새 DB를 만들고 `python -m alembic upgrade head`를 먼저 한다. **운영 DB는 예외다** — 사용자의 지도와 핀이 장소 id를 가리켜 새 DB로 갈아탈 수 없다. 운영에 새 판을 넣는 절차(제자리 갱신: 장소 id 유지, 출처 기록만 더하고, 빠진 정예는 추천 후보에서만 빠짐)는 #886이 끝나야 생긴다. 그 전에는 운영에 새 판을 넣지 않는다.
2. 서울 정예: `restaurants`, `cafes`, `tourapi` 순서로 `--authoritative --file <장소> --labels <라벨>`. 관광지 라벨은 JSON이 아니라 CSV다. 음식점 다음에 카페를 넣어 두 파일에 겹치는 6곳을 카페로 둔다(#507).
3. 서울 커버리지: `permit --encoding cp949`에 인허가 파일 3개를 `--file`로 한 번에 준다. 이어서 `restaurant-labels --file permit_cover_labels.json`.
4. 지역마다(v2): 2와 3을 `--all-regions`를 붙여 같은 순서로 한다(`restaurant-labels`에는 붙이지 않는다).
5. 영업시간: 장소를 모두 넣은 뒤 `place-hours`. 서울은 음식점 라벨 JSON, 카페 라벨 JSON, 관광지 `tourist_seoul_closed_days.json`. 지역은 음식점, 카페, 관광지 라벨 JSON에 `--all-regions`.

- 모든 명령은 `--dry-run`을 지원한다. 처음 한 명령은 dry-run으로 경로와 건수를 확인한다.
- 기존 DB를 유지한 채 인허가만 새로 받을 때 `permit --close-missing`을 쓴다(파일에 없는 커버리지를 폐업으로 바꾼다). 지역 커버리지에 쓰면 서울 커버리지가 닫히지 않는지 먼저 `--dry-run`으로 본다. 새 DB에서는 닫을 행이 없어 쓰지 않는다.
- 2026-10-27 로컬 실측(새 DB, 서울과 5개 지역 전부): 장소 199,211곳(정예 13,901), 라벨 약 191만 건, 영업시간 12,843곳.

## 스테이징

운영과 같은 방식으로 배포하고 실제 사용자는 없는 시험 서버다(`https://staging.ktc-pingopingo.duckdns.org`). QA 하네스(`qa/harness/run_api_cases.py --base-url`)가 이 주소로 핵심 흐름을 실제 HTTP로 돌린다(#788). 로컬에서는 `uvicorn`을 `PINGO_ENV=staging`으로 띄워 같은 방식으로 돌린다.

- `PINGO_ENV=staging`. 운영과 같은 기동 가드를 받는다(스텁 금지, CORS, `SESSION_SECRET`, `FRONTEND_BASE_URL`).
- `SESSION_SECRET`은 운영과 다른 값이다. 스테이징에서 만든 세션 쿠키가 운영에서 통하지 않게 한다.
- `QA_LOGIN_SECRET`이 있을 때만 `POST /auth/qa-login`이 붙는다(#789). 운영에는 이 값을 넣지 않는다. 넣으면 서버가 뜨지 않는다.
- DB는 운영과 나눈다. 운영 DB를 복사하지 않는다(실사용자 데이터, #53).
- 값은 저장소나 채팅에 남기지 않는다.

## 예약 실행

| 작업 | 명령 | 주기 | 상태 |
|---|---|---|---|
| 정기 정리: 지도(삭제 30일 후), 알림(90일), 게스트(90일 미사용), 모델 호출 사용량 `llm_calls`(30일, #870) | `deploy/run.sh <환경> python -m maintenance.run` | 하루 한 번(03:30 운영, 03:40 스테이징) | 서버 cron(`deploy/crontab`) |
| 운영 DB 덤프 | `deploy/backup.sh prod` | 하루 한 번(04:00), 14일 보관 | 서버 cron. 운영 배포 직전에도 한다 |
| v2 계획 보조 에이전트 관찰 | 지금은 프로세스 안 반복 작업(`AGENT_LOOP_IN_PROCESS=1`) | 5분(`docs/agent-v2.md` 12.1) | 관찰 tick 명령과 lease fencing이 생기면 cron으로 옮긴다(위 「타협」, #812) |
| agent 일일 정리 | 없음 | 서버 안에서 돈다 | 따로 예약하지 않는다(`backend/maintenance/CLAUDE.md`) |

## 배포 뒤 볼 지표

지도가 늘면 v2 관찰(tick)이 가장 먼저 걸린다(멘토 리뷰 #680). tick은 5분마다 지도를 최대 `TICK_MAX_MAPS`(6)곳 관찰한다(`agent/constants.py`).

| 지표 | 읽는 법 | 이렇게 보이면 |
|---|---|---|
| stale로 버린 관찰 비율 | `select outcome, count(*) from agent_runs where trigger in ('activity', 'time') and started_at > now() - interval '1 day' group by 1` 에서 stale ÷ 전체 | 늘면 관찰이 겹치거나 늦게 끝나고 있다. 결과가 틀리지는 않지만(저장할 때 지도 행을 잠그고 다시 확인한다) 모델 호출을 버린다 |
| tick당 처리 수와 미룬 지도 수, 걸린 시간 | tick 끝의 로그 한 줄 `agent tick due= observed= deferred_by_max= deferred_by_budget= elapsed_ms=`(#756). 차례였던 지도, 관찰한 수, `TICK_MAX_MAPS`로 미룬 수, 시간 예산으로 미룬 수, 걸린 ms. 시간 예산으로 미룬 지도가 있으면 warning | 미룬 지도가 tick마다 남으면 처리 수나 주기를 바꾼다. 시간 예산은 150초(`TICK_BUDGET_SEC`)로 두고 이 지표로 본다(#754). 걸린 시간이 lease(180초)를 넘는 tick이 보이면 105초(`LEASE_SEC − 75`)로 낮춘다 |

## 배포 전에 정할 것

- `event_log` 오래된 행 삭제: 읽기는 24시간으로 자르지만(`realtime.service.RETENTION`) 지우는 작업은 아직 없다. `created_at` 인덱스는 삭제용으로 있다. 정기 정리(`maintenance.run`)에 단계로 넣을지 정한다.
- 세션 쿠키의 `Secure`는 설정 `COOKIE_SECURE`가 정한다(#810). 기본은 staging, prod에서 켬이고 dev, test에서 끔이다. 아직은 설정 정의만 끝났다. 실제 쿠키에 Secure를 거는 일(`settings.cookie_secure` 사용)은 auth 후속이고, 그때 응답의 `Set-Cookie`도 검증한다. 로컬 http로 staging을 띄워 하네스를 돌릴 때만 `COOKIE_SECURE=0`으로 끈다. 배포된 서버의 env에는 적지 않는다.
- staging, prod 기동 가드는 CORS, `SESSION_SECRET`, `FRONTEND_BASE_URL`에 더해 `PLACES_MODE=real`이면 카카오 키(`KAKAO_CLIENT_ID/SECRET/REDIRECT_URI`), `LLM_MODE=real`이면 `ELICE_ML_API_BASE_URL`, `ELICE_ML_API_KEY`가 비었을 때 서버를 세운다(#810).
- `/places/nearest`의 쿼리스트링(누른 좌표)은 uvicorn 접근 로그에서만 가린다(`places/logguard.py`). 앞단 Caddy는 접근 로그를 켜지 않는다(`deploy/Caddyfile`, #473). 켜야 하면 쿼리스트링을 지우는 형식으로 켠다.
- 비로그인 `GET /invites/{token}`에는 호출 상한이 없다. 토큰이 256비트라 추측은 비현실적이지만, 넣을지 정한다(#168).
- 개발 중 로컬 DB에 쌓인 카카오 좌표와 이름은 배포 전에 지운다(`docs/architecture.md`, #53). 배포 DB를 로컬 DB에서 복사하지 않는다.
