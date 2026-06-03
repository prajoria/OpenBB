-- FMP Cached Provider Test Database Setup
-- Run as MySQL admin/root user

CREATE DATABASE IF NOT EXISTS openbb_fmp_cache_test;
GRANT ALL PRIVILEGES ON openbb_fmp_cache_test.* TO 'fmp_user'@'localhost';
FLUSH PRIVILEGES;

-- Verification
SHOW DATABASES;
SELECT User, Host FROM mysql.user WHERE User = 'fmp_user';
