# places/assets

- `face_detection_yunet_2023mar.onnx`: YuNet 얼굴 검출 모델(232,589바이트). 블로그 사진에서 사람 얼굴이 보이는 사진을 뺄 때 쓴다(`places/photos.py`, #1157).
  - 출처: OpenCV Zoo `models/face_detection_yunet/face_detection_yunet_2023mar.onnx` (https://github.com/opencv/opencv_zoo)
  - 라이선스: MIT License, Copyright (c) 2020 Shiqi Yu
  - 바꾸려면 같은 이름으로 덮어쓰고 `places/tests/test_photos_1157.py`를 돌린다.
