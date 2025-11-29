-- MySQL setup script for FMP Cached provider
-- Run this script as MySQL root user

-- Create database
CREATE DATABASE IF NOT EXISTS openbb_fmp_cache 
CHARACTER SET utf8mb4 
COLLATE utf8mb4_unicode_ci;

-- Create user
CREATE USER IF NOT EXISTS 'fmp_user'@'localhost' IDENTIFIED BY 'fmp_password';

-- Grant all privileges on the database to the user
GRANT ALL PRIVILEGES ON openbb_fmp_cache.* TO 'fmp_user'@'localhost';

-- Flush privileges to ensure they take effect
FLUSH PRIVILEGES;

-- Show confirmation
SELECT 'Database and user created successfully!' as Status;

-- Show databases to confirm
SHOW DATABASES LIKE 'openbb_fmp_cache';

-- Show user to confirm
SELECT User, Host FROM mysql.user WHERE User = 'fmp_user';