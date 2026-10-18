-- ===============================
-- DROP TABLES (ORDER MATTERS)
-- ===============================

DROP TABLE IF EXISTS otps;
DROP TABLE IF EXISTS user_details;
DROP TABLE IF EXISTS admin_activity_log;
DROP TABLE IF EXISTS schemes;
DROP TABLE IF EXISTS user;


-- ===============================
-- USER TABLE
-- ===============================

CREATE TABLE user (
  id INT AUTO_INCREMENT PRIMARY KEY,
  username VARCHAR(100) UNIQUE NOT NULL,
  email VARCHAR(100) UNIQUE NOT NULL,
  password VARCHAR(200) NOT NULL,
  is_registered BOOLEAN DEFAULT FALSE,
  user_type VARCHAR(15) DEFAULT 'user'
);


-- ===============================
-- OTP TABLE
-- ===============================

CREATE TABLE otps (
  id INT AUTO_INCREMENT PRIMARY KEY,
  otp VARCHAR(100),
  created BIGINT,
  FOREIGN KEY (id) REFERENCES user(id) ON DELETE CASCADE
);


-- ===============================
-- USER DETAILS TABLE
-- ===============================

CREATE TABLE user_details (
  id INT AUTO_INCREMENT PRIMARY KEY,
  name VARCHAR(100),
  age INT,
  dob DATE,
  gender VARCHAR(100),
  income INT,
  caste VARCHAR(100),
  states VARCHAR(100),
  occupation VARCHAR(100),
  aadhar VARCHAR(100),
  pan VARCHAR(100),
  doc_type VARCHAR(20),
  doc_verified BOOLEAN DEFAULT FALSE,
  user_id INT,
  FOREIGN KEY (user_id) REFERENCES user(id) ON DELETE CASCADE
);


-- ===============================
-- SCHEMES TABLE
-- ===============================

CREATE TABLE schemes (
  id INT AUTO_INCREMENT PRIMARY KEY,
  title VARCHAR(200) NOT NULL,
  category VARCHAR(100),
  description TEXT,
  benefits TEXT,
  objectives TEXT,
  application_process TEXT,
  documents TEXT,
  min_age INT,
  max_age INT,
  max_income INT,
  gender VARCHAR(50),
  caste VARCHAR(50),
  state VARCHAR(100),
  occupation VARCHAR(100),
  eligibility TEXT,
  exclusions TEXT,
  faq TEXT,
  table_data TEXT,
  table_section VARCHAR(50) DEFAULT 'benefits',
  tags VARCHAR(255)
);


-- ===============================
-- ADMIN ACTIVITY LOG TABLE
-- ===============================

CREATE TABLE admin_activity_log (
  id INT AUTO_INCREMENT PRIMARY KEY,
  admin_name VARCHAR(100),
  action VARCHAR(100),
  detail TEXT,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
