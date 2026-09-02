"""
FastAPI 앱 진입점. 단일 앱, 마이크로서비스 아님(backend/CLAUDE.md 참고).

각 backend/<module>/이 자기 router.py를 만들면 아래 주석을 풀고 등록한다.
이 파일 자체를 수정하는 건 라우터 등록뿐 — 비즈니스 로직은 각 모듈에 둔다.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="pingo API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # TODO: 배포 전 프론트 도메인으로 제한
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok"}


# 모듈 담당자가 router.py를 만들면 여기 등록한다. docs/api-spec.yaml 태그 = 모듈 단위.
# from auth.router import router as auth_router
# from maps.router import router as maps_router
# from pins.router import router as pins_router
# from recommend.router import router as recommend_router
# from shortlist.router import router as shortlist_router
# from realtime.router import router as realtime_router
#
# app.include_router(auth_router)
# app.include_router(maps_router)
# app.include_router(pins_router)
# app.include_router(recommend_router)
# app.include_router(shortlist_router)
# app.include_router(realtime_router)
