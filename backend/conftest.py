import os

# 테스트는 항상 test 환경이다. common.settings import보다 먼저 정해져야 해서 루트 conftest에 둔다.
# setdefault가 아니라 강제로 덮어쓴다 — 개발자 셸에 PINGO_ENV=prod가 남아있으면(예: 배포
# 스크립트를 돌리고 같은 터미널에서 바로 테스트를 돌리는 경우) setdefault는 그 값을 그대로
# 두어 테스트가 prod 가드에 걸려 깨진다(DeepSeek 검수 지적). 테스트는 셸 환경과 무관하게
# 항상 test여야 한다.
os.environ["PINGO_ENV"] = "test"
