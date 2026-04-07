CREATE DATABASE IF NOT EXISTS doctor_appointment_system;
USE doctor_appointment_system;

SET FOREIGN_KEY_CHECKS = 0;
DROP TABLE IF EXISTS appointment;
DROP TABLE IF EXISTS doctor_schedule;
DROP TABLE IF EXISTS patient;
DROP TABLE IF EXISTS doctor;
DROP TABLE IF EXISTS specialty;
SET FOREIGN_KEY_CHECKS = 1;

CREATE TABLE specialty (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(120) NOT NULL UNIQUE
) ENGINE=InnoDB;

CREATE TABLE doctor (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(150) NOT NULL,
    username VARCHAR(80) NULL,
    password_hash VARCHAR(255) NULL,
    email VARCHAR(150) NULL,
    phone VARCHAR(20) NULL,
    specialty_id INT NOT NULL,
    mode VARCHAR(10) NOT NULL,
    fee DECIMAL(10, 2) NOT NULL,
    active TINYINT(1) NOT NULL DEFAULT 1,
    clinic_address VARCHAR(255) NULL,
    CONSTRAINT chk_doctor_mode CHECK (mode IN ('online', 'offline')),
    CONSTRAINT fk_doctor_specialty FOREIGN KEY (specialty_id) REFERENCES specialty (id),
    INDEX idx_doctor_specialty_id (specialty_id),
    INDEX idx_doctor_mode (mode),
    INDEX idx_doctor_active (active),
    UNIQUE KEY uq_doctor_username (username),
    UNIQUE KEY uq_doctor_email (email)
) ENGINE=InnoDB;

CREATE TABLE patient (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(150) NOT NULL,
    contact VARCHAR(20) NOT NULL,
    dob DATE NOT NULL,
    email VARCHAR(150) NOT NULL,
    password_hash VARCHAR(255) NULL,
    UNIQUE KEY uq_patient_contact (contact),
    UNIQUE KEY uq_patient_email (email),
    INDEX idx_patient_email (email)
) ENGINE=InnoDB;

CREATE TABLE doctor_schedule (
    id INT AUTO_INCREMENT PRIMARY KEY,
    doctor_id INT NOT NULL,
    schedule_date DATE NOT NULL,
    time_slot TIME NOT NULL,
    booked_flag TINYINT(1) NOT NULL DEFAULT 0,
    CONSTRAINT fk_schedule_doctor FOREIGN KEY (doctor_id) REFERENCES doctor (id) ON DELETE CASCADE,
    CONSTRAINT uq_schedule_doctor_date_time UNIQUE (doctor_id, schedule_date, time_slot),
    INDEX idx_schedule_doctor_id (doctor_id),
    INDEX idx_schedule_date (schedule_date),
    INDEX idx_schedule_booked_flag (booked_flag)
) ENGINE=InnoDB;

CREATE TABLE appointment (
    id INT AUTO_INCREMENT PRIMARY KEY,
    patient_id INT NOT NULL,
    doctor_id INT NOT NULL,
    mode VARCHAR(10) NOT NULL,
    appointment_date DATE NOT NULL,
    appointment_time TIME NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'confirmed',
    doctor_decision VARCHAR(20) NOT NULL DEFAULT 'pending',
    fee DECIMAL(10, 2) NOT NULL,
    video_link VARCHAR(255) NULL,
    clinic_address VARCHAR(255) NULL,
    instructions VARCHAR(255) NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT fk_appointment_patient FOREIGN KEY (patient_id) REFERENCES patient (id),
    CONSTRAINT fk_appointment_doctor FOREIGN KEY (doctor_id) REFERENCES doctor (id),
    CONSTRAINT chk_appointment_mode CHECK (mode IN ('online', 'offline')),
    CONSTRAINT chk_appointment_status CHECK (status IN ('confirmed', 'completed', 'cancelled', 'no-show')),
    CONSTRAINT chk_doctor_decision CHECK (doctor_decision IN ('pending', 'accepted', 'rejected')),
    INDEX idx_appointment_doctor_id (doctor_id),
    INDEX idx_appointment_mode (mode),
    INDEX idx_appointment_status (status),
    INDEX idx_appointment_date (appointment_date),
    INDEX idx_appointment_date_mode (appointment_date, mode)
) ENGINE=InnoDB;
