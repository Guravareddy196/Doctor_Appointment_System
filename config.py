import os

from dotenv import load_dotenv


load_dotenv()


class Config:
	SECRET_KEY = os.getenv("SECRET_KEY", "doctor-appointment-system-dev-key")
	MYSQL_HOST = os.getenv("MYSQL_HOST", "localhost")
	MYSQL_PORT = int(os.getenv("MYSQL_PORT", "3306"))
	MYSQL_USER = os.getenv("MYSQL_USER", "root")
	MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "")
	MYSQL_DB = os.getenv("MYSQL_DB", "doctor_appointment_system")
	ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
	ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")

