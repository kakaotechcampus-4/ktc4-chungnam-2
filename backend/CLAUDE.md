# backend

루트 문서를 먼저 읽는다: `/CLAUDE.md`. 그다음 이 문서, 그다음 자기가 맡은 `backend/<module>/CLAUDE.md`.
이 문서는 모듈 전체에 공통인 것만 담는다 — 모듈 하나만의 이야기는 그 모듈 CLAUDE.md로.

## 단일 FastAPI 앱 — 마이크로서비스 아님

하나의 FastAPI 앱(단일 Cloud Run 배포, 최종기획안 13절)에 `backend/<module>/`이 각각 파이썬
패키지로 들어간다.

```
backend/
  main.py            -- FastAPI() 생성 + 각 모듈 router include
  <module>/
    router.py         -- 이 모듈 소유 엔드포인트 (docs/api-spec.yaml 태그 단위)
    models.py          -- 이 모듈 소유 테이블만 (docs/data-model.md)
    schemas.py          -- Pydantic, api-spec.yaml과 1:1
    service.py           -- 비즈니스 로직 (docs/code-quality.md 기능형 코어 원칙)
    tests/
```

## DB 마이그레이션 — 체인은 하나

Alembic 히스토리는 저장소 전체에 하나다. 모듈마다 별도 체인을 만들지 않는다 — PR 올리기 전
`develop`을 받아서 마이그레이션 순서를 맞춘다. 충돌 나면 먼저 머지된 쪽이 우선.

## 모듈 간 접근 — 함수/API로만

`docs/architecture.md` 1절 원칙 그대로: 다른 모듈의 테이블(ORM 모델)을 직접 import·쿼리하지
않는다. 필요하면 그 모듈이 공개한 서비스 함수를 부르거나 API로 요청한다.

## 로컬 실행

- `pip install -r requirements.txt`, `.env.example`을 `.env`로 복사 후 값 채우기
- DB·Redis: `docker-compose up -d` (`backend/docker-compose.yml` — PostgreSQL+PostGIS, Redis)
- `uvicorn main:app --reload` — `backend/main.py`는 이미 있다. 각 모듈은 자기 `router.py`를 만들고
  `main.py`의 주석 처리된 `include_router` 줄만 풀면 된다(그 외엔 `main.py`를 건드리지 않는다)
- 마이그레이션: `alembic revision --autogenerate -m "..."` / `alembic upgrade head` — 모델을
  추가했으면 `alembic/env.py`에 그 모듈의 `models` import를 추가해야 Alembic이 인식한다
- 테스트: pytest, 모듈별 `tests/`

## 코드 품질

`docs/code-quality.md` 참고 — 기능형 코어/명령형 셸 분리는 여기 전체에 적용된다.
