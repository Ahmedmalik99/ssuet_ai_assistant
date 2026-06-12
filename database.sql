-- SSUET AI Assistant Database Schema
-- Run this in your MySQL database to create all required tables

CREATE DATABASE IF NOT EXISTS railway;
USE railway;

-- Users table
CREATE TABLE IF NOT EXISTS users (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    email VARCHAR(100) UNIQUE NOT NULL,
    phone VARCHAR(20),
    password_hash VARCHAR(255) NOT NULL,
    email_verified BOOLEAN DEFAULT FALSE,
    last_login DATETIME NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Add email_verified column to users (safe fallback for existing tables)
ALTER TABLE users ADD COLUMN IF NOT EXISTS email_verified BOOLEAN DEFAULT FALSE;

-- Chat sessions table
CREATE TABLE IF NOT EXISTS chat_sessions (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    session_name VARCHAR(255) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id)
);

-- Messages table
CREATE TABLE IF NOT EXISTS messages (
    id INT AUTO_INCREMENT PRIMARY KEY,
    session_id INT NOT NULL,
    sender ENUM('user', 'ai') NOT NULL,
    content TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (session_id) REFERENCES chat_sessions(id)
);

-- Leads table (for admissions tracking)
CREATE TABLE IF NOT EXISTS leads (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    name VARCHAR(100) NOT NULL,
    email VARCHAR(100) NOT NULL,
    phone VARCHAR(20),
    interest_program VARCHAR(100),
    status ENUM('new', 'contacted', 'converted') DEFAULT 'new',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id)
);

-- Feedback table
CREATE TABLE IF NOT EXISTS feedback (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    rating INT NOT NULL,
    category VARCHAR(50) DEFAULT 'general',
    comment TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id)
);

-- Tickets table (support system)
CREATE TABLE IF NOT EXISTS tickets (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    subject VARCHAR(255) NOT NULL,
    description TEXT NOT NULL,
    priority ENUM('low', 'medium', 'high') DEFAULT 'medium',
    status ENUM('open', 'in_progress', 'resolved') DEFAULT 'open',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id)
);

-- Faculty table
CREATE TABLE IF NOT EXISTS faculty (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    designation VARCHAR(100),
    department VARCHAR(100),
    email VARCHAR(100),
    specialization VARCHAR(255)
);

-- OTP Codes for Email Verification
CREATE TABLE IF NOT EXISTS otp_codes (
    id INT AUTO_INCREMENT PRIMARY KEY,
    email VARCHAR(100) NOT NULL,
    otp_code VARCHAR(6) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at DATETIME NOT NULL,
    used BOOLEAN DEFAULT FALSE,
    INDEX idx_email_otp (email, otp_code),
    INDEX idx_expires (expires_at)
);

-- Login Attempts Tracking (Brute Force / Account Lockout)
CREATE TABLE IF NOT EXISTS login_attempts (
    id INT AUTO_INCREMENT PRIMARY KEY,
    ip_address VARCHAR(45) NOT NULL,
    email VARCHAR(100) NOT NULL,
    attempted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_email_time (email, attempted_at),
    INDEX idx_ip_time (ip_address, attempted_at)
);

-- Blocked IP Addresses
CREATE TABLE IF NOT EXISTS blocked_ips (
    id INT AUTO_INCREMENT PRIMARY KEY,
    ip_address VARCHAR(45) NOT NULL UNIQUE,
    reason VARCHAR(255) DEFAULT 'Suspicious activity',
    blocked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at DATETIME NULL,
    INDEX idx_ip (ip_address),
    INDEX idx_expires (expires_at)
);

-- Admins table
CREATE TABLE IF NOT EXISTS admins (
    id INT AUTO_INCREMENT PRIMARY KEY,
    username VARCHAR(50) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    email VARCHAR(100) UNIQUE NOT NULL
);

-- Insert default admin (password: admin123)
INSERT IGNORE INTO admins (username, password_hash, email) 
VALUES ('admin', 
        '$2b$12$5LqBx6v3jZ6fY6u7v8w9x.y.z.A.B.C.D.E.F.G.H.I.J.K.L.M.N.O.P', 
        'admin@ssuet.edu.pk');

-- Insert sample faculty data (optional)
INSERT IGNORE INTO faculty (name, designation, department, email, specialization) 
VALUES 
('Dr. Farooq Ahmad', 'Dean', 'Electrical & Computer Engineering', 'farooq.ahmad@ssuet.edu.pk', 'Power Systems'),
('Dr. Salman Ahmed', 'Dean', 'Computing & Applied Sciences', 'salman.ahmad@ssuet.edu.pk', 'Artificial Intelligence'),
('Dr. Asma Khan', 'Dean', 'Civil Engineering & Architecture', 'asma.khan@ssuet.edu.pk', 'Structural Engineering'),
('Dr. Hassan Raza', 'Dean', 'Business Management & Social Science', 'hassan.raza@ssuet.edu.pk', 'Finance');

INSERT IGNORE INTO users (name, email, phone, password_hash) 
VALUES 
('Admin User', 'admin@ssuet.edu.pk', '0300-0000000', 
 '$2b$12$5LqBx6v3jZ6fY6u7v8w9x.y.z.A.B.C.D.E.F.G.H.I.J.K.L.M.N.O.P');
