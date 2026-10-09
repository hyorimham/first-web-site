-- 데이터베이스가 없으면 생성하고 사용 (문자가 깨지지 않도록 utf8mb4 설정)
CREATE DATABASE IF NOT EXISTS community DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE community;

-- 1. 사용자(users) 테이블 생성
CREATE TABLE IF NOT EXISTS users (
    id INT AUTO_INCREMENT PRIMARY KEY,
    username VARCHAR(50) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 2. 게시글(posts) 테이블 생성
CREATE TABLE IF NOT EXISTS posts (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    title VARCHAR(200) NOT NULL,
    content TEXT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 테스트용 기본 사용자 데이터 하나 넣어두기 (로그인 기능 만들기 전 테스트용)
INSERT INTO users (id, username, password_hash) 
VALUES (1, 'admin', 'scrypt:32768:8:1$default_hash_for_test')
ON DUPLICATE KEY UPDATE id=id;