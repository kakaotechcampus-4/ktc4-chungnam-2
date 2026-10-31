-- 처음 DB 볼륨을 만들 때 한 번만 돈다(postgis 이미지의 초기화 규칙). 확장(postgis)은 마이그레이션 0001이 만든다.
CREATE DATABASE pingo_prod;
CREATE DATABASE pingo_staging;
