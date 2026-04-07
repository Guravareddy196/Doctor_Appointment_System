# Doctor Appointment System

Flask + MySQL mini project with role-based views for patients, doctors, and admin.

## Features

- Patient registration/login and booking history.
- Doctor registration/login and accept/reject for booked appointments.
- Admin login with manage appointments and revenue summary.
- Mode-aware booking (online vs offline doctors), transactional slot locking, and double-booking prevention.

## Run Steps

1. Import database schema:
	- Open [schema.sql](schema.sql) in MySQL Workbench and execute.
2. Seed sample data:
	- Open [seed.sql](seed.sql) in MySQL Workbench and execute.
3. Install packages:
	- `pip install -r requirements.txt`
4. Create [.env](.env) from [.env.example](.env.example) and set your MySQL password.
5. Start app:
	- `python app.py`
6. Open:
	- `http://127.0.0.1:5000/`

## Important Routes

- Public: `/`, `/patient/register`, `/patient/login`, `/doctor/register`, `/doctor/login`, `/admin/login`
- Patient-only: `/specialties`, `/book`, `/my-appointments`
- Doctor-only: `/doctor/appointments`
- Admin-only: `/appointments`, `/summary`

