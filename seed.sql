USE doctor_appointment_system;

INSERT INTO specialty (name) VALUES
('General Physician'),
('Pediatrics'),
('Dermatology'),
('Gynecology'),
('Orthopedics'),
('Cardiology'),
('Neurology'),
('Ophthalmology'),
('ENT'),
('Psychiatry'),
('Psychology'),
('Gastroenterology'),
('Nephrology'),
('Urology'),
('Pulmonology'),
('Endocrinology'),
('Oncology'),
('Rheumatology'),
('Dentistry'),
('Physiotherapy'),
('Nutrition'),
('Homeopathy'),
('Ayurveda'),
('General Surgery'),
('Plastic Surgery'),
('Vascular Surgery'),
('Spine'),
('Diabetology'),
('Pain Management');

INSERT INTO doctor (name, specialty_id, mode, fee, active, clinic_address) VALUES
('Dr. Asha Menon', (SELECT id FROM specialty WHERE name = 'Cardiology'), 'online', 800.00, 1, NULL),
('Dr. Rahul Verma', (SELECT id FROM specialty WHERE name = 'Cardiology'), 'offline', 850.00, 1, 'HCL Heart Clinic, 24 Lake View Road, City Center'),
('Dr. Meera Nair', (SELECT id FROM specialty WHERE name = 'Dermatology'), 'online', 650.00, 1, NULL),
('Dr. Sanjay Kulkarni', (SELECT id FROM specialty WHERE name = 'Dermatology'), 'offline', 700.00, 1, 'HCL Skin Clinic, 11 Green Park, City Center'),
('Dr. Priya Shah', (SELECT id FROM specialty WHERE name = 'General Physician'), 'online', 500.00, 1, NULL),
('Dr. Arjun Kapoor', (SELECT id FROM specialty WHERE name = 'General Physician'), 'offline', 550.00, 1, 'HCL General Clinic, 8 Central Avenue, City Center'),
('Dr. Neha Iyer', (SELECT id FROM specialty WHERE name = 'Pediatrics'), 'online', 600.00, 1, NULL),
('Dr. Vikram Joshi', (SELECT id FROM specialty WHERE name = 'Orthopedics'), 'offline', 900.00, 1, 'HCL Ortho Center, 90 Sports Complex Road, City Center'),
('Dr. Farah Khan', (SELECT id FROM specialty WHERE name = 'Gynecology'), 'offline', 750.00, 1, 'HCL Women Clinic, 44 Harmony Lane, City Center'),
('Dr. Anil Kumar', (SELECT id FROM specialty WHERE name = 'Psychology'), 'online', 700.00, 1, NULL);

INSERT INTO doctor_schedule (doctor_id, schedule_date, time_slot)
SELECT d.id, dates.schedule_date, slots.time_slot
FROM doctor d
JOIN (
    SELECT DATE('2026-04-08') AS schedule_date
    UNION ALL SELECT DATE('2026-04-09')
    UNION ALL SELECT DATE('2026-04-10')
) AS dates
JOIN (
    SELECT TIME('09:00:00') AS time_slot
    UNION ALL SELECT TIME('11:00:00')
    UNION ALL SELECT TIME('14:00:00')
) AS slots;
