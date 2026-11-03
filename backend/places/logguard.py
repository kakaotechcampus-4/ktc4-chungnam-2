"""호환용 — 접근 로그 가리기는 common/logguard.py로 옮겼다(#1201). 쿼리스트링을 경로와 무관하게 모두 지운다."""

from common.logguard import MaskRequestFilter, install, mask_request_target  # noqa: F401

# 옛 이름(#473) — 다른 브랜치가 import할 수 있어 남긴다. SENSITIVE_PATHS는 이제 쓰이지 않는다(모든 경로의 쿼리를 지운다).
StripQueryFilter = MaskRequestFilter
SENSITIVE_PATHS = ("/places/nearest",)
