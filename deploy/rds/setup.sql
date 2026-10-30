-- RDS 첫 설정(#873). 마스터(pingo_admin)로 한 번만 돈다 — rds-setup.sh가 부른다(deploy_rules.md 「RDS로 옮기기」).
-- 앱은 환경마다 전용 계정으로 붙는다. 마스터 비밀번호는 30일마다 바뀌지만 앱 계정은 바뀌지 않고, 운영과 스테이징 계정은
-- 서로의 DB를 열지 못한다. 확장은 앱 계정이 만들 수 없어 여기서 먼저 만든다(마이그레이션 0001, 0042는 IF NOT EXISTS라 지나간다).
-- 앱 계정 비밀번호는 환경 변수 PINGO_PROD_APP_PW, PINGO_STAGING_APP_PW에서 읽는다(명령 인자에 남지 않게). 값은 출력하지 않는다.
\set ON_ERROR_STOP on
\set QUIET on
\getenv prod_pw PINGO_PROD_APP_PW
\getenv staging_pw PINGO_STAGING_APP_PW

CREATE ROLE pingo_prod_app LOGIN PASSWORD :'prod_pw';
CREATE ROLE pingo_staging_app LOGIN PASSWORD :'staging_pw';
-- PostgreSQL 16부터 DB 소유자를 넘기려면 그 역할로 SET ROLE할 수 있어야 한다
GRANT pingo_prod_app TO pingo_admin WITH SET TRUE;
GRANT pingo_staging_app TO pingo_admin WITH SET TRUE;

ALTER DATABASE pingo_prod OWNER TO pingo_prod_app;
CREATE DATABASE pingo_staging OWNER pingo_staging_app;
-- 기본으로 PUBLIC에 열린 접속 권한을 닫는다 — 각 DB는 그 환경의 앱 계정(소유자)과 마스터만 붙는다
REVOKE ALL ON DATABASE pingo_prod FROM PUBLIC;
REVOKE ALL ON DATABASE pingo_staging FROM PUBLIC;

\connect pingo_prod
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
\unset QUIET
SELECT 'pingo_prod' AS db, postgis_full_version() AS postgis;

\connect pingo_staging
\set QUIET on
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
\unset QUIET
SELECT 'pingo_staging' AS db, postgis_full_version() AS postgis;
