from flask import Flask, render_template, request, redirect, url_for, session, flash
import sqlite3
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
from pathlib import Path

app = Flask(__name__)
app.secret_key = "change-this-development-secret"
DB = Path(__file__).with_name("clinic.db")

def db():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    return con

def init_db():
    with db() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, username TEXT UNIQUE, password TEXT, role TEXT);
        CREATE TABLE IF NOT EXISTS patients(id INTEGER PRIMARY KEY, name TEXT, age INTEGER, phone TEXT, address TEXT);
        CREATE TABLE IF NOT EXISTS doctors(id INTEGER PRIMARY KEY, name TEXT, specialization TEXT, phone TEXT, available_time TEXT);
        CREATE TABLE IF NOT EXISTS appointments(id INTEGER PRIMARY KEY, patient_id INTEGER, doctor_id INTEGER, date TEXT, time TEXT, status TEXT DEFAULT 'Booked',
          FOREIGN KEY(patient_id) REFERENCES patients(id), FOREIGN KEY(doctor_id) REFERENCES doctors(id));
        CREATE TABLE IF NOT EXISTS consultations(id INTEGER PRIMARY KEY, patient_id INTEGER, doctor_id INTEGER, visit_date TEXT, symptoms TEXT, diagnosis TEXT, prescription TEXT);
        """)
        if not con.execute("SELECT 1 FROM users LIMIT 1").fetchone():
            con.execute("INSERT INTO users(username,password,role) VALUES(?,?,?)",
                        ("admin", generate_password_hash("admin123"), "Administrator"))
            con.execute("INSERT INTO users(username,password,role) VALUES(?,?,?)",
                        ("doctor", generate_password_hash("doctor123"), "Doctor"))
            con.execute("INSERT INTO users(username,password,role) VALUES(?,?,?)",
                        ("reception", generate_password_hash("reception123"), "Receptionist"))

def roles_required(*allowed_roles):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if not session.get("user"):
                return redirect(url_for("login"))
            if session.get("role") not in allowed_roles:
                flash("You do not have permission to access this module.")
                return redirect(url_for("index"))
            return fn(*args, **kwargs)
        return wrapper
    return decorator

def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("user"):
            return redirect(url_for("login"))
        return fn(*args, **kwargs)
    return wrapper

@app.route("/", methods=["GET"])
def index():
    if not session.get("user"): return redirect(url_for("login"))
    with db() as con:
        stats = {
            "patients": con.execute("SELECT COUNT(*) FROM patients").fetchone()[0],
            "doctors": con.execute("SELECT COUNT(*) FROM doctors").fetchone()[0],
            "appointments": con.execute("SELECT COUNT(*) FROM appointments").fetchone()[0],
            "pending": con.execute("SELECT COUNT(*) FROM appointments WHERE status='Booked'").fetchone()[0],
        }
        recent = con.execute("""SELECT a.*, p.name patient, d.name doctor FROM appointments a
          JOIN patients p ON p.id=a.patient_id JOIN doctors d ON d.id=a.doctor_id ORDER BY a.date DESC,a.time DESC LIMIT 6""").fetchall()
    return render_template("dashboard.html", stats=stats, recent=recent)

@app.route("/login", methods=["GET","POST"])
def login():
    if request.method == "POST":
        with db() as con:
            u = con.execute("SELECT * FROM users WHERE username=?", (request.form["username"],)).fetchone()
        if u and check_password_hash(u["password"], request.form["password"]):
            session["user"], session["role"] = u["username"], u["role"]
            return redirect(url_for("index"))
        flash("Invalid username or password.")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/patients", methods=["GET","POST"])
@roles_required("Administrator", "Receptionist", "Doctor")
def patients():
    with db() as con:
        if request.method == "POST":
            if session.get("role") not in ("Administrator", "Receptionist"):
                flash("Only Admin or Receptionist can register patients.")
                return redirect(url_for("patients"))
            con.execute("INSERT INTO patients(name,age,phone,address) VALUES(?,?,?,?)",
                (request.form["name"], request.form["age"], request.form["phone"], request.form["address"]))
            flash("Patient added successfully.")
            return redirect(url_for("patients"))
        q = request.args.get("q","")
        rows = con.execute("SELECT * FROM patients WHERE name LIKE ? OR CAST(id AS TEXT) LIKE ? ORDER BY id DESC",
                           (f"%{q}%",f"%{q}%")).fetchall()
    return render_template("patients.html", rows=rows, q=q)

@app.route("/doctors", methods=["GET","POST"])
@roles_required("Administrator", "Receptionist", "Doctor")
def doctors():
    with db() as con:
        if request.method == "POST":
            if session.get("role") != "Administrator":
                flash("Only Admin can add doctor details.")
                return redirect(url_for("doctors"))
            con.execute("INSERT INTO doctors(name,specialization,phone,available_time) VALUES(?,?,?,?)",
                (request.form["name"], request.form["specialization"], request.form["phone"], request.form["available_time"]))
            flash("Doctor added successfully.")
            return redirect(url_for("doctors"))
        rows = con.execute("SELECT * FROM doctors ORDER BY id DESC").fetchall()
    return render_template("doctors.html", rows=rows)

@app.route("/appointments", methods=["GET","POST"])
@roles_required("Administrator", "Receptionist", "Doctor")
def appointments():
    with db() as con:
        if request.method == "POST":
            if session.get("role") not in ("Administrator", "Receptionist"):
                flash("Only Admin or Receptionist can book appointments.")
                return redirect(url_for("appointments"))
            con.execute("INSERT INTO appointments(patient_id,doctor_id,date,time,status) VALUES(?,?,?,?, 'Booked')",
                (request.form["patient_id"], request.form["doctor_id"], request.form["date"], request.form["time"]))
            flash("Appointment booked.")
            return redirect(url_for("appointments"))
        rows = con.execute("""SELECT a.*,p.name patient,d.name doctor FROM appointments a
          JOIN patients p ON p.id=a.patient_id JOIN doctors d ON d.id=a.doctor_id ORDER BY a.date DESC,a.time DESC""").fetchall()
        ps = con.execute("SELECT * FROM patients ORDER BY name").fetchall()
        ds = con.execute("SELECT * FROM doctors ORDER BY name").fetchall()
    return render_template("appointments.html", rows=rows, patients=ps, doctors=ds)

@app.post("/appointment/<int:aid>/status")
@roles_required("Administrator", "Receptionist", "Doctor")
def appointment_status(aid):
    if session.get("role") == "Doctor":
        flash("Doctors can view appointments but cannot change booking status.")
        return redirect(url_for("appointments"))
    status = request.form.get("status")
    if status not in ("Booked","Completed","Cancelled"): status = "Booked"
    with db() as con: con.execute("UPDATE appointments SET status=? WHERE id=?", (status,aid))
    flash("Appointment status updated.")
    return redirect(url_for("appointments"))

@app.route("/consultations", methods=["GET","POST"])
@roles_required("Doctor")
def consultations():
    with db() as con:
        if request.method == "POST":
            con.execute("""INSERT INTO consultations(patient_id,doctor_id,visit_date,symptoms,diagnosis,prescription)
              VALUES(?,?,?,?,?,?)""", (request.form["patient_id"],request.form["doctor_id"],request.form["visit_date"],
              request.form["symptoms"],request.form["diagnosis"],request.form["prescription"]))
            flash("Consultation record saved.")
            return redirect(url_for("consultations"))
        rows = con.execute("""SELECT c.*,p.name patient,d.name doctor FROM consultations c
          JOIN patients p ON p.id=c.patient_id JOIN doctors d ON d.id=c.doctor_id ORDER BY c.id DESC""").fetchall()
        ps = con.execute("SELECT * FROM patients ORDER BY name").fetchall()
        ds = con.execute("SELECT * FROM doctors ORDER BY name").fetchall()
    return render_template("consultations.html", rows=rows, patients=ps, doctors=ds)

if __name__ == "__main__":
    init_db()
    app.run(debug=True)
