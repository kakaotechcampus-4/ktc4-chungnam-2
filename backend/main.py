"""
FastAPI 앱 진입점. 단일 앱, 마이크로서비스 아님(backend/CLAUDE.md 참고).

각 backend/<module>/이 자기 router.py를 만들면 아래 주석을 풀고 등록한다.
이 파일 자체를 수정하는 건 라우터 등록뿐 — 비즈니스 로직은 각 모듈에 둔다.
"""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware

from common.adapters import format_assembly
from common.errors import register_error_handlers
from common.settings import settings
from realtime.dispatcher import dispatcher

logger = logging.getLogger("pingo")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # 서버가 어떤 조립(dev 스텁 vs 실구현)으로 떴는지 기동 로그 한 곳에서 보인다.
    logger.info("\n%s", format_assembly())
    # 반드시 이 순서로: 이미 있는 event_log까지 따라잡은 뒤(동기, 한 번) 폴링 루프를 시작한다.
    dispatcher.initialize_last_seen()
    task = asyncio.create_task(dispatcher.run_forever())
    yield
    task.cancel()


app = FastAPI(title="pingo API", version="0.1.0", lifespan=lifespan)

# 모든 응답을 {code, message, detail?} 한 봉투로 통일한다(backend/common/errors.py, #2).
register_error_handlers(app)


@app.get("/health")
def health():
    return {"status": "ok"}


# 모듈 담당자가 router.py를 만들면 여기 등록한다. docs/api-spec.yaml 태그 = 모듈 단위.
# from auth.router import router as auth_router
# from maps.router import router as maps_router
from pins.router import router as pins_router  # noqa: E402
from realtime.router import router as realtime_router  # noqa: E402

# from recommend.router import router as recommend_router
# from shortlist.router import router as shortlist_router
#
# app.include_router(auth_router)
# app.include_router(maps_router)
app.include_router(pins_router)
# app.include_router(recommend_router)
# app.include_router(shortlist_router)
app.include_router(realtime_router)

# CORS는 add_middleware가 아니라 앱을 "바깥에서" 감싼다.
# add_middleware로 넣으면 CORS가 ServerErrorMiddleware 안쪽이 돼서 500 응답에 CORS 헤더가
# 안 붙는다(브라우저 FE가 500 본문을 못 읽는다). 바깥에서 감싸면 안에서 만들어진 500에도 붙는다.
# CORSMiddleware는 순수 ASGI라 body 청크를 건드리지 않는다 — SSE(#13) 스트리밍에 영향 없다.
#
#   실행: uvicorn main:asgi_app --reload   (main:app 아니다)
#   테스트에서 CORS를 보려면 TestClient(asgi_app), 라우터/의존성만 보면 TestClient(app).
asgi_app = CORSMiddleware(
    app,
    allow_origins=list(settings.cors_allow_origins),
    allow_origin_regex=settings.cors_allow_origin_regex,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
