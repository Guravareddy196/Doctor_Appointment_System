from datetime import date as date_class
from datetime import datetime, timedelta
from functools import wraps

from flask import Flask, flash, redirect, render_template, request, session, url_for
from mysql.connector import Error, IntegrityError
from werkzeug.security import check_password_hash, generate_password_hash

from config import Config
from db import fetch_all, fetch_one, get_connection


app = Flask(__name__)
app.config.from_object(Config)
app.secret_key = Config.SECRET_KEY

ALLOWED_MODES = ("online", "offline")
ALLOWED_STATUSES = ("confirmed", "completed", "cancelled", "no-show")
TERMINAL_STATUSES = ("completed", "cancelled", "no-show")
ALLOWED_DOCTOR_DECISIONS = ("pending", "accepted", "rejected")
OFFLINE_INSTRUCTIONS = "Please arrive 15 minutes early and carry previous reports."
DEFAULT_CLINIC_ADDRESS = "HCL Clinic, Main Road, City Center"


def admin_login_required(view_function):
    @wraps(view_function)
    def wrapped_view(*args, **kwargs):
        if not session.get("is_admin"):
            flash("Admin login is required to access this page.", "warning")
            return redirect(url_for("admin_login", next=request.path))
        return view_function(*args, **kwargs)

    return wrapped_view


def patient_login_required(view_function):
    @wraps(view_function)
    def wrapped_view(*args, **kwargs):
        if not session.get("patient_id"):
            flash("Patient login is required to access this page.", "warning")
            return redirect(url_for("patient_login", next=request.path))
        return view_function(*args, **kwargs)

    return wrapped_view


def doctor_login_required(view_function):
    @wraps(view_function)
    def wrapped_view(*args, **kwargs):
        if not session.get("doctor_id"):
            flash("Doctor login is required to access this page.", "warning")
            return redirect(url_for("doctor_login", next=request.path))
        return view_function(*args, **kwargs)

    return wrapped_view


def normalize_mode(value):
    if value is None:
        return ""
    return str(value).strip().lower()


def safe_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def normalize_time_input(value):
    if not value:
        return ""
    value = str(value).strip()
    if len(value) == 5:
        return f"{value}:00"
    return value


def display_time(value):
    if value is None:
        return ""
    if isinstance(value, timedelta):
        total_seconds = int(value.total_seconds())
        hours, remainder = divmod(total_seconds, 3600)
        minutes = remainder // 60
        return f"{hours:02d}:{minutes:02d}"
    if hasattr(value, "strftime"):
        return value.strftime("%H:%M")
    text = str(value)
    return text[:5] if len(text) >= 5 else text


def display_date(value):
    if value is None:
        return ""
    if hasattr(value, "strftime"):
        return value.strftime("%Y-%m-%d")
    return str(value)


@app.template_filter("display_time")
def display_time_filter(value):
    return display_time(value)


@app.template_filter("display_date")
def display_date_filter(value):
    return display_date(value)


def get_specialties():
    return fetch_all("SELECT id, name FROM specialty ORDER BY name")


def ensure_patient_auth_column():
    connection = get_connection()
    cursor = connection.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT COUNT(*) AS column_count
            FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = %s
              AND TABLE_NAME = 'patient'
              AND COLUMN_NAME = 'password_hash'
            """,
            (Config.MYSQL_DB,),
        )
        row = cursor.fetchone()
        if row and row["column_count"] == 0:
            cursor.execute("ALTER TABLE patient ADD COLUMN password_hash VARCHAR(255) NULL AFTER email")
            connection.commit()
    finally:
        cursor.close()
        connection.close()


def ensure_doctor_auth_columns():
    connection = get_connection()
    cursor = connection.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT COLUMN_NAME
            FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = %s
              AND TABLE_NAME = 'doctor'
              AND COLUMN_NAME IN ('username', 'password_hash', 'email', 'phone')
            """,
            (Config.MYSQL_DB,),
        )
        existing = {row["COLUMN_NAME"] for row in cursor.fetchall()}

        if "username" not in existing:
            cursor.execute("ALTER TABLE doctor ADD COLUMN username VARCHAR(80) NULL AFTER name")
            cursor.execute("CREATE UNIQUE INDEX uq_doctor_username ON doctor (username)")

        if "password_hash" not in existing:
            cursor.execute("ALTER TABLE doctor ADD COLUMN password_hash VARCHAR(255) NULL AFTER username")

        if "email" not in existing:
            cursor.execute("ALTER TABLE doctor ADD COLUMN email VARCHAR(150) NULL AFTER password_hash")

        if "phone" not in existing:
            cursor.execute("ALTER TABLE doctor ADD COLUMN phone VARCHAR(20) NULL AFTER email")

        cursor.execute(
            """
            SELECT COUNT(*) AS idx_count
            FROM information_schema.STATISTICS
            WHERE TABLE_SCHEMA = %s
              AND TABLE_NAME = 'doctor'
              AND INDEX_NAME = 'uq_doctor_email'
            """,
            (Config.MYSQL_DB,),
        )
        idx_row = cursor.fetchone()
        if idx_row and idx_row["idx_count"] == 0:
            cursor.execute("CREATE UNIQUE INDEX uq_doctor_email ON doctor (email)")

        connection.commit()
    finally:
        cursor.close()
        connection.close()


def ensure_appointment_doctor_decision_column():
    connection = get_connection()
    cursor = connection.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT COUNT(*) AS column_count
            FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = %s
              AND TABLE_NAME = 'appointment'
              AND COLUMN_NAME = 'doctor_decision'
            """,
            (Config.MYSQL_DB,),
        )
        row = cursor.fetchone()
        if row and row["column_count"] == 0:
            cursor.execute(
                "ALTER TABLE appointment ADD COLUMN doctor_decision VARCHAR(20) NOT NULL DEFAULT 'pending' AFTER status"
            )
            connection.commit()
    finally:
        cursor.close()
        connection.close()


def ensure_doctor_schedule_mode_column():
    connection = get_connection()
    cursor = connection.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT COUNT(*) AS column_count
            FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = %s
              AND TABLE_NAME = 'doctor_schedule'
              AND COLUMN_NAME = 'mode'
            """,
            (Config.MYSQL_DB,),
        )
        row = cursor.fetchone()
        if row and row["column_count"] == 0:
            cursor.execute("ALTER TABLE doctor_schedule ADD COLUMN mode VARCHAR(10) NOT NULL DEFAULT 'offline' AFTER time_slot")
            cursor.execute(
                """
                UPDATE doctor_schedule ds
                INNER JOIN doctor d ON d.id = ds.doctor_id
                SET ds.mode = d.mode
                """
            )
            connection.commit()
    finally:
        cursor.close()
        connection.close()


def ensure_doctor_schedule_mode_column():
    connection = get_connection()
    cursor = connection.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT COUNT(*) AS column_count
            FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = %s
              AND TABLE_NAME = 'doctor_schedule'
              AND COLUMN_NAME = 'mode'
            """,
            (Config.MYSQL_DB,),
        )
        row = cursor.fetchone()
        if row and row["column_count"] == 0:
            cursor.execute("ALTER TABLE doctor_schedule ADD COLUMN mode VARCHAR(10) NOT NULL DEFAULT 'offline' AFTER time_slot")
            cursor.execute(
                """
                UPDATE doctor_schedule ds
                INNER JOIN doctor d ON d.id = ds.doctor_id
                SET ds.mode = d.mode
                """
            )
            connection.commit()
    finally:
        cursor.close()
        connection.close()


def get_logged_in_patient():
    patient_id = session.get("patient_id")
    if not patient_id:
        return None
    return fetch_one(
        """
        SELECT id, name, contact, dob, email
        FROM patient
        WHERE id = %s
        """,
        (patient_id,),
    )


def get_doctors(mode=None, specialty_id=None, active_only=True):
    query = [
        "SELECT d.id, d.name, d.mode, d.fee, d.active, d.clinic_address, s.name AS specialty_name",
        "FROM doctor d",
        "INNER JOIN specialty s ON s.id = d.specialty_id",
        "WHERE 1 = 1",
    ]
    params = []
    if active_only:
        query.append("AND d.active = 1")
    if mode:
        query.append("AND d.mode = %s")
        params.append(mode)
    if specialty_id:
        query.append("AND d.specialty_id = %s")
        params.append(specialty_id)
    query.append("ORDER BY d.name")
    return fetch_all("\n".join(query), params)


def get_available_slots(doctor_id, appointment_date):
    return fetch_all(
        """
        SELECT id, time_slot
        FROM doctor_schedule
        WHERE doctor_id = %s
          AND schedule_date = %s
          AND booked_flag = 0
        ORDER BY time_slot
        """,
        (doctor_id, appointment_date),
    )


def prepare_booking_context(form_values=None, errors=None):
    values = form_values or {}
    logged_in_patient = get_logged_in_patient()
    if logged_in_patient:
        values = dict(values)
        values.setdefault("patient_name", logged_in_patient["name"])
        values.setdefault("patient_contact", logged_in_patient["contact"])
        values.setdefault("patient_email", logged_in_patient["email"])
        if logged_in_patient.get("dob"):
            values.setdefault("patient_dob", display_date(logged_in_patient["dob"]))

    mode = normalize_mode(values.get("mode"))
    specialty_id = safe_int(values.get("specialty_id"))
    doctor_id = safe_int(values.get("doctor_id"))
    appointment_date = values.get("appointment_date", "")

    specialties = get_specialties()
    doctors = []
    slots = []

    if mode in ALLOWED_MODES and specialty_id:
        doctors = get_doctors(mode=mode, specialty_id=specialty_id)
    if doctor_id and appointment_date:
        slots = get_available_slots(doctor_id, appointment_date)

    return {
        "specialties": specialties,
        "doctors": doctors,
        "slots": slots,
        "selected_mode": mode,
        "selected_specialty_id": specialty_id,
        "selected_doctor_id": doctor_id,
        "selected_date": appointment_date,
        "form_values": values,
        "errors": errors or {},
        "allowed_modes": ALLOWED_MODES,
        "allowed_statuses": ALLOWED_STATUSES,
    }


def validate_booking_form(form):
    errors = {}
    data = {
        "mode": normalize_mode(form.get("mode")),
        "specialty_id": safe_int(form.get("specialty_id")),
        "doctor_id": safe_int(form.get("doctor_id")),
        "appointment_date": form.get("appointment_date", "").strip(),
        "appointment_time": normalize_time_input(form.get("appointment_time", "")),
        "patient_name": form.get("patient_name", "").strip(),
        "patient_contact": form.get("patient_contact", "").strip(),
        "patient_dob": form.get("patient_dob", "").strip(),
        "patient_email": form.get("patient_email", "").strip(),
    }
    required_fields = {
        "mode": "Appointment mode is required.",
        "specialty_id": "Specialty is required.",
        "doctor_id": "Doctor is required.",
        "appointment_date": "Appointment date is required.",
        "appointment_time": "Appointment time is required.",
        "patient_name": "Patient name is required.",
        "patient_contact": "Patient contact is required.",
        "patient_dob": "Patient date of birth is required.",
        "patient_email": "Patient email is required.",
    }
    for key, message in required_fields.items():
        if not data[key]:
            errors[key] = message
    if data["mode"] and data["mode"] not in ALLOWED_MODES:
        errors["mode"] = "Mode must be either Online or Offline."
    if data["patient_email"] and "@" not in data["patient_email"]:
        errors["patient_email"] = "Enter a valid email address."
    if data["appointment_date"]:
        try:
            appointment_date = datetime.strptime(data["appointment_date"], "%Y-%m-%d").date()
            if appointment_date < date_class.today():
                errors["appointment_date"] = "Appointment date cannot be in the past."
        except ValueError:
            errors["appointment_date"] = "Enter a valid appointment date."
    if data["patient_dob"]:
        try:
            datetime.strptime(data["patient_dob"], "%Y-%m-%d")
        except ValueError:
            errors["patient_dob"] = "Enter a valid date of birth."
    if data["appointment_time"]:
        try:
            datetime.strptime(data["appointment_time"], "%H:%M:%S")
        except ValueError:
            errors["appointment_time"] = "Enter a valid appointment time."
    return data, errors


def get_or_create_patient(connection, patient_name, patient_contact, patient_dob, patient_email):
    cursor = connection.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT id
            FROM patient
            WHERE contact = %s OR email = %s
            LIMIT 1
            FOR UPDATE
            """,
            (patient_contact, patient_email),
        )
        existing_patient = cursor.fetchone()
        if existing_patient:
            cursor.execute(
                """
                UPDATE patient
                SET name = %s, contact = %s, dob = %s, email = %s
                WHERE id = %s
                """,
                (patient_name, patient_contact, patient_dob, patient_email, existing_patient["id"]),
            )
            return existing_patient["id"]

        cursor.execute(
            """
            INSERT INTO patient (name, contact, dob, email)
            VALUES (%s, %s, %s, %s)
            """,
            (patient_name, patient_contact, patient_dob, patient_email),
        )
        return cursor.lastrowid
    finally:
        cursor.close()


@app.route("/")
def home():
    home_stats = {"patients": 0, "doctors": 0, "specialties": 0, "appointments": 0}
    try:
        patients_row = fetch_one("SELECT COUNT(*) AS total FROM patient")
        doctors_row = fetch_one("SELECT COUNT(*) AS total FROM doctor WHERE active = 1")
        specialties_row = fetch_one("SELECT COUNT(*) AS total FROM specialty")
        appointments_row = fetch_one("SELECT COUNT(*) AS total FROM appointment")

        home_stats["patients"] = patients_row["total"] if patients_row else 0
        home_stats["doctors"] = doctors_row["total"] if doctors_row else 0
        home_stats["specialties"] = specialties_row["total"] if specialties_row else 0
        home_stats["appointments"] = appointments_row["total"] if appointments_row else 0
    except Error:
        # Keep dashboard visible even if DB is temporarily unavailable.
        pass

    return render_template("home.html", home_stats=home_stats)


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    next_url = request.args.get("next") or request.form.get("next") or url_for("appointments")
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        if username == Config.ADMIN_USERNAME and password == Config.ADMIN_PASSWORD:
            session.pop("patient_id", None)
            session.pop("patient_name", None)
            session.pop("doctor_id", None)
            session.pop("doctor_name", None)
            session["is_admin"] = True
            session["admin_username"] = username
            flash("Admin login successful.", "success")
            if not next_url.startswith("/"):
                next_url = url_for("appointments")
            return redirect(next_url)
        flash("Invalid admin credentials.", "danger")
    return render_template("admin_login.html", next_url=next_url)


@app.route("/admin/logout")
def admin_logout():
    session.pop("is_admin", None)
    session.pop("admin_username", None)
    flash("Admin logged out successfully.", "success")
    return redirect(url_for("home"))


@app.route("/doctor/register", methods=["GET", "POST"])
def doctor_register():
    ensure_doctor_auth_columns()
    errors = {}
    form_values = {}
    specialties = get_specialties()
    if request.method == "POST":
        form_values = {
            "specialty_id": request.form.get("specialty_id", "").strip(),
            "doctor_name": request.form.get("doctor_name", "").strip(),
            "email": request.form.get("email", "").strip(),
            "phone": request.form.get("phone", "").strip(),
        }
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")
        specialty_id = safe_int(form_values["specialty_id"])
        if specialty_id is None:
            errors["specialty_id"] = "Please select specialization."
        if not form_values["doctor_name"]:
            errors["doctor_name"] = "Doctor name is required."
        if not form_values["email"] or "@" not in form_values["email"]:
            errors["email"] = "Valid email is required."
        if not form_values["phone"]:
            errors["phone"] = "Phone is required."
        if len(password) < 6:
            errors["password"] = "Password must be at least 6 characters."
        if password != confirm_password:
            errors["confirm_password"] = "Password and confirm password must match."
        if not errors:
            connection = get_connection()
            cursor = connection.cursor(dictionary=True)
            try:
                connection.start_transaction()
                cursor.execute(
                    "SELECT id FROM doctor WHERE email = %s LIMIT 1 FOR UPDATE",
                    (form_values["email"],),
                )
                existing_email = cursor.fetchone()
                if existing_email:
                    errors["email"] = "Email is already in use."
                    raise ValueError

                cursor.execute(
                    """
                    INSERT INTO doctor (
                        name,
                        username,
                        password_hash,
                        email,
                        phone,
                        specialty_id,
                        mode,
                        fee,
                        active,
                        clinic_address
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, 'offline', 500.00, 1, %s)
                    """,
                    (
                        form_values["doctor_name"],
                        form_values["email"],
                        generate_password_hash(password),
                        form_values["email"],
                        form_values["phone"],
                        specialty_id,
                        DEFAULT_CLINIC_ADDRESS,
                    ),
                )
                connection.commit()
                flash("Doctor registration successful. Please login.", "success")
                return redirect(url_for("doctor_login"))
            except (ValueError, Error, IntegrityError):
                connection.rollback()
            finally:
                cursor.close()
                connection.close()
    return render_template("doctor_register.html", specialties=specialties, errors=errors, form_values=form_values)


@app.route("/doctor/login", methods=["GET", "POST"])
def doctor_login():
    ensure_doctor_auth_columns()
    ensure_appointment_doctor_decision_column()
    next_url = request.args.get("next") or request.form.get("next") or url_for("doctor_appointments")
    form_values = {}
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        form_values["username"] = username
        doctor = fetch_one(
            """SELECT id, name, username, password_hash FROM doctor WHERE username = %s AND active = 1 LIMIT 1""",
            (username,),
        )
        if not doctor or not doctor.get("password_hash") or not check_password_hash(doctor["password_hash"], password):
            flash("Invalid doctor credentials.", "danger")
            return render_template("doctor_login.html", next_url=next_url, form_values=form_values)
        session.pop("is_admin", None)
        session.pop("admin_username", None)
        session.pop("patient_id", None)
        session.pop("patient_name", None)
        session["doctor_id"] = doctor["id"]
        session["doctor_name"] = doctor["name"]
        flash("Doctor login successful.", "success")
        if not next_url.startswith("/"):
            next_url = url_for("doctor_appointments")
        return redirect(next_url)
    return render_template("doctor_login.html", next_url=next_url, form_values=form_values)


@app.route("/doctor/logout")
def doctor_logout():
    session.pop("doctor_id", None)
    session.pop("doctor_name", None)
    flash("Doctor logged out successfully.", "success")
    return redirect(url_for("home"))


@app.route("/doctor/appointments")
@doctor_login_required
def doctor_appointments():
    ensure_appointment_doctor_decision_column()
    ensure_doctor_schedule_mode_column()
    doctor_id = session.get("doctor_id")
    doctor_profile = fetch_one(
        """
        SELECT id, name, mode, clinic_address
        FROM doctor
        WHERE id = %s
        LIMIT 1
        """,
        (doctor_id,),
    )
    appointment_rows = fetch_all(
        """
        SELECT a.id, a.appointment_date, a.appointment_time, a.mode, a.status, a.doctor_decision, a.fee,
               p.name AS patient_name, p.contact AS patient_contact, p.email AS patient_email, s.name AS specialty_name
        FROM appointment a
        INNER JOIN patient p ON p.id = a.patient_id
        INNER JOIN doctor d ON d.id = a.doctor_id
        INNER JOIN specialty s ON s.id = d.specialty_id
        WHERE a.doctor_id = %s
        ORDER BY a.appointment_date DESC, a.appointment_time DESC, a.id DESC
        """,
        (doctor_id,),
    )
    start_date = date_class.today()
    end_date = start_date + timedelta(days=6)
    schedule_rows = fetch_all(
        """
                SELECT schedule_date, time_slot, booked_flag, mode
        FROM doctor_schedule
        WHERE doctor_id = %s
          AND schedule_date BETWEEN %s AND %s
        ORDER BY schedule_date, time_slot
        """,
        (doctor_id, start_date, end_date),
    )
    schedule_map = {}
    for row in schedule_rows:
        date_key = display_date(row["schedule_date"])
        schedule_map.setdefault(date_key, []).append(row)

    availability_days = []
    for offset in range(7):
        day_value = start_date + timedelta(days=offset)
        date_key = display_date(day_value)
        slots = []
        for slot in schedule_map.get(date_key, []):
            slot_value = slot["time_slot"]
            if hasattr(slot_value, "strftime"):
                slot_value = slot_value.strftime("%H:%M:%S")
            else:
                slot_value = normalize_time_input(slot_value)
            slots.append(
                {
                    "time_display": display_time(slot["time_slot"]),
                    "time_value": slot_value,
                    "booked_flag": int(slot["booked_flag"]),
                    "mode": normalize_mode(slot.get("mode")) or "offline",
                }
            )
        availability_days.append(
            {
                "date": date_key,
                "label": day_value.strftime("%A, %d %b %Y"),
                "slots": slots,
            }
        )

    return render_template(
        "doctor_appointments.html",
        appointments=appointment_rows,
        doctor_profile=doctor_profile,
        availability_days=availability_days,
        terminal_statuses=TERMINAL_STATUSES,
    )


@app.route("/doctor/appointments/decision/<int:appointment_id>", methods=["POST"])
@doctor_login_required
def doctor_appointment_decision(appointment_id):
    ensure_appointment_doctor_decision_column()
    decision = normalize_mode(request.form.get("decision"))
    if decision not in ("accepted", "rejected"):
        flash("Invalid decision.", "danger")
        return redirect(url_for("doctor_appointments"))
    doctor_id = session.get("doctor_id")
    connection = get_connection()
    cursor = connection.cursor(dictionary=True)
    try:
        connection.start_transaction()
        cursor.execute(
            """
            SELECT id, doctor_id, appointment_date, appointment_time, status, doctor_decision
            FROM appointment
            WHERE id = %s AND doctor_id = %s
            FOR UPDATE
            """,
            (appointment_id, doctor_id),
        )
        appointment = cursor.fetchone()
        if not appointment:
            flash("Appointment not found for this doctor.", "danger")
            connection.rollback()
            return redirect(url_for("doctor_appointments"))
        if appointment["status"] == "cancelled":
            flash("This appointment is already cancelled.", "warning")
            connection.rollback()
            return redirect(url_for("doctor_appointments"))
        if decision == "accepted":
            cursor.execute("UPDATE appointment SET doctor_decision = 'accepted', updated_at = CURRENT_TIMESTAMP WHERE id = %s", (appointment_id,))
            flash("Appointment accepted.", "success")
        else:
            cursor.execute(
                "UPDATE appointment SET doctor_decision = 'rejected', status = 'cancelled', updated_at = CURRENT_TIMESTAMP WHERE id = %s",
                (appointment_id,),
            )
            cursor.execute(
                """
                UPDATE doctor_schedule
                SET booked_flag = 0
                WHERE doctor_id = %s
                  AND schedule_date = %s
                  AND time_slot = %s
                """,
                (doctor_id, appointment["appointment_date"], appointment["appointment_time"]),
            )
            flash("Appointment rejected and slot released.", "success")
        connection.commit()
    except Error:
        connection.rollback()
        flash("Unable to update appointment decision.", "danger")
    finally:
        cursor.close()
        connection.close()
    return redirect(url_for("doctor_appointments"))


@app.route("/doctor/availability/add", methods=["POST"])
@doctor_login_required
def doctor_add_availability():
    ensure_doctor_schedule_mode_column()
    doctor_id = session.get("doctor_id")
    schedule_date = request.form.get("schedule_date", "").strip()
    time_slot = normalize_time_input(request.form.get("time_slot", "").strip())
    slot_mode = normalize_mode(request.form.get("mode"))
    if slot_mode not in ALLOWED_MODES:
        flash("Select a valid mode for this slot.", "danger")
        return redirect(url_for("doctor_appointments"))

    try:
        parsed_date = datetime.strptime(schedule_date, "%Y-%m-%d").date()
    except ValueError:
        flash("Select a valid availability date.", "danger")
        return redirect(url_for("doctor_appointments"))

    if parsed_date < date_class.today():
        flash("Availability date cannot be in the past.", "danger")
        return redirect(url_for("doctor_appointments"))

    try:
        datetime.strptime(time_slot, "%H:%M:%S")
    except ValueError:
        flash("Select a valid time slot.", "danger")
        return redirect(url_for("doctor_appointments"))

    connection = get_connection()
    cursor = connection.cursor(dictionary=True)
    try:
        connection.start_transaction()
        cursor.execute(
            """
            INSERT INTO doctor_schedule (doctor_id, schedule_date, time_slot, mode, booked_flag)
            VALUES (%s, %s, %s, %s, 0)
            """,
            (doctor_id, parsed_date, time_slot, slot_mode),
        )
        connection.commit()
        flash("Availability slot added.", "success")
    except IntegrityError:
        connection.rollback()
        flash("This slot already exists.", "warning")
    except Error:
        connection.rollback()
        flash("Unable to add availability slot.", "danger")
    finally:
        cursor.close()
        connection.close()
    return redirect(url_for("doctor_appointments"))


@app.route("/doctor/availability/day-mode", methods=["POST"])
@doctor_login_required
def doctor_update_day_mode():
    ensure_doctor_schedule_mode_column()
    doctor_id = session.get("doctor_id")
    schedule_date = request.form.get("schedule_date", "").strip()
    selected_mode = normalize_mode(request.form.get("mode"))
    if selected_mode not in ALLOWED_MODES:
        flash("Select a valid mode for the day.", "danger")
        return redirect(url_for("doctor_appointments"))
    try:
        parsed_date = datetime.strptime(schedule_date, "%Y-%m-%d").date()
    except ValueError:
        flash("Select a valid date.", "danger")
        return redirect(url_for("doctor_appointments"))

    connection = get_connection()
    cursor = connection.cursor(dictionary=True)
    try:
        connection.start_transaction()
        cursor.execute(
            """
            UPDATE doctor_schedule
            SET mode = %s
            WHERE doctor_id = %s
              AND schedule_date = %s
              AND booked_flag = 0
            """,
            (selected_mode, doctor_id, parsed_date),
        )
        if cursor.rowcount == 0:
            connection.rollback()
            flash("No unbooked slots found for that day.", "warning")
            return redirect(url_for("doctor_appointments"))
        connection.commit()
        flash("Day mode updated for available slots.", "success")
    except Error:
        connection.rollback()
        flash("Unable to update day mode.", "danger")
    finally:
        cursor.close()
        connection.close()
    return redirect(url_for("doctor_appointments"))


@app.route("/doctor/availability/slot-mode", methods=["POST"])
@doctor_login_required
def doctor_update_slot_mode():
    ensure_doctor_schedule_mode_column()
    doctor_id = session.get("doctor_id")
    schedule_date = request.form.get("schedule_date", "").strip()
    time_slot = normalize_time_input(request.form.get("time_slot", "").strip())
    selected_mode = normalize_mode(request.form.get("mode"))
    if selected_mode not in ALLOWED_MODES:
        flash("Select a valid mode for this slot.", "danger")
        return redirect(url_for("doctor_appointments"))

    try:
        parsed_date = datetime.strptime(schedule_date, "%Y-%m-%d").date()
        datetime.strptime(time_slot, "%H:%M:%S")
    except ValueError:
        flash("Invalid date or time for slot mode update.", "danger")
        return redirect(url_for("doctor_appointments"))

    connection = get_connection()
    cursor = connection.cursor(dictionary=True)
    try:
        connection.start_transaction()
        cursor.execute(
            """
            UPDATE doctor_schedule
            SET mode = %s
            WHERE doctor_id = %s
              AND schedule_date = %s
              AND time_slot = %s
              AND booked_flag = 0
            """,
            (selected_mode, doctor_id, parsed_date, time_slot),
        )
        if cursor.rowcount == 0:
            connection.rollback()
            flash("Only unbooked slots can be updated.", "warning")
            return redirect(url_for("doctor_appointments"))
        connection.commit()
        flash("Slot mode updated.", "success")
    except Error:
        connection.rollback()
        flash("Unable to update slot mode.", "danger")
    finally:
        cursor.close()
        connection.close()
    return redirect(url_for("doctor_appointments"))


@app.route("/doctor/availability/unavailable", methods=["POST"])
@doctor_login_required
def doctor_mark_unavailable():
    doctor_id = session.get("doctor_id")
    schedule_date = request.form.get("schedule_date", "").strip()
    time_slot = normalize_time_input(request.form.get("time_slot", "").strip())

    try:
        parsed_date = datetime.strptime(schedule_date, "%Y-%m-%d").date()
        datetime.strptime(time_slot, "%H:%M:%S")
    except ValueError:
        flash("Invalid date or time for availability update.", "danger")
        return redirect(url_for("doctor_appointments"))

    connection = get_connection()
    cursor = connection.cursor(dictionary=True)
    try:
        connection.start_transaction()
        cursor.execute(
            """
            SELECT id, booked_flag
            FROM doctor_schedule
            WHERE doctor_id = %s AND schedule_date = %s AND time_slot = %s
            FOR UPDATE
            """,
            (doctor_id, parsed_date, time_slot),
        )
        slot = cursor.fetchone()
        if not slot:
            connection.rollback()
            flash("Slot not found.", "warning")
            return redirect(url_for("doctor_appointments"))
        if int(slot["booked_flag"]) == 1:
            connection.rollback()
            flash("Booked slot cannot be marked unavailable.", "warning")
            return redirect(url_for("doctor_appointments"))

        cursor.execute("DELETE FROM doctor_schedule WHERE id = %s", (slot["id"],))
        connection.commit()
        flash("Slot marked as not available.", "success")
    except Error:
        connection.rollback()
        flash("Unable to update slot availability.", "danger")
    finally:
        cursor.close()
        connection.close()
    return redirect(url_for("doctor_appointments"))


@app.route("/doctor/appointments/update-status/<int:appointment_id>", methods=["POST"])
@doctor_login_required
def doctor_update_appointment_status(appointment_id):
    doctor_id = session.get("doctor_id")
    new_status = normalize_mode(request.form.get("status"))
    if new_status not in TERMINAL_STATUSES:
        flash("Select a valid final status.", "danger")
        return redirect(url_for("doctor_appointments"))

    connection = get_connection()
    cursor = connection.cursor(dictionary=True)
    try:
        connection.start_transaction()
        cursor.execute(
            """
            SELECT id, appointment_date, appointment_time, status, doctor_decision
            FROM appointment
            WHERE id = %s AND doctor_id = %s
            FOR UPDATE
            """,
            (appointment_id, doctor_id),
        )
        appointment = cursor.fetchone()
        if not appointment:
            connection.rollback()
            flash("Appointment not found for this doctor.", "danger")
            return redirect(url_for("doctor_appointments"))
        if appointment["status"] != "confirmed":
            connection.rollback()
            flash("Only confirmed appointments can be updated.", "warning")
            return redirect(url_for("doctor_appointments"))
        if appointment["doctor_decision"] != "accepted":
            connection.rollback()
            flash("Accept the appointment before setting final status.", "warning")
            return redirect(url_for("doctor_appointments"))

        cursor.execute("UPDATE appointment SET status = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s", (new_status, appointment_id))
        if new_status == "cancelled":
            cursor.execute(
                """
                UPDATE doctor_schedule
                SET booked_flag = 0
                WHERE doctor_id = %s
                  AND schedule_date = %s
                  AND time_slot = %s
                """,
                (doctor_id, appointment["appointment_date"], appointment["appointment_time"]),
            )
        connection.commit()
        flash("Appointment status updated.", "success")
    except Error:
        connection.rollback()
        flash("Unable to update appointment status.", "danger")
    finally:
        cursor.close()
        connection.close()
    return redirect(url_for("doctor_appointments"))


@app.route("/specialties")
def specialties():
    specialty_rows = fetch_all(
        """
        SELECT s.id, s.name, COUNT(d.id) AS doctor_count
        FROM specialty s
        LEFT JOIN doctor d ON d.specialty_id = s.id AND d.active = 1
        GROUP BY s.id, s.name
        ORDER BY s.name
        """
    )
    return render_template("specialties.html", specialties=specialty_rows)


@app.route("/patient/register", methods=["GET", "POST"])
def patient_register():
    form_values = {}
    errors = {}
    if request.method == "POST":
        ensure_patient_auth_column()
        form_values = {
            "name": request.form.get("name", "").strip(),
            "contact": request.form.get("contact", "").strip(),
            "dob": request.form.get("dob", "").strip(),
            "email": request.form.get("email", "").strip(),
        }
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")
        for key, label in (("name", "Name"), ("contact", "Contact"), ("dob", "Date of birth"), ("email", "Email")):
            if not form_values[key]:
                errors[key] = f"{label} is required."
        if form_values["email"] and "@" not in form_values["email"]:
            errors["email"] = "Enter a valid email address."
        if not password:
            errors["password"] = "Password is required."
        elif len(password) < 6:
            errors["password"] = "Password must be at least 6 characters."
        if password != confirm_password:
            errors["confirm_password"] = "Password and confirm password must match."
        if form_values["dob"]:
            try:
                datetime.strptime(form_values["dob"], "%Y-%m-%d")
            except ValueError:
                errors["dob"] = "Enter a valid date of birth."
        if not errors:
            try:
                connection = get_connection()
                connection.start_transaction()
                cursor = connection.cursor(dictionary=True)
                try:
                    cursor.execute(
                        """
                        SELECT id, password_hash
                        FROM patient
                        WHERE email = %s OR contact = %s
                        LIMIT 1
                        FOR UPDATE
                        """,
                        (form_values["email"], form_values["contact"]),
                    )
                    existing_patient = cursor.fetchone()
                    if existing_patient and existing_patient.get("password_hash"):
                        errors["email"] = "Patient account already exists. Please login."
                        raise ValueError
                    password_hash = generate_password_hash(password)
                    if existing_patient:
                        cursor.execute(
                            """
                            UPDATE patient
                            SET name = %s, contact = %s, dob = %s, email = %s, password_hash = %s
                            WHERE id = %s
                            """,
                            (
                                form_values["name"],
                                form_values["contact"],
                                form_values["dob"],
                                form_values["email"],
                                password_hash,
                                existing_patient["id"],
                            ),
                        )
                        patient_id = existing_patient["id"]
                    else:
                        cursor.execute(
                            """
                            INSERT INTO patient (name, contact, dob, email, password_hash)
                            VALUES (%s, %s, %s, %s, %s)
                            """,
                            (
                                form_values["name"],
                                form_values["contact"],
                                form_values["dob"],
                                form_values["email"],
                                password_hash,
                            ),
                        )
                        patient_id = cursor.lastrowid
                    connection.commit()
                    session.pop("is_admin", None)
                    session.pop("admin_username", None)
                    session.pop("doctor_id", None)
                    session.pop("doctor_name", None)
                    session["patient_id"] = patient_id
                    session["patient_name"] = form_values["name"]
                    flash("Patient registration successful. You are now logged in.", "success")
                    return redirect(url_for("book_appointment"))
                except (ValueError, IntegrityError):
                    connection.rollback()
                except Error:
                    connection.rollback()
                    flash("Unable to register patient right now.", "danger")
                finally:
                    cursor.close()
                    connection.close()
            except Error:
                flash("Database connection error while registering patient.", "danger")
    return render_template("patient_register.html", form_values=form_values, errors=errors)


@app.route("/patient/login", methods=["GET", "POST"])
def patient_login():
    next_url = request.args.get("next") or request.form.get("next") or url_for("book_appointment")
    form_values = {}
    if request.method == "POST":
        ensure_patient_auth_column()
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        form_values["email"] = email
        try:
            patient = fetch_one(
                """
                SELECT id, name, password_hash
                FROM patient
                WHERE email = %s
                LIMIT 1
                """,
                (email,),
            )
        except Error:
            patient = None
        if not patient or not patient.get("password_hash") or not check_password_hash(patient["password_hash"], password):
            flash("Invalid patient credentials.", "danger")
            return render_template("patient_login.html", next_url=next_url, form_values=form_values)
        session.pop("is_admin", None)
        session.pop("admin_username", None)
        session.pop("doctor_id", None)
        session.pop("doctor_name", None)
        session["patient_id"] = patient["id"]
        session["patient_name"] = patient["name"]
        flash("Patient login successful.", "success")
        if not next_url.startswith("/"):
            next_url = url_for("book_appointment")
        return redirect(next_url)
    return render_template("patient_login.html", next_url=next_url, form_values=form_values)


@app.route("/patient/logout")
def patient_logout():
    session.pop("patient_id", None)
    session.pop("patient_name", None)
    flash("Patient logged out successfully.", "success")
    return redirect(url_for("home"))


@app.route("/my-appointments")
@patient_login_required
def my_appointments():
    patient_id = session.get("patient_id")
    appointment_rows = fetch_all(
        """
        SELECT a.id, a.mode, a.appointment_date, a.appointment_time, a.status, a.fee,
               a.video_link, a.clinic_address, a.instructions, d.name AS doctor_name, s.name AS specialty_name
        FROM appointment a
        INNER JOIN doctor d ON d.id = a.doctor_id
        INNER JOIN specialty s ON s.id = d.specialty_id
        WHERE a.patient_id = %s
        ORDER BY a.appointment_date DESC, a.appointment_time DESC, a.id DESC
        """,
        (patient_id,),
    )
    return render_template("my_appointments.html", appointments=appointment_rows)


@app.route("/book", methods=["GET", "POST"])
def book_appointment():
    ensure_appointment_doctor_decision_column()
    if request.method == "POST":
        form_source = request.form.to_dict(flat=True)
        logged_in_patient = get_logged_in_patient()
        if logged_in_patient:
            form_source["patient_name"] = logged_in_patient["name"]
            form_source["patient_contact"] = logged_in_patient["contact"]
            form_source["patient_email"] = logged_in_patient["email"]
            form_source["patient_dob"] = display_date(logged_in_patient["dob"])
        data, errors = validate_booking_form(form_source)
        if data["mode"] not in ALLOWED_MODES:
            errors["mode"] = "Select a valid appointment mode."
        if data["specialty_id"] is None:
            errors["specialty_id"] = "Select a valid specialty."
        if data["doctor_id"] is None:
            errors["doctor_id"] = "Select a valid doctor."
        if errors:
            flash("Please fix the highlighted errors and try again.", "danger")
            return render_template("book.html", **prepare_booking_context(form_source, errors))
        try:
            connection = get_connection()
            connection.start_transaction()
            cursor = connection.cursor(dictionary=True)
            try:
                cursor.execute(
                    """
                    SELECT d.id, d.name, d.specialty_id, d.mode, d.fee, d.active, d.clinic_address, s.name AS specialty_name
                    FROM doctor d
                    INNER JOIN specialty s ON s.id = d.specialty_id
                    WHERE d.id = %s
                    FOR UPDATE
                    """,
                    (data["doctor_id"],),
                )
                doctor = cursor.fetchone()
                if not doctor:
                    errors["doctor_id"] = "Selected doctor does not exist."
                    raise ValueError
                if doctor["active"] != 1:
                    errors["doctor_id"] = "Selected doctor is inactive."
                    raise ValueError
                if doctor["specialty_id"] != data["specialty_id"]:
                    errors["doctor_id"] = "Selected doctor does not belong to the chosen specialty."
                    raise ValueError
                if doctor["mode"] != data["mode"]:
                    errors["mode"] = "Mode-doctor mismatch. Online appointments require online doctors and offline appointments require offline doctors."
                    raise ValueError
                cursor.execute(
                    """
                    SELECT id, booked_flag
                    FROM doctor_schedule
                    WHERE doctor_id = %s
                      AND schedule_date = %s
                      AND time_slot = %s
                    FOR UPDATE
                    """,
                    (doctor["id"], data["appointment_date"], data["appointment_time"]),
                )
                schedule = cursor.fetchone()
                if not schedule:
                    errors["appointment_time"] = "Selected schedule slot does not exist."
                    raise ValueError
                if schedule["booked_flag"] == 1:
                    errors["appointment_time"] = "This slot is already booked. Please choose another slot."
                    raise ValueError
                patient_id = get_or_create_patient(
                    connection,
                    data["patient_name"],
                    data["patient_contact"],
                    data["patient_dob"],
                    data["patient_email"],
                )
                cursor.execute(
                    """
                    INSERT INTO appointment (
                        patient_id, doctor_id, mode, appointment_date, appointment_time,
                        status, doctor_decision, fee, video_link, clinic_address, instructions
                    )
                    VALUES (%s, %s, %s, %s, %s, 'confirmed', 'pending', %s, %s, %s, %s)
                    """,
                    (
                        patient_id,
                        doctor["id"],
                        data["mode"],
                        data["appointment_date"],
                        data["appointment_time"],
                        doctor["fee"],
                        "",
                        doctor["clinic_address"] or DEFAULT_CLINIC_ADDRESS,
                        OFFLINE_INSTRUCTIONS,
                    ),
                )
                appointment_id = cursor.lastrowid
                video_link = f"https://meet.example.com/{appointment_id}"
                if data["mode"] == "online":
                    cursor.execute(
                        "UPDATE appointment SET video_link = %s, clinic_address = NULL, instructions = NULL WHERE id = %s",
                        (video_link, appointment_id),
                    )
                else:
                    cursor.execute(
                        "UPDATE appointment SET video_link = NULL, clinic_address = %s, instructions = %s WHERE id = %s",
                        (doctor["clinic_address"] or DEFAULT_CLINIC_ADDRESS, OFFLINE_INSTRUCTIONS, appointment_id),
                    )
                cursor.execute("UPDATE doctor_schedule SET booked_flag = 1 WHERE id = %s", (schedule["id"],))
                connection.commit()
                flash("Appointment booked successfully.", "success")
                return redirect(url_for("confirm_appointment", appointment_id=appointment_id))
            except (ValueError, IntegrityError):
                connection.rollback()
                if not errors:
                    flash("Unable to book the selected slot. Please try again.", "danger")
                return render_template("book.html", **prepare_booking_context(form_source, errors))
            except Error:
                connection.rollback()
                flash("Database error while booking appointment.", "danger")
                return render_template("book.html", **prepare_booking_context(form_source, errors))
            finally:
                cursor.close()
                connection.close()
        except Error:
            flash("Unable to connect to the database.", "danger")
            return render_template("book.html", **prepare_booking_context(form_source, errors))
    return render_template("book.html", **prepare_booking_context(request.args))


@app.route("/confirm/<int:appointment_id>")
def confirm_appointment(appointment_id):
    appointment = fetch_one(
        """
        SELECT a.id, a.mode, a.appointment_date, a.appointment_time, a.status, a.fee,
               a.video_link, a.clinic_address, a.instructions, a.created_at,
               p.name AS patient_name, p.contact AS patient_contact, p.email AS patient_email,
               d.name AS doctor_name, d.mode AS doctor_mode, s.name AS specialty_name
        FROM appointment a
        INNER JOIN patient p ON p.id = a.patient_id
        INNER JOIN doctor d ON d.id = a.doctor_id
        INNER JOIN specialty s ON s.id = d.specialty_id
        WHERE a.id = %s
        """,
        (appointment_id,),
    )
    if not appointment:
        flash("Appointment not found.", "danger")
        return redirect(url_for("book_appointment"))
    return render_template("confirm.html", appointment=appointment)


@app.route("/appointments")
@admin_login_required
def appointments():
    appointment_rows = fetch_all(
        """
        SELECT a.id, a.mode, a.appointment_date, a.appointment_time, a.status, a.doctor_decision,
               a.fee, a.created_at, p.name AS patient_name, d.name AS doctor_name, s.name AS specialty_name
        FROM appointment a
        INNER JOIN patient p ON p.id = a.patient_id
        INNER JOIN doctor d ON d.id = a.doctor_id
        INNER JOIN specialty s ON s.id = d.specialty_id
        ORDER BY a.appointment_date DESC, a.appointment_time DESC, a.id DESC
        """
    )
    return render_template("appointments.html", appointments=appointment_rows, allowed_statuses=ALLOWED_STATUSES, terminal_statuses=TERMINAL_STATUSES)


@app.route("/appointments/update-status/<int:appointment_id>", methods=["POST"])
@admin_login_required
def update_appointment_status(appointment_id):
    new_status = normalize_mode(request.form.get("status"))
    if new_status not in ALLOWED_STATUSES:
        flash("Select a valid appointment status.", "danger")
        return redirect(url_for("appointments"))
    appointment = fetch_one(
        """
        SELECT id, doctor_id, appointment_date, appointment_time, status
        FROM appointment
        WHERE id = %s
        """,
        (appointment_id,),
    )
    if not appointment:
        flash("Appointment not found.", "danger")
        return redirect(url_for("appointments"))
    if appointment["status"] != "confirmed":
        flash("Only confirmed appointments can be moved to a final status.", "danger")
        return redirect(url_for("appointments"))
    try:
        connection = get_connection()
        connection.start_transaction()
        cursor = connection.cursor(dictionary=True)
        try:
            cursor.execute("UPDATE appointment SET status = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s", (new_status, appointment_id))
            if new_status == "cancelled":
                cursor.execute(
                    """
                    UPDATE doctor_schedule
                    SET booked_flag = 0
                    WHERE doctor_id = %s
                      AND schedule_date = %s
                      AND time_slot = %s
                    """,
                    (appointment["doctor_id"], appointment["appointment_date"], appointment["appointment_time"]),
                )
            connection.commit()
            flash("Appointment status updated successfully.", "success")
        except Error:
            connection.rollback()
            flash("Unable to update appointment status.", "danger")
        finally:
            cursor.close()
            connection.close()
    except Error:
        flash("Unable to connect to the database.", "danger")
    return redirect(url_for("appointments"))


@app.route("/summary")
@admin_login_required
def summary():
    summary_date = request.args.get("date") or display_date(date_class.today())
    try:
        datetime.strptime(summary_date, "%Y-%m-%d")
    except ValueError:
        summary_date = display_date(date_class.today())
    totals = fetch_one(
        """
        SELECT COUNT(*) AS total_appointments,
               COALESCE(SUM(CASE WHEN status <> 'cancelled' THEN fee ELSE 0 END), 0) AS total_revenue
        FROM appointment
        WHERE appointment_date = %s
        """,
        (summary_date,),
    ) or {"total_appointments": 0, "total_revenue": 0}
    mode_summary = fetch_all(
        """
        SELECT a.mode, COUNT(*) AS total_appointments,
               COALESCE(SUM(CASE WHEN a.status <> 'cancelled' THEN a.fee ELSE 0 END), 0) AS total_revenue
        FROM appointment a
        WHERE a.appointment_date = %s
        GROUP BY a.mode
        ORDER BY a.mode
        """,
        (summary_date,),
    )
    specialty_summary = fetch_all(
        """
        SELECT s.name AS specialty_name, COUNT(*) AS total_appointments,
               COALESCE(SUM(CASE WHEN a.status <> 'cancelled' THEN a.fee ELSE 0 END), 0) AS total_revenue
        FROM appointment a
        INNER JOIN doctor d ON d.id = a.doctor_id
        INNER JOIN specialty s ON s.id = d.specialty_id
        WHERE a.appointment_date = %s
        GROUP BY s.name
        ORDER BY s.name
        """,
        (summary_date,),
    )
    return render_template("summary.html", summary_date=summary_date, totals=totals, mode_summary=mode_summary, specialty_summary=specialty_summary)


if __name__ == "__main__":
    app.run(debug=True)

from datetime import date as date_class
from datetime import datetime, timedelta
from functools import wraps

from flask import Flask, flash, redirect, render_template, request, session, url_for
from mysql.connector import Error, IntegrityError
from werkzeug.security import check_password_hash, generate_password_hash

from config import Config
from db import fetch_all, fetch_one, get_connection


app = Flask(__name__)
app.config.from_object(Config)
app.secret_key = Config.SECRET_KEY

ALLOWED_MODES = ("online", "offline")
ALLOWED_STATUSES = ("confirmed", "completed", "cancelled", "no-show")
TERMINAL_STATUSES = ("completed", "cancelled", "no-show")
ALLOWED_DOCTOR_DECISIONS = ("pending", "accepted", "rejected")
OFFLINE_INSTRUCTIONS = "Please arrive 15 minutes early and carry previous reports."
DEFAULT_CLINIC_ADDRESS = "HCL Clinic, Main Road, City Center"


def admin_login_required(view_function):
    @wraps(view_function)
    def wrapped_view(*args, **kwargs):
        if not session.get("is_admin"):
            flash("Admin login is required to access this page.", "warning")
            return redirect(url_for("admin_login", next=request.path))
        return view_function(*args, **kwargs)

    return wrapped_view


def patient_login_required(view_function):
    @wraps(view_function)
    def wrapped_view(*args, **kwargs):
        if not session.get("patient_id"):
            flash("Patient login is required to access this page.", "warning")
            return redirect(url_for("patient_login", next=request.path))
        return view_function(*args, **kwargs)

    return wrapped_view


def doctor_login_required(view_function):
    @wraps(view_function)
    def wrapped_view(*args, **kwargs):
        if not session.get("doctor_id"):
            flash("Doctor login is required to access this page.", "warning")
            return redirect(url_for("doctor_login", next=request.path))
        return view_function(*args, **kwargs)

    return wrapped_view


def normalize_mode(value):
    if value is None:
        return ""
    return str(value).strip().lower()


def safe_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def normalize_time_input(value):
    if not value:
        return ""
    value = str(value).strip()
    if len(value) == 5:
        return f"{value}:00"
    return value


def display_time(value):
    if value is None:
        return ""
    if isinstance(value, timedelta):
        total_seconds = int(value.total_seconds())
        hours, remainder = divmod(total_seconds, 3600)
        minutes = remainder // 60
        return f"{hours:02d}:{minutes:02d}"
    if hasattr(value, "strftime"):
        return value.strftime("%H:%M")
    text = str(value)
    return text[:5] if len(text) >= 5 else text


def display_date(value):
    if value is None:
        return ""
    if hasattr(value, "strftime"):
        return value.strftime("%Y-%m-%d")
    return str(value)


@app.template_filter("display_time")
def display_time_filter(value):
    return display_time(value)


@app.template_filter("display_date")
def display_date_filter(value):
    return display_date(value)


def get_specialties():
    return fetch_all("SELECT id, name FROM specialty ORDER BY name")


def ensure_patient_auth_column():
    """Auto-add patient password column for older databases created before auth was introduced."""
    connection = get_connection()
    cursor = connection.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT COUNT(*) AS column_count
            FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = %s
              AND TABLE_NAME = 'patient'
              AND COLUMN_NAME = 'password_hash'
            """,
            (Config.MYSQL_DB,),
        )
        row = cursor.fetchone()
        if row and row["column_count"] == 0:
            cursor.execute("ALTER TABLE patient ADD COLUMN password_hash VARCHAR(255) NULL AFTER email")
            connection.commit()
    finally:
        cursor.close()
        connection.close()


def ensure_doctor_auth_columns():
    connection = get_connection()
    cursor = connection.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT COLUMN_NAME
            FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = %s
              AND TABLE_NAME = 'doctor'
              AND COLUMN_NAME IN ('username', 'password_hash', 'email', 'phone')
            """,
            (Config.MYSQL_DB,),
        )
        existing = {row["COLUMN_NAME"] for row in cursor.fetchall()}

        if "username" not in existing:
            cursor.execute("ALTER TABLE doctor ADD COLUMN username VARCHAR(80) NULL AFTER name")
            cursor.execute("CREATE UNIQUE INDEX uq_doctor_username ON doctor (username)")

        if "password_hash" not in existing:
            cursor.execute("ALTER TABLE doctor ADD COLUMN password_hash VARCHAR(255) NULL AFTER username")

        if "email" not in existing:
            cursor.execute("ALTER TABLE doctor ADD COLUMN email VARCHAR(150) NULL AFTER password_hash")

        if "phone" not in existing:
            cursor.execute("ALTER TABLE doctor ADD COLUMN phone VARCHAR(20) NULL AFTER email")

        cursor.execute(
            """
            SELECT COUNT(*) AS idx_count
            FROM information_schema.STATISTICS
            WHERE TABLE_SCHEMA = %s
              AND TABLE_NAME = 'doctor'
              AND INDEX_NAME = 'uq_doctor_email'
            """,
            (Config.MYSQL_DB,),
        )
        idx_row = cursor.fetchone()
        if idx_row and idx_row["idx_count"] == 0:
            cursor.execute("CREATE UNIQUE INDEX uq_doctor_email ON doctor (email)")

        connection.commit()
    finally:
        cursor.close()
        connection.close()


def ensure_appointment_doctor_decision_column():
    connection = get_connection()
    cursor = connection.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT COUNT(*) AS column_count
            FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = %s
              AND TABLE_NAME = 'appointment'
              AND COLUMN_NAME = 'doctor_decision'
            """,
            (Config.MYSQL_DB,),
        )
        row = cursor.fetchone()
        if row and row["column_count"] == 0:
            cursor.execute(
                "ALTER TABLE appointment ADD COLUMN doctor_decision VARCHAR(20) NOT NULL DEFAULT 'pending' AFTER status"
            )
            connection.commit()
    finally:
        cursor.close()
        connection.close()


def get_logged_in_patient():
    patient_id = session.get("patient_id")
    if not patient_id:
        return None

    return fetch_one(
        """
        SELECT id, name, contact, dob, email
        FROM patient
        WHERE id = %s
        """,
        (patient_id,),
    )


def get_doctors(mode=None, specialty_id=None, active_only=True):
    query = [
        "SELECT d.id, d.name, d.mode, d.fee, d.active, d.clinic_address, s.name AS specialty_name",
        "FROM doctor d",
        "INNER JOIN specialty s ON s.id = d.specialty_id",
        "WHERE 1 = 1",
    ]
    params = []
    if active_only:
        query.append("AND d.active = 1")
    if mode:
        query.append("AND d.mode = %s")
        params.append(mode)
    if specialty_id:
        query.append("AND d.specialty_id = %s")
        params.append(specialty_id)
    query.append("ORDER BY d.name")
    return fetch_all("\n".join(query), params)


def get_available_slots(doctor_id, appointment_date):
    return fetch_all(
        """
    SELECT id, time_slot
        FROM doctor_schedule
        WHERE doctor_id = %s
          AND schedule_date = %s
          AND booked_flag = 0
        ORDER BY time_slot
        """,
        (doctor_id, appointment_date),
    )


def prepare_booking_context(form_values=None, errors=None):
    values = form_values or {}

    logged_in_patient = get_logged_in_patient()
    if logged_in_patient:
        values = dict(values)
        values.setdefault("patient_name", logged_in_patient["name"])
        values.setdefault("patient_contact", logged_in_patient["contact"])
        values.setdefault("patient_email", logged_in_patient["email"])
        if logged_in_patient.get("dob"):
            values.setdefault("patient_dob", display_date(logged_in_patient["dob"]))

    mode = normalize_mode(values.get("mode"))
    specialty_id = safe_int(values.get("specialty_id"))
    doctor_id = safe_int(values.get("doctor_id"))
    appointment_date = values.get("appointment_date", "")

    specialties = get_specialties()
    doctors = []
    slots = []

    if mode in ALLOWED_MODES and specialty_id:
        doctors = get_doctors(mode=mode, specialty_id=specialty_id)

    if doctor_id and appointment_date:
        slots = get_available_slots(doctor_id, appointment_date)

    return {
        "specialties": specialties,
        "doctors": doctors,
        "slots": slots,
        "selected_mode": mode,
        "selected_specialty_id": specialty_id,
        "selected_doctor_id": doctor_id,
        "selected_date": appointment_date,
        "form_values": values,
        "errors": errors or {},
        "allowed_modes": ALLOWED_MODES,
        "allowed_statuses": ALLOWED_STATUSES,
    }


def validate_booking_form(form):
    errors = {}
    data = {
        "mode": normalize_mode(form.get("mode")),
        "specialty_id": safe_int(form.get("specialty_id")),
        "doctor_id": safe_int(form.get("doctor_id")),
        "appointment_date": form.get("appointment_date", "").strip(),
        "appointment_time": normalize_time_input(form.get("appointment_time", "")),
        "patient_name": form.get("patient_name", "").strip(),
        "patient_contact": form.get("patient_contact", "").strip(),
        "patient_dob": form.get("patient_dob", "").strip(),
        "patient_email": form.get("patient_email", "").strip(),
    }

    required_fields = {
        "mode": "Appointment mode is required.",
        "specialty_id": "Specialty is required.",
        "doctor_id": "Doctor is required.",
        "appointment_date": "Appointment date is required.",
        "appointment_time": "Appointment time is required.",
        "patient_name": "Patient name is required.",
        "patient_contact": "Patient contact is required.",
        "patient_dob": "Patient date of birth is required.",
        "patient_email": "Patient email is required.",
    }

    for key, message in required_fields.items():
        if not data[key]:
            errors[key] = message

    if data["mode"] and data["mode"] not in ALLOWED_MODES:
        errors["mode"] = "Mode must be either Online or Offline."

    if data["patient_email"] and "@" not in data["patient_email"]:
        errors["patient_email"] = "Enter a valid email address."

    if data["appointment_date"]:
        try:
            appointment_date = datetime.strptime(data["appointment_date"], "%Y-%m-%d").date()
            if appointment_date < date_class.today():
                errors["appointment_date"] = "Appointment date cannot be in the past."
        except ValueError:
            errors["appointment_date"] = "Enter a valid appointment date."

    if data["patient_dob"]:
        try:
            datetime.strptime(data["patient_dob"], "%Y-%m-%d")
        except ValueError:
            errors["patient_dob"] = "Enter a valid date of birth."

    if data["appointment_time"]:
        try:
            datetime.strptime(data["appointment_time"], "%H:%M:%S")
        except ValueError:
            errors["appointment_time"] = "Enter a valid appointment time."

    return data, errors


def get_or_create_patient(connection, patient_name, patient_contact, patient_dob, patient_email):
    cursor = connection.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT id
            FROM patient
            WHERE contact = %s OR email = %s
            LIMIT 1
            FOR UPDATE
            """,
            (patient_contact, patient_email),
        )
        existing_patient = cursor.fetchone()
        if existing_patient:
            cursor.execute(
                """
                UPDATE patient
                SET name = %s, contact = %s, dob = %s, email = %s
                WHERE id = %s
                """,
                (patient_name, patient_contact, patient_dob, patient_email, existing_patient["id"]),
            )
            return existing_patient["id"]

        cursor.execute(
            """
            INSERT INTO patient (name, contact, dob, email)
            VALUES (%s, %s, %s, %s)
            """,
            (patient_name, patient_contact, patient_dob, patient_email),
        )
        return cursor.lastrowid
    finally:
        cursor.close()


@app.route("/")
def home():
    return render_template("home.html")


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    next_url = request.args.get("next") or request.form.get("next") or url_for("appointments")

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        if username == Config.ADMIN_USERNAME and password == Config.ADMIN_PASSWORD:
            session.pop("patient_id", None)
            session.pop("patient_name", None)
            session.pop("doctor_id", None)
            session.pop("doctor_name", None)
            session["is_admin"] = True
            session["admin_username"] = username
            flash("Admin login successful.", "success")
            if not next_url.startswith("/"):
                next_url = url_for("appointments")
            return redirect(next_url)

        flash("Invalid admin credentials.", "danger")

    return render_template("admin_login.html", next_url=next_url)


@app.route("/admin/logout")
def admin_logout():
    session.pop("is_admin", None)
    session.pop("admin_username", None)
    flash("Admin logged out successfully.", "success")
    return redirect(url_for("home"))


@app.route("/doctor/register", methods=["GET", "POST"])
def doctor_register():
    ensure_doctor_auth_columns()

    errors = {}
    form_values = {}
    specialties = get_specialties()

    if request.method == "POST":
        form_values = {
            "specialty_id": request.form.get("specialty_id", "").strip(),
            "doctor_name": request.form.get("doctor_name", "").strip(),
            "email": request.form.get("email", "").strip(),
            "phone": request.form.get("phone", "").strip(),
        }
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        specialty_id = safe_int(form_values["specialty_id"])
        if specialty_id is None:
            errors["specialty_id"] = "Please select specialization."
        if not form_values["doctor_name"]:
            errors["doctor_name"] = "Doctor name is required."
        if not form_values["email"] or "@" not in form_values["email"]:
            errors["email"] = "Valid email is required."
        if not form_values["phone"]:
            errors["phone"] = "Phone is required."
        if len(password) < 6:
            errors["password"] = "Password must be at least 6 characters."
        if password != confirm_password:
            errors["confirm_password"] = "Password and confirm password must match."

        if not errors:
            connection = get_connection()
            cursor = connection.cursor(dictionary=True)
            try:
                connection.start_transaction()
                cursor.execute(
                    "SELECT id FROM doctor WHERE email = %s LIMIT 1 FOR UPDATE",
                    (form_values["email"],),
                )
                existing_email = cursor.fetchone()
                if existing_email:
                    errors["email"] = "Email is already in use."
                    raise ValueError

                cursor.execute(
                    """
                    INSERT INTO doctor (
                        name,
                        username,
                        password_hash,
                        email,
                        phone,
                        specialty_id,
                        mode,
                        fee,
                        active,
                        clinic_address
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, 'offline', 500.00, 1, %s)
                    """,
                    (
                        form_values["doctor_name"],
                        form_values["email"],
                        generate_password_hash(password),
                        form_values["email"],
                        form_values["phone"],
                        specialty_id,
                        DEFAULT_CLINIC_ADDRESS,
                    ),
                )
                connection.commit()
                flash("Doctor registration successful. Please login.", "success")
                return redirect(url_for("doctor_login"))
            except (ValueError, Error, IntegrityError):
                connection.rollback()
            finally:
                cursor.close()
                connection.close()

    return render_template("doctor_register.html", specialties=specialties, errors=errors, form_values=form_values)


@app.route("/doctor/login", methods=["GET", "POST"])
def doctor_login():
    ensure_doctor_auth_columns()
    ensure_appointment_doctor_decision_column()

    next_url = request.args.get("next") or request.form.get("next") or url_for("doctor_appointments")
    form_values = {}

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        form_values["username"] = username

        doctor = fetch_one(
            """
            SELECT id, name, username, password_hash
            FROM doctor
            WHERE username = %s AND active = 1
            LIMIT 1
            """,
            (username,),
        )

        if not doctor or not doctor.get("password_hash") or not check_password_hash(doctor["password_hash"], password):
            flash("Invalid doctor credentials.", "danger")
            return render_template("doctor_login.html", next_url=next_url, form_values=form_values)

        session.pop("is_admin", None)
        session.pop("admin_username", None)
        session.pop("patient_id", None)
        session.pop("patient_name", None)
        session["doctor_id"] = doctor["id"]
        session["doctor_name"] = doctor["name"]
        flash("Doctor login successful.", "success")
        if not next_url.startswith("/"):
            next_url = url_for("doctor_appointments")
        return redirect(next_url)

    return render_template("doctor_login.html", next_url=next_url, form_values=form_values)


@app.route("/doctor/logout")
def doctor_logout():
    session.pop("doctor_id", None)
    session.pop("doctor_name", None)
    flash("Doctor logged out successfully.", "success")
    return redirect(url_for("home"))


@app.route("/doctor/appointments")
@doctor_login_required
def doctor_appointments():
    ensure_appointment_doctor_decision_column()
    ensure_doctor_schedule_mode_column()
    doctor_id = session.get("doctor_id")
    doctor_profile = fetch_one(
        """
        SELECT id, name, mode, clinic_address
        FROM doctor
        WHERE id = %s
        LIMIT 1
        """,
        (doctor_id,),
    )
    appointment_rows = fetch_all(
        """
        SELECT
            a.id,
            a.appointment_date,
            a.appointment_time,
            a.mode,
            a.status,
            a.doctor_decision,
            a.fee,
            p.name AS patient_name,
            p.contact AS patient_contact,
            p.email AS patient_email,
            s.name AS specialty_name
        FROM appointment a
        INNER JOIN patient p ON p.id = a.patient_id
        INNER JOIN doctor d ON d.id = a.doctor_id
        INNER JOIN specialty s ON s.id = d.specialty_id
        WHERE a.doctor_id = %s
        ORDER BY a.appointment_date DESC, a.appointment_time DESC, a.id DESC
        """,
        (doctor_id,),
    )
    start_date = date_class.today()
    end_date = start_date + timedelta(days=6)
    schedule_rows = fetch_all(
        """
                SELECT schedule_date, time_slot, booked_flag, mode
        FROM doctor_schedule
        WHERE doctor_id = %s
          AND schedule_date BETWEEN %s AND %s
        ORDER BY schedule_date, time_slot
        """,
        (doctor_id, start_date, end_date),
    )
    schedule_map = {}
    for row in schedule_rows:
        date_key = display_date(row["schedule_date"])
        schedule_map.setdefault(date_key, []).append(row)

    availability_days = []
    for offset in range(7):
        day_value = start_date + timedelta(days=offset)
        date_key = display_date(day_value)
        slots = []
        for slot in schedule_map.get(date_key, []):
            slot_value = slot["time_slot"]
            if hasattr(slot_value, "strftime"):
                slot_value = slot_value.strftime("%H:%M:%S")
            else:
                slot_value = normalize_time_input(slot_value)
            slots.append(
                {
                    "time_display": display_time(slot["time_slot"]),
                    "time_value": slot_value,
                    "booked_flag": int(slot["booked_flag"]),
                    "mode": normalize_mode(slot.get("mode")) or "offline",
                }
            )
        availability_days.append(
            {
                "date": date_key,
                "label": day_value.strftime("%A, %d %b %Y"),
                "slots": slots,
            }
        )

    return render_template(
        "doctor_appointments.html",
        appointments=appointment_rows,
        doctor_profile=doctor_profile,
        availability_days=availability_days,
        terminal_statuses=TERMINAL_STATUSES,
    )


@app.route("/doctor/appointments/decision/<int:appointment_id>", methods=["POST"])
@doctor_login_required
def doctor_appointment_decision(appointment_id):
    ensure_appointment_doctor_decision_column()

    decision = normalize_mode(request.form.get("decision"))
    if decision not in ("accepted", "rejected"):
        flash("Invalid decision.", "danger")
        return redirect(url_for("doctor_appointments"))

    doctor_id = session.get("doctor_id")
    connection = get_connection()
    cursor = connection.cursor(dictionary=True)
    try:
        connection.start_transaction()
        cursor.execute(
            """
            SELECT id, doctor_id, appointment_date, appointment_time, status, doctor_decision
            FROM appointment
            WHERE id = %s AND doctor_id = %s
            FOR UPDATE
            """,
            (appointment_id, doctor_id),
        )
        appointment = cursor.fetchone()
        if not appointment:
            flash("Appointment not found for this doctor.", "danger")
            connection.rollback()
            return redirect(url_for("doctor_appointments"))

        if appointment["status"] == "cancelled":
            flash("This appointment is already cancelled.", "warning")
            connection.rollback()
            return redirect(url_for("doctor_appointments"))

        if decision == "accepted":
            cursor.execute(
                "UPDATE appointment SET doctor_decision = 'accepted', updated_at = CURRENT_TIMESTAMP WHERE id = %s",
                (appointment_id,),
            )
            flash("Appointment accepted.", "success")
        else:
            cursor.execute(
                "UPDATE appointment SET doctor_decision = 'rejected', status = 'cancelled', updated_at = CURRENT_TIMESTAMP WHERE id = %s",
                (appointment_id,),
            )
            cursor.execute(
                """
                UPDATE doctor_schedule
                SET booked_flag = 0
                WHERE doctor_id = %s
                  AND schedule_date = %s
                  AND time_slot = %s
                """,
                (doctor_id, appointment["appointment_date"], appointment["appointment_time"]),
            )
            flash("Appointment rejected and slot released.", "success")

        connection.commit()
    except Error:
        connection.rollback()
        flash("Unable to update appointment decision.", "danger")
    finally:
        cursor.close()
        connection.close()

    return redirect(url_for("doctor_appointments"))


@app.route("/doctor/availability/add", methods=["POST"])
@doctor_login_required
def doctor_add_availability():
    ensure_doctor_schedule_mode_column()
    doctor_id = session.get("doctor_id")
    schedule_date = request.form.get("schedule_date", "").strip()
    time_slot = normalize_time_input(request.form.get("time_slot", "").strip())
    slot_mode = normalize_mode(request.form.get("mode"))
    if slot_mode not in ALLOWED_MODES:
        flash("Select a valid mode for this slot.", "danger")
        return redirect(url_for("doctor_appointments"))

    try:
        parsed_date = datetime.strptime(schedule_date, "%Y-%m-%d").date()
    except ValueError:
        flash("Select a valid availability date.", "danger")
        return redirect(url_for("doctor_appointments"))

    if parsed_date < date_class.today():
        flash("Availability date cannot be in the past.", "danger")
        return redirect(url_for("doctor_appointments"))

    try:
        datetime.strptime(time_slot, "%H:%M:%S")
    except ValueError:
        flash("Select a valid time slot.", "danger")
        return redirect(url_for("doctor_appointments"))

    connection = get_connection()
    cursor = connection.cursor(dictionary=True)
    try:
        connection.start_transaction()
        cursor.execute(
            """
            INSERT INTO doctor_schedule (doctor_id, schedule_date, time_slot, mode, booked_flag)
            VALUES (%s, %s, %s, %s, 0)
            """,
            (doctor_id, parsed_date, time_slot, slot_mode),
        )
        connection.commit()
        flash("Availability slot added.", "success")
    except IntegrityError:
        connection.rollback()
        flash("This slot already exists.", "warning")
    except Error:
        connection.rollback()
        flash("Unable to add availability slot.", "danger")
    finally:
        cursor.close()
        connection.close()
    return redirect(url_for("doctor_appointments"))


@app.route("/doctor/availability/day-mode", methods=["POST"])
@doctor_login_required
def doctor_update_day_mode():
    ensure_doctor_schedule_mode_column()
    doctor_id = session.get("doctor_id")
    schedule_date = request.form.get("schedule_date", "").strip()
    selected_mode = normalize_mode(request.form.get("mode"))
    if selected_mode not in ALLOWED_MODES:
        flash("Select a valid mode for the day.", "danger")
        return redirect(url_for("doctor_appointments"))
    try:
        parsed_date = datetime.strptime(schedule_date, "%Y-%m-%d").date()
    except ValueError:
        flash("Select a valid date.", "danger")
        return redirect(url_for("doctor_appointments"))

    connection = get_connection()
    cursor = connection.cursor(dictionary=True)
    try:
        connection.start_transaction()
        cursor.execute(
            """
            UPDATE doctor_schedule
            SET mode = %s
            WHERE doctor_id = %s
              AND schedule_date = %s
              AND booked_flag = 0
            """,
            (selected_mode, doctor_id, parsed_date),
        )
        if cursor.rowcount == 0:
            connection.rollback()
            flash("No unbooked slots found for that day.", "warning")
            return redirect(url_for("doctor_appointments"))
        connection.commit()
        flash("Day mode updated for available slots.", "success")
    except Error:
        connection.rollback()
        flash("Unable to update day mode.", "danger")
    finally:
        cursor.close()
        connection.close()
    return redirect(url_for("doctor_appointments"))


@app.route("/doctor/availability/slot-mode", methods=["POST"])
@doctor_login_required
def doctor_update_slot_mode():
    ensure_doctor_schedule_mode_column()
    doctor_id = session.get("doctor_id")
    schedule_date = request.form.get("schedule_date", "").strip()
    time_slot = normalize_time_input(request.form.get("time_slot", "").strip())
    selected_mode = normalize_mode(request.form.get("mode"))
    if selected_mode not in ALLOWED_MODES:
        flash("Select a valid mode for this slot.", "danger")
        return redirect(url_for("doctor_appointments"))

    try:
        parsed_date = datetime.strptime(schedule_date, "%Y-%m-%d").date()
        datetime.strptime(time_slot, "%H:%M:%S")
    except ValueError:
        flash("Invalid date or time for slot mode update.", "danger")
        return redirect(url_for("doctor_appointments"))

    connection = get_connection()
    cursor = connection.cursor(dictionary=True)
    try:
        connection.start_transaction()
        cursor.execute(
            """
            UPDATE doctor_schedule
            SET mode = %s
            WHERE doctor_id = %s
              AND schedule_date = %s
              AND time_slot = %s
              AND booked_flag = 0
            """,
            (selected_mode, doctor_id, parsed_date, time_slot),
        )
        if cursor.rowcount == 0:
            connection.rollback()
            flash("Only unbooked slots can be updated.", "warning")
            return redirect(url_for("doctor_appointments"))
        connection.commit()
        flash("Slot mode updated.", "success")
    except Error:
        connection.rollback()
        flash("Unable to update slot mode.", "danger")
    finally:
        cursor.close()
        connection.close()
    return redirect(url_for("doctor_appointments"))


@app.route("/doctor/availability/unavailable", methods=["POST"])
@doctor_login_required
def doctor_mark_unavailable():
    doctor_id = session.get("doctor_id")
    schedule_date = request.form.get("schedule_date", "").strip()
    time_slot = normalize_time_input(request.form.get("time_slot", "").strip())

    try:
        parsed_date = datetime.strptime(schedule_date, "%Y-%m-%d").date()
        datetime.strptime(time_slot, "%H:%M:%S")
    except ValueError:
        flash("Invalid date or time for availability update.", "danger")
        return redirect(url_for("doctor_appointments"))

    connection = get_connection()
    cursor = connection.cursor(dictionary=True)
    try:
        connection.start_transaction()
        cursor.execute(
            """
            SELECT id, booked_flag
            FROM doctor_schedule
            WHERE doctor_id = %s AND schedule_date = %s AND time_slot = %s
            FOR UPDATE
            """,
            (doctor_id, parsed_date, time_slot),
        )
        slot = cursor.fetchone()
        if not slot:
            connection.rollback()
            flash("Slot not found.", "warning")
            return redirect(url_for("doctor_appointments"))
        if int(slot["booked_flag"]) == 1:
            connection.rollback()
            flash("Booked slot cannot be marked unavailable.", "warning")
            return redirect(url_for("doctor_appointments"))

        cursor.execute("DELETE FROM doctor_schedule WHERE id = %s", (slot["id"],))
        connection.commit()
        flash("Slot marked as not available.", "success")
    except Error:
        connection.rollback()
        flash("Unable to update slot availability.", "danger")
    finally:
        cursor.close()
        connection.close()
    return redirect(url_for("doctor_appointments"))


@app.route("/doctor/appointments/update-status/<int:appointment_id>", methods=["POST"])
@doctor_login_required
def doctor_update_appointment_status(appointment_id):
    doctor_id = session.get("doctor_id")
    new_status = normalize_mode(request.form.get("status"))
    if new_status not in TERMINAL_STATUSES:
        flash("Select a valid final status.", "danger")
        return redirect(url_for("doctor_appointments"))

    connection = get_connection()
    cursor = connection.cursor(dictionary=True)
    try:
        connection.start_transaction()
        cursor.execute(
            """
            SELECT id, appointment_date, appointment_time, status, doctor_decision
            FROM appointment
            WHERE id = %s AND doctor_id = %s
            FOR UPDATE
            """,
            (appointment_id, doctor_id),
        )
        appointment = cursor.fetchone()
        if not appointment:
            connection.rollback()
            flash("Appointment not found for this doctor.", "danger")
            return redirect(url_for("doctor_appointments"))
        if appointment["status"] != "confirmed":
            connection.rollback()
            flash("Only confirmed appointments can be updated.", "warning")
            return redirect(url_for("doctor_appointments"))
        if appointment["doctor_decision"] != "accepted":
            connection.rollback()
            flash("Accept the appointment before setting final status.", "warning")
            return redirect(url_for("doctor_appointments"))

        cursor.execute(
            "UPDATE appointment SET status = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s",
            (new_status, appointment_id),
        )
        if new_status == "cancelled":
            cursor.execute(
                """
                UPDATE doctor_schedule
                SET booked_flag = 0
                WHERE doctor_id = %s
                  AND schedule_date = %s
                  AND time_slot = %s
                """,
                (doctor_id, appointment["appointment_date"], appointment["appointment_time"]),
            )
        connection.commit()
        flash("Appointment status updated.", "success")
    except Error:
        connection.rollback()
        flash("Unable to update appointment status.", "danger")
    finally:
        cursor.close()
        connection.close()
    return redirect(url_for("doctor_appointments"))


@app.route("/specialties")
def specialties():
    specialty_rows = fetch_all(
        """
        SELECT s.id, s.name, COUNT(d.id) AS doctor_count
        FROM specialty s
        LEFT JOIN doctor d ON d.specialty_id = s.id AND d.active = 1
        GROUP BY s.id, s.name
        ORDER BY s.name
        """
    )
    return render_template("specialties.html", specialties=specialty_rows)


@app.route("/patient/register", methods=["GET", "POST"])
def patient_register():
    form_values = {}
    errors = {}

    if request.method == "POST":
        ensure_patient_auth_column()

        form_values = {
            "name": request.form.get("name", "").strip(),
            "contact": request.form.get("contact", "").strip(),
            "dob": request.form.get("dob", "").strip(),
            "email": request.form.get("email", "").strip(),
        }
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        for key, label in (("name", "Name"), ("contact", "Contact"), ("dob", "Date of birth"), ("email", "Email")):
            if not form_values[key]:
                errors[key] = f"{label} is required."

        if form_values["email"] and "@" not in form_values["email"]:
            errors["email"] = "Enter a valid email address."

        if not password:
            errors["password"] = "Password is required."
        elif len(password) < 6:
            errors["password"] = "Password must be at least 6 characters."

        if password != confirm_password:
            errors["confirm_password"] = "Password and confirm password must match."

        if form_values["dob"]:
            try:
                datetime.strptime(form_values["dob"], "%Y-%m-%d")
            except ValueError:
                errors["dob"] = "Enter a valid date of birth."

        if not errors:
            try:
                connection = get_connection()
                connection.start_transaction()
                cursor = connection.cursor(dictionary=True)
                try:
                    cursor.execute(
                        """
                        SELECT id, password_hash
                        FROM patient
                        WHERE email = %s OR contact = %s
                        LIMIT 1
                        FOR UPDATE
                        """,
                        (form_values["email"], form_values["contact"]),
                    )
                    existing_patient = cursor.fetchone()

                    if existing_patient and existing_patient.get("password_hash"):
                        errors["email"] = "Patient account already exists. Please login."
                        raise ValueError

                    password_hash = generate_password_hash(password)

                    if existing_patient:
                        cursor.execute(
                            """
                            UPDATE patient
                            SET name = %s, contact = %s, dob = %s, email = %s, password_hash = %s
                            WHERE id = %s
                            """,
                            (
                                form_values["name"],
                                form_values["contact"],
                                form_values["dob"],
                                form_values["email"],
                                password_hash,
                                existing_patient["id"],
                            ),
                        )
                        patient_id = existing_patient["id"]
                    else:
                        cursor.execute(
                            """
                            INSERT INTO patient (name, contact, dob, email, password_hash)
                            VALUES (%s, %s, %s, %s, %s)
                            """,
                            (
                                form_values["name"],
                                form_values["contact"],
                                form_values["dob"],
                                form_values["email"],
                                password_hash,
                            ),
                        )
                        patient_id = cursor.lastrowid

                    connection.commit()
                    session.pop("is_admin", None)
                    session.pop("admin_username", None)
                    session.pop("doctor_id", None)
                    session.pop("doctor_name", None)
                    session["patient_id"] = patient_id
                    session["patient_name"] = form_values["name"]
                    flash("Patient registration successful. You are now logged in.", "success")
                    return redirect(url_for("book_appointment"))
                except (ValueError, IntegrityError):
                    connection.rollback()
                except Error:
                    connection.rollback()
                    flash("Unable to register patient right now.", "danger")
                finally:
                    cursor.close()
                    connection.close()
            except Error:
                flash("Database connection error while registering patient.", "danger")

    return render_template("patient_register.html", form_values=form_values, errors=errors)


@app.route("/patient/login", methods=["GET", "POST"])
def patient_login():
    next_url = request.args.get("next") or request.form.get("next") or url_for("book_appointment")
    form_values = {}

    if request.method == "POST":
        ensure_patient_auth_column()

        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        form_values["email"] = email

        try:
            patient = fetch_one(
                """
                SELECT id, name, password_hash
                FROM patient
                WHERE email = %s
                LIMIT 1
                """,
                (email,),
            )
        except Error:
            patient = None

        if not patient or not patient.get("password_hash") or not check_password_hash(patient["password_hash"], password):
            flash("Invalid patient credentials.", "danger")
            return render_template("patient_login.html", next_url=next_url, form_values=form_values)

        session.pop("is_admin", None)
        session.pop("admin_username", None)
        session.pop("doctor_id", None)
        session.pop("doctor_name", None)
        session["patient_id"] = patient["id"]
        session["patient_name"] = patient["name"]
        flash("Patient login successful.", "success")
        if not next_url.startswith("/"):
            next_url = url_for("book_appointment")
        return redirect(next_url)

    return render_template("patient_login.html", next_url=next_url, form_values=form_values)


@app.route("/patient/logout")
def patient_logout():
    session.pop("patient_id", None)
    session.pop("patient_name", None)
    flash("Patient logged out successfully.", "success")
    return redirect(url_for("home"))


@app.route("/my-appointments")
@patient_login_required
def my_appointments():
    patient_id = session.get("patient_id")
    appointment_rows = fetch_all(
        """
        SELECT
            a.id,
            a.mode,
            a.appointment_date,
            a.appointment_time,
            a.status,
            a.fee,
            a.video_link,
            a.clinic_address,
            a.instructions,
            d.name AS doctor_name,
            s.name AS specialty_name
        FROM appointment a
        INNER JOIN doctor d ON d.id = a.doctor_id
        INNER JOIN specialty s ON s.id = d.specialty_id
        WHERE a.patient_id = %s
        ORDER BY a.appointment_date DESC, a.appointment_time DESC, a.id DESC
        """,
        (patient_id,),
    )
    return render_template("my_appointments.html", appointments=appointment_rows)


@app.route("/book", methods=["GET", "POST"])
def book_appointment():
    ensure_appointment_doctor_decision_column()

    if request.method == "POST":
        form_source = request.form.to_dict(flat=True)
        logged_in_patient = get_logged_in_patient()

        if logged_in_patient:
            form_source["patient_name"] = logged_in_patient["name"]
            form_source["patient_contact"] = logged_in_patient["contact"]
            form_source["patient_email"] = logged_in_patient["email"]
            form_source["patient_dob"] = display_date(logged_in_patient["dob"])

        data, errors = validate_booking_form(form_source)

        if data["mode"] not in ALLOWED_MODES:
            errors["mode"] = "Select a valid appointment mode."

        if data["specialty_id"] is None:
            errors["specialty_id"] = "Select a valid specialty."

        if data["doctor_id"] is None:
            errors["doctor_id"] = "Select a valid doctor."

        if errors:
            flash("Please fix the highlighted errors and try again.", "danger")
            return render_template("book.html", **prepare_booking_context(form_source, errors))

        try:
            connection = get_connection()
            connection.start_transaction()
            cursor = connection.cursor(dictionary=True)

            try:
                cursor.execute(
                    """
                    SELECT d.id, d.name, d.specialty_id, d.mode, d.fee, d.active, d.clinic_address, s.name AS specialty_name
                    FROM doctor d
                    INNER JOIN specialty s ON s.id = d.specialty_id
                    WHERE d.id = %s
                    FOR UPDATE
                    """,
                    (data["doctor_id"],),
                )
                doctor = cursor.fetchone()
                if not doctor:
                    errors["doctor_id"] = "Selected doctor does not exist."
                    raise ValueError

                if doctor["active"] != 1:
                    errors["doctor_id"] = "Selected doctor is inactive."
                    raise ValueError

                if doctor["specialty_id"] != data["specialty_id"]:
                    errors["doctor_id"] = "Selected doctor does not belong to the chosen specialty."
                    raise ValueError

                if doctor["mode"] != data["mode"]:
                    errors["mode"] = "Mode-doctor mismatch. Online appointments require online doctors and offline appointments require offline doctors."
                    raise ValueError

                cursor.execute(
                    """
                    SELECT id, booked_flag
                    FROM doctor_schedule
                    WHERE doctor_id = %s
                      AND schedule_date = %s
                      AND time_slot = %s
                    FOR UPDATE
                    """,
                    (doctor["id"], data["appointment_date"], data["appointment_time"]),
                )
                schedule = cursor.fetchone()
                if not schedule:
                    errors["appointment_time"] = "Selected schedule slot does not exist."
                    raise ValueError

                if schedule["booked_flag"] == 1:
                    errors["appointment_time"] = "This slot is already booked. Please choose another slot."
                    raise ValueError

                patient_id = get_or_create_patient(
                    connection,
                    data["patient_name"],
                    data["patient_contact"],
                    data["patient_dob"],
                    data["patient_email"],
                )

                cursor.execute(
                    """
                    INSERT INTO appointment (
                        patient_id,
                        doctor_id,
                        mode,
                        appointment_date,
                        appointment_time,
                        status,
                        doctor_decision,
                        fee,
                        video_link,
                        clinic_address,
                        instructions
                    )
                    VALUES (%s, %s, %s, %s, %s, 'confirmed', 'pending', %s, %s, %s, %s)
                    """,
                    (
                        patient_id,
                        doctor["id"],
                        data["mode"],
                        data["appointment_date"],
                        data["appointment_time"],
                        doctor["fee"],
                        "",
                        doctor["clinic_address"] or DEFAULT_CLINIC_ADDRESS,
                        OFFLINE_INSTRUCTIONS,
                    ),
                )

                appointment_id = cursor.lastrowid
                video_link = f"https://meet.example.com/{appointment_id}"

                if data["mode"] == "online":
                    cursor.execute(
                        "UPDATE appointment SET video_link = %s, clinic_address = NULL, instructions = NULL WHERE id = %s",
                        (video_link, appointment_id),
                    )
                else:
                    cursor.execute(
                        "UPDATE appointment SET video_link = NULL, clinic_address = %s, instructions = %s WHERE id = %s",
                        (doctor["clinic_address"] or DEFAULT_CLINIC_ADDRESS, OFFLINE_INSTRUCTIONS, appointment_id),
                    )

                cursor.execute(
                    "UPDATE doctor_schedule SET booked_flag = 1 WHERE id = %s",
                    (schedule["id"],),
                )

                connection.commit()
                flash("Appointment booked successfully.", "success")
                return redirect(url_for("confirm_appointment", appointment_id=appointment_id))
            except (ValueError, IntegrityError):
                connection.rollback()
                if not errors:
                    flash("Unable to book the selected slot. Please try again.", "danger")
                return render_template("book.html", **prepare_booking_context(form_source, errors))
            except Error:
                connection.rollback()
                flash("Database error while booking appointment.", "danger")
                return render_template("book.html", **prepare_booking_context(form_source, errors))
            finally:
                cursor.close()
                connection.close()
        except Error:
            flash("Unable to connect to the database.", "danger")
            return render_template("book.html", **prepare_booking_context(form_source, errors))

    return render_template("book.html", **prepare_booking_context(request.args))


@app.route("/confirm/<int:appointment_id>")
def confirm_appointment(appointment_id):
    appointment = fetch_one(
        """
        SELECT
            a.id,
            a.mode,
            a.appointment_date,
            a.appointment_time,
            a.status,
            a.fee,
            a.video_link,
            a.clinic_address,
            a.instructions,
            a.created_at,
            p.name AS patient_name,
            p.contact AS patient_contact,
            p.email AS patient_email,
            d.name AS doctor_name,
            d.mode AS doctor_mode,
            s.name AS specialty_name
        FROM appointment a
        INNER JOIN patient p ON p.id = a.patient_id
        INNER JOIN doctor d ON d.id = a.doctor_id
        INNER JOIN specialty s ON s.id = d.specialty_id
        WHERE a.id = %s
        """,
        (appointment_id,),
    )

    if not appointment:
        flash("Appointment not found.", "danger")
        return redirect(url_for("book_appointment"))

    return render_template("confirm.html", appointment=appointment)


@app.route("/appointments")
@admin_login_required
def appointments():
    appointment_rows = fetch_all(
        """
        SELECT
            a.id,
            a.mode,
            a.appointment_date,
            a.appointment_time,
            a.status,
            a.doctor_decision,
            a.fee,
            a.created_at,
            p.name AS patient_name,
            d.name AS doctor_name,
            s.name AS specialty_name
        FROM appointment a
        INNER JOIN patient p ON p.id = a.patient_id
        INNER JOIN doctor d ON d.id = a.doctor_id
        INNER JOIN specialty s ON s.id = d.specialty_id
        ORDER BY a.appointment_date DESC, a.appointment_time DESC, a.id DESC
        """
    )
    return render_template(
        "appointments.html",
        appointments=appointment_rows,
        allowed_statuses=ALLOWED_STATUSES,
        terminal_statuses=TERMINAL_STATUSES,
    )


@app.route("/appointments/update-status/<int:appointment_id>", methods=["POST"])
@admin_login_required
def update_appointment_status(appointment_id):
    new_status = normalize_mode(request.form.get("status"))
    if new_status not in ALLOWED_STATUSES:
        flash("Select a valid appointment status.", "danger")
        return redirect(url_for("appointments"))

    appointment = fetch_one(
        """
        SELECT id, doctor_id, appointment_date, appointment_time, status
        FROM appointment
        WHERE id = %s
        """,
        (appointment_id,),
    )

    if not appointment:
        flash("Appointment not found.", "danger")
        return redirect(url_for("appointments"))

    if appointment["status"] != "confirmed":
        flash("Only confirmed appointments can be moved to a final status.", "danger")
        return redirect(url_for("appointments"))

    try:
        connection = get_connection()
        connection.start_transaction()
        cursor = connection.cursor(dictionary=True)

        try:
            cursor.execute(
                "UPDATE appointment SET status = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s",
                (new_status, appointment_id),
            )

            if new_status == "cancelled":
                cursor.execute(
                    """
                    UPDATE doctor_schedule
                    SET booked_flag = 0
                    WHERE doctor_id = %s
                      AND schedule_date = %s
                      AND time_slot = %s
                    """,
                    (appointment["doctor_id"], appointment["appointment_date"], appointment["appointment_time"]),
                )

            connection.commit()
            flash("Appointment status updated successfully.", "success")
        except Error:
            connection.rollback()
            flash("Unable to update appointment status.", "danger")
        finally:
            cursor.close()
            connection.close()
    except Error:
        flash("Unable to connect to the database.", "danger")

    return redirect(url_for("appointments"))


@app.route("/summary")
@admin_login_required
def summary():
    summary_date = request.args.get("date") or display_date(date_class.today())
    try:
        datetime.strptime(summary_date, "%Y-%m-%d")
    except ValueError:
        summary_date = display_date(date_class.today())

    totals = fetch_one(
        """
        SELECT
            COUNT(*) AS total_appointments,
            COALESCE(SUM(CASE WHEN status <> 'cancelled' THEN fee ELSE 0 END), 0) AS total_revenue
        FROM appointment
        WHERE appointment_date = %s
        """,
        (summary_date,),
    ) or {"total_appointments": 0, "total_revenue": 0}

    mode_summary = fetch_all(
        """
        SELECT
            a.mode,
            COUNT(*) AS total_appointments,
            COALESCE(SUM(CASE WHEN a.status <> 'cancelled' THEN a.fee ELSE 0 END), 0) AS total_revenue
        FROM appointment a
        WHERE a.appointment_date = %s
        GROUP BY a.mode
        ORDER BY a.mode
        """,
        (summary_date,),
    )

    specialty_summary = fetch_all(
        """
        SELECT
            s.name AS specialty_name,
            COUNT(*) AS total_appointments,
            COALESCE(SUM(CASE WHEN a.status <> 'cancelled' THEN a.fee ELSE 0 END), 0) AS total_revenue
        FROM appointment a
        INNER JOIN doctor d ON d.id = a.doctor_id
        INNER JOIN specialty s ON s.id = d.specialty_id
        WHERE a.appointment_date = %s
        GROUP BY s.name
        ORDER BY s.name
        """,
        (summary_date,),
    )

    return render_template(
        "summary.html",
        summary_date=summary_date,
        totals=totals,
        mode_summary=mode_summary,
        specialty_summary=specialty_summary,
    )


if __name__ == "__main__":
    app.run(debug=True)
