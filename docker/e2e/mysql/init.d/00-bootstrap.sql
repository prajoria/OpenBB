-- docker/e2e/mysql/init.d/00-bootstrap.sql
--
-- Executed once by the mysql:8.4 entrypoint on first boot (before any
-- healthcheck passes). MYSQL_DATABASE / MYSQL_USER / MYSQL_PASSWORD
-- env vars already created `openbb_fmp_cache` and the `fmp_user` user;
-- here we add the _test schema and the grants on both DBs so the
-- extension's default read/write user works.
--
-- We deliberately do NOT restore the app data here — this file runs
-- with the whole 330MB dump inline it becomes slow and brittle. Data
-- restore is a separate step driven by ../restore_dump.sh.

CREATE DATABASE IF NOT EXISTS openbb_fmp_cache      CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE DATABASE IF NOT EXISTS openbb_fmp_cache_test CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

GRANT ALL PRIVILEGES ON openbb_fmp_cache.*      TO 'fmp_user'@'%';
GRANT ALL PRIVILEGES ON openbb_fmp_cache_test.* TO 'fmp_user'@'%';
FLUSH PRIVILEGES;
