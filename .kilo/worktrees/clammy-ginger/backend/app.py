"""Flask API and static-file server for the Smart Library System."""

import os
import re
import secrets
import sqlite3
import hmac
import json
import math
from datetime import date, datetime, timedelta
from functools import wraps
from pathlib import Path
from zoneinfo import ZoneInfo

from flask import Flask, abort, g, jsonify, redirect, request, send_from_directory, session
from werkzeug.security import check_password_hash, generate_password_hash

from database import DATABASE_PATH, get_connection, initialize_database


PROJECT_ROOT = Path(__file__).resolve().parent.parent
COVER_DIRECTORY = Path(__file__).resolve().parent / "uploads" / "book_covers"
FACE_DIRECTORY = Path(__file__).resolve().parent / "uploads" / "person_faces"
MAX_COVER_SIZE = 5 * 1024 * 1024
MANILA_TIME = ZoneInfo("Asia/Manila")
app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.environ.get("SMART_LIBRARY_SECRET", "local-development-key-change-before-deployment"),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("SMART_LIBRARY_HTTPS", "0") == "1",
    MAX_CONTENT_LENGTH=MAX_COVER_SIZE + 64 * 1024,
)
initialize_database()


def api_error(message, status=400):
    return jsonify({"error": message}), status


def signed_in_user():
    user_id = session.get("user_id")
    if not user_id:
        return None
    with get_connection() as connection:
        user = connection.execute(
            "SELECT id, school_id, name, email, role, department, status "
            "FROM users WHERE id = ? AND status = 'active'",
            (user_id,),
        ).fetchone()
    return dict(user) if user else None


@app.before_request
def load_signed_in_user():
    g.user = signed_in_user()


def login_required(handler):
    @wraps(handler)
    def wrapped(*args, **kwargs):
        if not g.user:
            return api_error("Please log in to continue.", 401)
        return handler(*args, **kwargs)

    return wrapped


def roles_required(*roles):
    def decorate(handler):
        @wraps(handler)
        @login_required
        def wrapped(*args, **kwargs):
            if g.user["role"] not in roles:
                return api_error("You do not have permission to perform this action.", 403)
            return handler(*args, **kwargs)

        return wrapped

    return decorate


def iot_required(handler):
    @wraps(handler)
    def wrapped(*args, **kwargs):
        expected_key = os.environ.get("SMART_LIBRARY_IOT_KEY", "")
        supplied_key = request.headers.get("X-IOT-API-Key", "")
        if not expected_key:
            return api_error("IoT API key is not configured on the main backend.", 503)
        if not supplied_key or not hmac.compare_digest(supplied_key, expected_key):
            return api_error("A valid IoT API key is required.", 401)
        return handler(*args, **kwargs)

    return wrapped


def clean_text(data, field, maximum=200):
    value = str(data.get(field, "")).strip()
    if not value or len(value) > maximum:
        raise ValueError(f"{field.replace('_', ' ').capitalize()} is required and must be under {maximum} characters.")
    return value


def transaction_rows(search="", date_from="", date_to=""):
    try:
        if date_from:
            date.fromisoformat(date_from)
        if date_to:
            date.fromisoformat(date_to)
    except ValueError:
        raise ValueError("Dates must use the YYYY-MM-DD format.")
    if date_from and date_to and date_from > date_to:
        raise ValueError("The start date must not be after the end date.")

    sql = """
        SELECT t.id, t.book_id, t.borrower_id, b.barcode, b.title,
               u.school_id AS borrower_school_id, u.name AS borrower_name,
               u.department AS borrower_department, u.email AS borrower_email,
               staff.name AS processed_by, t.borrow_date, t.due_date, t.return_date,
               t.status,
            CASE WHEN t.status = 'borrowed' AND t.due_date < ?
                    THEN 'overdue' ELSE t.status END AS display_status
        FROM book_transactions t
        JOIN books b ON b.id = t.book_id
        JOIN users u ON u.id = t.borrower_id
        JOIN users staff ON staff.id = t.processed_by
        WHERE (b.title LIKE ? OR b.barcode LIKE ? OR u.name LIKE ? OR u.school_id LIKE ?)
    """
    search_term = f"%{search}%"
    parameters = [manila_now()[:10], search_term, search_term, search_term, search_term]
    if date_from and date_to:
        sql += " AND ((date(t.borrow_date) BETWEEN ? AND ?) OR (date(t.return_date) BETWEEN ? AND ?))"
        parameters.extend([date_from, date_to, date_from, date_to])
    elif date_from:
        sql += " AND (date(t.borrow_date) >= ? OR date(t.return_date) >= ?)"
        parameters.extend([date_from, date_from])
    elif date_to:
        sql += " AND (date(t.borrow_date) <= ? OR date(t.return_date) <= ?)"
        parameters.extend([date_to, date_to])
    sql += " ORDER BY t.created_at DESC, t.id DESC"
    with get_connection() as connection:
        return [dict(row) for row in connection.execute(sql, parameters).fetchall()]


def manila_now():
    return datetime.now(MANILA_TIME).isoformat(timespec="seconds")


def attendance_rows(search="", date_from="", date_to="", role="", department="", event_type="all"):
    for value in (date_from, date_to):
        if value:
            try:
                date.fromisoformat(value)
            except ValueError as error:
                raise ValueError("Dates must use the YYYY-MM-DD format.") from error
    if date_from and date_to and date_from > date_to:
        raise ValueError("The start date must not be after the end date.")
    if event_type not in ("all", "time_in", "time_out"):
        raise ValueError("Choose all attendance, Time-in, or Time-out records.")

    sql = """
        SELECT a.id, u.id AS person_id, u.school_id, u.name,
               COALESCE(NULLIF(u.person_type, ''), u.role) AS role,
               u.department, a.attendance_date, a.time_in, a.time_out, a.source,
               CASE a.status WHEN 'admin_closed' THEN 'Closed by Admin'
                    WHEN 'inside' THEN 'Inside' ELSE 'Completed' END AS status
        FROM attendance_records a
        JOIN users u ON u.id = a.person_id
        WHERE (u.school_id LIKE ? OR u.name LIKE ?)
          AND (? = '' OR COALESCE(NULLIF(u.person_type, ''), u.role) = ?)
          AND (? = '' OR u.department LIKE ?)
          AND u.role NOT IN ('MIS Admin', 'Librarian')
    """
    search_term = f"%{search}%"
    parameters = [search_term, search_term, role, role, f"%{department}%" if department else "", f"%{department}%" if department else ""]
    if event_type == "time_in":
        sql += " AND a.time_in IS NOT NULL"
    elif event_type == "time_out":
        sql += " AND a.time_out IS NOT NULL"
    if date_from and date_to:
        if event_type == "time_in":
            sql += " AND substr(a.time_in, 1, 10) BETWEEN ? AND ?"
            parameters.extend([date_from, date_to])
        elif event_type == "time_out":
            sql += " AND substr(a.time_out, 1, 10) BETWEEN ? AND ?"
            parameters.extend([date_from, date_to])
        else:
            sql += " AND (substr(a.time_in, 1, 10) BETWEEN ? AND ? OR substr(a.time_out, 1, 10) BETWEEN ? AND ?)"
            parameters.extend([date_from, date_to, date_from, date_to])
    elif date_from:
        if event_type == "all":
            sql += " AND (substr(a.time_in, 1, 10) >= ? OR (a.time_out IS NOT NULL AND substr(a.time_out, 1, 10) >= ?))"
            parameters.extend([date_from, date_from])
        else:
            field = "a.time_out" if event_type == "time_out" else "a.time_in"
            sql += f" AND substr({field}, 1, 10) >= ?"
            parameters.append(date_from)
    elif date_to:
        if event_type == "all":
            sql += " AND (substr(a.time_in, 1, 10) <= ? OR (a.time_out IS NOT NULL AND substr(a.time_out, 1, 10) <= ?))"
            parameters.extend([date_to, date_to])
        else:
            field = "a.time_out" if event_type == "time_out" else "a.time_in"
            sql += f" AND substr({field}, 1, 10) <= ?"
            parameters.append(date_to)
    sql += " ORDER BY a.time_in DESC, a.id DESC"
    with get_connection() as connection:
        return [dict(row) for row in connection.execute(sql, parameters).fetchall()]


@app.post("/api/auth/login")
def login():
    data = request.get_json(silent=True) or {}
    email = str(data.get("email", "")).strip().lower()
    password = str(data.get("password", ""))
    with get_connection() as connection:
        user = connection.execute(
            "SELECT id, school_id, name, email, password_hash, role, department "
            "FROM users WHERE lower(email) = ? AND status = 'active'",
            (email,),
        ).fetchone()
    if (not user or user["role"] not in ("MIS Admin", "Librarian") or not user["password_hash"]
            or not check_password_hash(user["password_hash"], password)):
        return api_error("Email or password is incorrect.", 401)
    session.clear()
    session["user_id"] = user["id"]
    with get_connection() as connection:
        connection.execute("UPDATE users SET last_login_at = ? WHERE id = ?", (manila_now(), user["id"]))
    return jsonify({"user": {key: user[key] for key in ("id", "school_id", "name", "email", "role", "department")}})


@app.get("/api/auth/me")
@login_required
def get_session_user():
    return jsonify({"user": g.user})


@app.post("/api/auth/logout")
def logout():
    session.clear()
    return jsonify({"message": "You have been logged out."})


@app.post("/api/auth/change-password")
@login_required
def change_password():
    data = request.get_json(silent=True) or {}
    password = str(data.get("newPassword", ""))
    confirmation = str(data.get("confirmPassword", ""))
    if len(password) < 8:
        return api_error("Password must be at least 8 characters long.")
    if password != confirmation:
        return api_error("The passwords do not match.")
    with get_connection() as connection:
        connection.execute("UPDATE users SET password_hash = ? WHERE id = ?", (generate_password_hash(password), g.user["id"]))
    session.clear()
    return jsonify({"message": "Password updated. Please log in again."})


@app.get("/api/books")
@login_required
def list_books():
    search = f"%{request.args.get('q', '').strip()}%"
    with get_connection() as connection:
        rows = connection.execute(
            """SELECT id, barcode, title, author, category, published_date, cover_image,
                      quantity, available_quantity,
                      CASE WHEN available_quantity > 0 THEN 'Available' ELSE 'Not Available' END AS status
               FROM books WHERE status = 'active' AND (barcode LIKE ? OR title LIKE ? OR author LIKE ? OR category LIKE ?)
               ORDER BY title COLLATE NOCASE""",
            (search, search, search, search),
        ).fetchall()
    return jsonify({"books": [dict(row) for row in rows]})


def cover_extension(image_data):
    if image_data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if image_data.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if image_data.startswith((b"GIF87a", b"GIF89a")):
        return ".gif"
    if image_data[:4] == b"RIFF" and image_data[8:12] == b"WEBP":
        return ".webp"
    return None


@app.get("/api/books/<int:book_id>/cover")
@login_required
def get_book_cover(book_id):
    with get_connection() as connection:
        book = connection.execute(
            "SELECT cover_image FROM books WHERE id = ? AND status = 'active'", (book_id,)
        ).fetchone()
    if not book or not book["cover_image"]:
        abort(404)
    return send_from_directory(COVER_DIRECTORY, book["cover_image"], max_age=0)


@app.post("/api/books/<int:book_id>/cover")
@roles_required("MIS Admin", "Librarian")
def upload_book_cover(book_id):
    upload = request.files.get("cover")
    if not upload:
        return api_error("Choose an image file to upload.")
    image_data = upload.stream.read(MAX_COVER_SIZE + 1)
    if len(image_data) > MAX_COVER_SIZE:
        return api_error("Book images must be 5 MB or smaller.", 413)
    extension = cover_extension(image_data)
    if not extension:
        return api_error("Choose a valid PNG, JPEG, GIF, or WebP image.")

    with get_connection() as connection:
        book = connection.execute(
            "SELECT cover_image FROM books WHERE id = ? AND status = 'active'", (book_id,)
        ).fetchone()
    if not book:
        return api_error("Book not found.", 404)

    COVER_DIRECTORY.mkdir(parents=True, exist_ok=True)
    filename = secrets.token_hex(16) + extension
    image_path = COVER_DIRECTORY / filename
    image_path.write_bytes(image_data)
    try:
        with get_connection() as connection:
            connection.execute("UPDATE books SET cover_image = ? WHERE id = ?", (filename, book_id))
    except Exception:
        image_path.unlink(missing_ok=True)
        raise

    old_filename = book["cover_image"]
    if old_filename and Path(old_filename).name == old_filename:
        (COVER_DIRECTORY / old_filename).unlink(missing_ok=True)
    return jsonify({"message": "Book image updated.", "cover_image": filename})


@app.delete("/api/books/<int:book_id>/cover")
@roles_required("MIS Admin", "Librarian")
def reset_book_cover(book_id):
    with get_connection() as connection:
        book = connection.execute(
            "SELECT cover_image FROM books WHERE id = ? AND status = 'active'", (book_id,)
        ).fetchone()
        if not book:
            return api_error("Book not found.", 404)
        connection.execute("UPDATE books SET cover_image = '' WHERE id = ?", (book_id,))
    old_filename = book["cover_image"]
    if old_filename and Path(old_filename).name == old_filename:
        (COVER_DIRECTORY / old_filename).unlink(missing_ok=True)
    return jsonify({"message": "Book image reset to the default."})


@app.post("/api/books")
@roles_required("MIS Admin", "Librarian")
def create_book():
    data = request.get_json(silent=True) or {}
    try:
        barcode = clean_text(data, "barcode", 50)
        title = clean_text(data, "title")
        author = clean_text(data, "author")
        category = clean_text(data, "category")
        published_date = str(data.get("published_date", "")).strip()
        quantity = int(data.get("quantity", 0))
        if quantity < 0:
            raise ValueError("Book count cannot be negative.")
    except (ValueError, TypeError) as error:
        return api_error(str(error))
    try:
        with get_connection() as connection:
            cursor = connection.execute(
                """INSERT INTO books
                   (barcode, title, author, category, published_date, quantity, available_quantity)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (barcode, title, author, category, published_date, quantity, quantity),
            )
        return jsonify({"id": cursor.lastrowid, "message": "Book added."}), 201
    except sqlite3.IntegrityError:
        return api_error("That book number is already in use.", 409)


@app.patch("/api/books/<int:book_id>")
@roles_required("MIS Admin", "Librarian")
def update_book(book_id):
    data = request.get_json(silent=True) or {}
    allowed_fields = {"barcode", "title", "author", "category", "published_date", "quantity"}
    values = {key: data[key] for key in allowed_fields if key in data}
    if not values:
        return api_error("No book details were provided.")
    try:
        for field in ("barcode", "title", "author", "category"):
            if field in values:
                values[field] = clean_text(values, field, 200 if field != "barcode" else 50)
        if "quantity" in values:
            new_quantity = int(values["quantity"])
            with get_connection() as connection:
                current = connection.execute("SELECT quantity, available_quantity FROM books WHERE id = ?", (book_id,)).fetchone()
                if not current:
                    return api_error("Book not found.", 404)
                borrowed = current["quantity"] - current["available_quantity"]
                if new_quantity < borrowed:
                    return api_error("Book count cannot be lower than the number of borrowed copies.")
                values["quantity"] = new_quantity
                values["available_quantity"] = new_quantity - borrowed
        fields = ", ".join(f"{field} = ?" for field in values)
        with get_connection() as connection:
            cursor = connection.execute(f"UPDATE books SET {fields} WHERE id = ?", (*values.values(), book_id))
            if cursor.rowcount == 0:
                return api_error("Book not found.", 404)
        return jsonify({"message": "Book updated."})
    except (ValueError, TypeError) as error:
        return api_error(str(error))
    except sqlite3.IntegrityError:
        return api_error("That book number is already in use.", 409)


@app.delete("/api/books/<int:book_id>")
@roles_required("MIS Admin", "Librarian")
def delete_book(book_id):
    with get_connection() as connection:
        active = connection.execute(
            "SELECT COUNT(*) FROM book_transactions WHERE book_id = ? AND status = 'borrowed'", (book_id,)
        ).fetchone()[0]
        if active:
            return api_error("Return all borrowed copies before removing this book.", 409)
        cursor = connection.execute("UPDATE books SET status = 'archived' WHERE id = ? AND status = 'active'", (book_id,))
    if not cursor.rowcount:
        return api_error("Book not found.", 404)
    return jsonify({"message": "Book removed."})


@app.get("/api/borrowers")
@login_required
def find_borrowers():
    search = f"%{request.args.get('q', '').strip()}%"
    with get_connection() as connection:
        rows = connection.execute(
            """SELECT id, school_id, name, email, role, department FROM users
               WHERE status = 'active' AND role IN ('Student', 'Faculty')
               AND (school_id LIKE ? OR name LIKE ? OR email LIKE ?)
               ORDER BY name COLLATE NOCASE LIMIT 20""",
            (search, search, search),
        ).fetchall()
    return jsonify({"borrowers": [dict(row) for row in rows]})


@app.get("/api/transactions")
@roles_required("MIS Admin", "Librarian")
def list_transactions():
    try:
        rows = transaction_rows(
            request.args.get("q", "").strip(), request.args.get("from", ""), request.args.get("to", "")
        )
        return jsonify({"transactions": rows})
    except ValueError as error:
        return api_error(str(error))


@app.post("/api/transactions/borrow")
@roles_required("MIS Admin", "Librarian")
def borrow_book():
    data = request.get_json(silent=True) or {}
    try:
        book_id = int(data.get("book_id", 0))
        school_id = clean_text(data, "borrower_school_id", 50)
        due_date = str(data.get("due_date") or (datetime.now(MANILA_TIME).date() + timedelta(days=14)).isoformat())
        date.fromisoformat(due_date)
    except (ValueError, TypeError):
        return api_error("Choose a valid book, borrower school ID, and due date.")

    try:
        with get_connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            book = connection.execute("SELECT id, available_quantity FROM books WHERE id = ?", (book_id,)).fetchone()
            borrower = connection.execute(
                "SELECT id FROM users WHERE school_id = ? AND status = 'active' AND role IN ('Student', 'Faculty')",
                (school_id,),
            ).fetchone()
            if not book:
                return api_error("Book not found.", 404)
            if not borrower:
                return api_error("No active student or faculty member has that school ID.", 404)
            if book["available_quantity"] < 1:
                return api_error("There are no available copies of this book.", 409)
            connection.execute(
                """INSERT INTO book_transactions
                   (book_id, borrower_id, processed_by, borrow_date, due_date)
                   VALUES (?, ?, ?, datetime('now', 'localtime'), ?)""",
                (book_id, borrower["id"], g.user["id"], due_date),
            )
            connection.execute("UPDATE books SET available_quantity = available_quantity - 1 WHERE id = ?", (book_id,))
        return jsonify({"message": "Book borrowed."}), 201
    except sqlite3.IntegrityError:
        return api_error("Unable to create the transaction.", 409)


@app.post("/api/transactions/<int:transaction_id>/return")
@roles_required("MIS Admin", "Librarian")
def return_book(transaction_id):
    with get_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        transaction = connection.execute(
            "SELECT book_id, status FROM book_transactions WHERE id = ?", (transaction_id,)
        ).fetchone()
        if not transaction:
            return api_error("Transaction not found.", 404)
        if transaction["status"] != "borrowed":
            return api_error("This book has already been returned.", 409)
        connection.execute(
            "UPDATE book_transactions SET status = 'returned', return_date = datetime('now', 'localtime') WHERE id = ?",
            (transaction_id,),
        )
        connection.execute(
            "UPDATE books SET available_quantity = available_quantity + 1 WHERE id = ?", (transaction["book_id"],)
        )
    return jsonify({"message": "Book returned."})


@app.get("/api/reports")
@roles_required("MIS Admin", "Librarian")
def report_transactions():
    try:
        rows = transaction_rows(
            request.args.get("q", "").strip(), request.args.get("from", ""), request.args.get("to", "")
        )
        return jsonify({"transactions": rows})
    except ValueError as error:
        return api_error(str(error))


@app.get("/api/dashboard")
@roles_required("MIS Admin", "Librarian")
def dashboard_data():
    today = manila_now()[:10]
    with get_connection() as connection:
        counts = connection.execute(
            """SELECT
                   (SELECT COUNT(*) FROM book_transactions WHERE status = 'borrowed') AS borrowed_books,
                   (SELECT COUNT(*) FROM book_transactions WHERE status = 'borrowed' AND due_date < ?) AS overdue_books,
                   (SELECT COUNT(*) FROM attendance_records a JOIN users u ON u.id = a.person_id
                    WHERE a.time_out IS NULL AND u.status = 'active') AS people_inside"""
        , (today,)).fetchone()
    return jsonify({"stats": dict(counts), "attendance": attendance_rows()[:40]})


def book_activity_rows(overdue_only=False):
    today = manila_now()[:10]
    sql = """
        SELECT t.id, u.school_id, u.name AS borrower_name, b.barcode, b.title,
               t.borrow_date, t.due_date,
               CAST(julianday(?) - julianday(date(t.due_date)) AS INTEGER) AS days_overdue,
               CASE WHEN date(t.due_date) < ? THEN 'Overdue' ELSE 'Borrowed' END AS status
        FROM book_transactions t
        JOIN books b ON b.id = t.book_id
        JOIN users u ON u.id = t.borrower_id
        WHERE t.status = 'borrowed'
    """
    parameters = [today, today]
    if overdue_only:
        sql += " AND date(t.due_date) < ?"
        parameters.append(today)
    sql += " ORDER BY t.due_date, u.name COLLATE NOCASE"
    with get_connection() as connection:
        return [dict(row) for row in connection.execute(sql, parameters).fetchall()]


@app.get("/api/dashboard/people-inside")
@roles_required("MIS Admin", "Librarian")
def dashboard_people_inside():
    with get_connection() as connection:
        rows = connection.execute(
            """SELECT u.school_id, u.name, COALESCE(NULLIF(u.person_type, ''), u.role) AS role,
                      u.department, a.time_in, a.attendance_date
               FROM attendance_records a JOIN users u ON u.id = a.person_id
               WHERE a.time_out IS NULL AND u.status = 'active'
               ORDER BY a.time_in"""
        ).fetchall()
    return jsonify({"count": len(rows), "people": [dict(row) for row in rows]})


@app.get("/api/dashboard/overdue-books")
@roles_required("MIS Admin", "Librarian")
def dashboard_overdue_books():
    rows = book_activity_rows(overdue_only=True)
    return jsonify({"count": len(rows), "books": rows})


@app.get("/api/dashboard/borrowed-books")
@roles_required("MIS Admin", "Librarian")
def dashboard_borrowed_books():
    rows = book_activity_rows()
    return jsonify({"count": len(rows), "books": rows})


@app.get("/api/dashboard/access-logs")
@roles_required("MIS Admin", "Librarian")
def dashboard_access_logs():
    return jsonify({"records": attendance_rows()[:100]})


def attendance_api_response(event_type):
    data = request.get_json(silent=True) or {}
    try:
        school_id = clean_text(data, "school_id", 50)
    except ValueError as error:
        return api_error(str(error))
    timestamp = manila_now()
    with get_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        person = connection.execute(
            """SELECT id, school_id, name, role, person_type, department, status, face_encoding
               FROM users WHERE school_id = ?""",
            (school_id,),
        ).fetchone()
        if not person or person["role"] in ("MIS Admin", "Librarian"):
            return api_error("No registered library person has that school ID.", 404)
        if person["status"] != "active":
            return api_error("Inactive people cannot record attendance.", 403)
        if not person["face_encoding"]:
            return api_error("This person has not completed face registration.", 409)
        active = connection.execute(
            "SELECT id FROM attendance_records WHERE person_id = ? AND time_out IS NULL",
            (person["id"],),
        ).fetchone()
        if event_type == "time_in":
            if active:
                return api_error("This person already has an active Time-in.", 409)
            connection.execute(
                """INSERT INTO attendance_records (person_id, time_in, attendance_date, source, status)
                   VALUES (?, ?, ?, 'face_recognition', 'inside')""",
                (person["id"], timestamp, timestamp[:10]),
            )
        else:
            if not active:
                return api_error("This person has no active Time-in to close.", 409)
            connection.execute(
                """UPDATE attendance_records SET time_out = ?, status = 'completed'
                   WHERE id = ? AND time_out IS NULL""",
                (timestamp, active["id"]),
            )
    return jsonify({
        "event": event_type,
        "timestamp": timestamp,
        "person": {
            "school_id": person["school_id"],
            "name": person["name"],
            "role": person["person_type"] or person["role"],
            "department": person["department"],
        },
    }), 201


@app.get("/api/attendance")
@roles_required("MIS Admin", "Librarian")
def list_attendance():
    try:
        records = attendance_rows(
            request.args.get("q", "").strip(), request.args.get("from", ""), request.args.get("to", ""),
            request.args.get("role", "").strip(), request.args.get("department", "").strip(),
            request.args.get("event", "all").strip(),
        )
        return jsonify({"records": records})
    except ValueError as error:
        return api_error(str(error))


@app.get("/api/reports/attendance")
@roles_required("MIS Admin", "Librarian")
def attendance_report():
    return list_attendance()


@app.post("/api/attendance/time-in")
@iot_required
def attendance_time_in():
    return attendance_api_response("time_in")


@app.post("/api/attendance/time-out")
@iot_required
def attendance_time_out():
    return attendance_api_response("time_out")


@app.get("/api/users")
@roles_required("MIS Admin")
def list_users():
    search = f"%{request.args.get('q', '').strip()}%"
    with get_connection() as connection:
        rows = connection.execute(
            """SELECT id, school_id, name, email, role, department, status, created_at
               FROM users WHERE role IN ('MIS Admin', 'Librarian')
               AND (school_id LIKE ? OR name LIKE ? OR email LIKE ? OR role LIKE ?)
               ORDER BY CASE status WHEN 'active' THEN 0 ELSE 1 END, name COLLATE NOCASE""",
            (search, search, search, search),
        ).fetchall()
    return jsonify({"users": [dict(row) for row in rows]})


def validate_user(data, creating=False):
    school_id = clean_text(data, "school_id", 50)
    name = clean_text(data, "name")
    email = clean_text(data, "email", 254).lower()
    role = clean_text(data, "role", 30)
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
        raise ValueError("Enter a valid email address.")
    if role not in ("MIS Admin", "Librarian", "Student", "Faculty"):
        raise ValueError("Choose a valid role.")
    password = str(data.get("password", ""))
    if creating and role in ("MIS Admin", "Librarian") and len(password) < 8:
        raise ValueError("MIS Admin and Librarian passwords must be at least 8 characters.")
    return {
        "school_id": school_id,
        "name": name,
        "email": email,
        "role": role,
        "department": str(data.get("department", "")).strip()[:100],
        "password": password,
    }


@app.post("/api/users")
@roles_required("MIS Admin")
def create_user():
    data = request.get_json(silent=True) or {}
    try:
        user = validate_user(data, creating=True)
        if user["role"] not in ("MIS Admin", "Librarian"):
            return api_error("Use People Information to add students, faculty, and other library visitors.")
        password_hash = generate_password_hash(user["password"]) if user["role"] in ("MIS Admin", "Librarian") else None
        with get_connection() as connection:
            cursor = connection.execute(
                """INSERT INTO users (school_id, name, email, password_hash, role, department)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (user["school_id"], user["name"], user["email"], password_hash, user["role"], user["department"]),
            )
        return jsonify({"id": cursor.lastrowid, "message": "User added."}), 201
    except (ValueError, TypeError) as error:
        return api_error(str(error))
    except sqlite3.IntegrityError:
        return api_error("School ID or email is already in use.", 409)


@app.patch("/api/users/<int:user_id>")
@roles_required("MIS Admin")
def update_user(user_id):
    data = request.get_json(silent=True) or {}
    try:
        user = validate_user(data)
        fields = {
            "school_id": user["school_id"],
            "name": user["name"],
            "email": user["email"],
            "role": user["role"],
            "department": user["department"],
            "status": "inactive" if data.get("status") == "inactive" else "active",
        }
        if user["password"]:
            if len(user["password"]) < 8:
                return api_error("Password must be at least 8 characters.")
            fields["password_hash"] = generate_password_hash(user["password"])
        if user_id == g.user["id"] and fields["status"] != "active":
            return api_error("You cannot deactivate your own account.", 409)
        with get_connection() as connection:
            current = connection.execute(
                "SELECT id, role, password_hash FROM users WHERE id = ?", (user_id,)
            ).fetchone()
            if not current:
                return api_error("User not found.", 404)
            if current["role"] not in ("MIS Admin", "Librarian"):
                return api_error("Use People Information to update this record.", 404)
            if fields["role"] in ("MIS Admin", "Librarian") and not user["password"] and not current["password_hash"]:
                return api_error("Set a password before assigning a staff login role.")
            if current["role"] == "MIS Admin" and (fields["role"] != "MIS Admin" or fields["status"] != "active"):
                admins = connection.execute(
                    "SELECT COUNT(*) FROM users WHERE role = 'MIS Admin' AND status = 'active'"
                ).fetchone()[0]
                if admins <= 1:
                    return api_error("Keep at least one active MIS Admin account.", 409)
            assignments = ", ".join(f"{field} = ?" for field in fields)
            connection.execute(
                f"UPDATE users SET {assignments} WHERE id = ?", (*fields.values(), user_id)
            )
        return jsonify({"message": "User updated."})
    except (ValueError, TypeError) as error:
        return api_error(str(error))
    except sqlite3.IntegrityError:
        return api_error("School ID or email is already in use.", 409)


@app.delete("/api/users/<int:user_id>")
@roles_required("MIS Admin")
def deactivate_user(user_id):
    if user_id == g.user["id"]:
        return api_error("You cannot deactivate your own account.", 409)
    with get_connection() as connection:
        user = connection.execute("SELECT role FROM users WHERE id = ?", (user_id,)).fetchone()
        if not user or user["role"] not in ("MIS Admin", "Librarian"):
            return api_error("User not found.", 404)
        if user["role"] == "MIS Admin":
            admins = connection.execute(
                "SELECT COUNT(*) FROM users WHERE role = 'MIS Admin' AND status = 'active'"
            ).fetchone()[0]
            if admins <= 1:
                return api_error("Keep at least one active MIS Admin account.", 409)
        connection.execute("UPDATE users SET status = 'inactive' WHERE id = ?", (user_id,))
    return jsonify({"message": "User deactivated."})


def person_role_expression():
    return "COALESCE(NULLIF(person_type, ''), role)"


def validate_person(data):
    school_id = clean_text(data, "school_id", 50)
    name = clean_text(data, "name")
    person_role = clean_text(data, "role", 30)
    if person_role not in ("Student", "Faculty", "Staff", "Other"):
        raise ValueError("Choose Student, Faculty, Staff, or Other.")
    department = str(data.get("department", "")).strip()
    contact = str(data.get("contact", "")).strip()
    if len(department) > 100 or len(contact) > 80:
        raise ValueError("Department or contact information is too long.")
    status = str(data.get("status", "active")).strip().lower()
    if status not in ("active", "inactive"):
        raise ValueError("Status must be Active or Inactive.")
    return {
        "school_id": school_id,
        "name": name,
        "person_role": person_role,
        "role": person_role if person_role in ("Student", "Faculty") else "Student",
        "department": department,
        "contact": contact,
        "status": status,
    }


@app.get("/api/people")
@roles_required("MIS Admin")
def list_people():
    search = f"%{request.args.get('q', '').strip()}%"
    person_role = request.args.get("role", "").strip()
    with get_connection() as connection:
        rows = connection.execute(
            f"""SELECT id, school_id, name, {person_role_expression()} AS role,
                       department, contact, status, created_at,
                       CASE WHEN face_image = '' THEN 0 ELSE 1 END AS has_face_image,
                       CASE WHEN face_encoding = '' THEN 0 ELSE 1 END AS face_registered
                FROM users
                WHERE role NOT IN ('MIS Admin', 'Librarian')
                  AND (school_id LIKE ? OR name LIKE ? OR department LIKE ? OR {person_role_expression()} LIKE ?)
                  AND (? = '' OR {person_role_expression()} = ?)
                ORDER BY CASE status WHEN 'active' THEN 0 ELSE 1 END, name COLLATE NOCASE""",
            (search, search, search, search, person_role, person_role),
        ).fetchall()
    return jsonify({"people": [dict(row) for row in rows]})


@app.post("/api/people")
@roles_required("MIS Admin")
def create_person():
    data = request.get_json(silent=True) or {}
    try:
        person = validate_person(data)
        email = person["school_id"].lower() + "@people.smartlibrary.local"
        with get_connection() as connection:
            cursor = connection.execute(
                """INSERT INTO users
                   (school_id, name, email, role, person_type, department, contact, status)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (person["school_id"], person["name"], email, person["role"], person["person_role"],
                 person["department"], person["contact"], person["status"]),
            )
        return jsonify({"id": cursor.lastrowid, "message": "People information saved."}), 201
    except (ValueError, TypeError) as error:
        return api_error(str(error))
    except sqlite3.IntegrityError:
        return api_error("That School ID is already registered.", 409)


@app.put("/api/people/<int:person_id>")
@roles_required("MIS Admin")
def update_person(person_id):
    data = request.get_json(silent=True) or {}
    try:
        person = validate_person(data)
        with get_connection() as connection:
            current = connection.execute(
                "SELECT role FROM users WHERE id = ?", (person_id,)
            ).fetchone()
            if not current or current["role"] in ("MIS Admin", "Librarian"):
                return api_error("People record not found.", 404)
            connection.execute(
                """UPDATE users SET school_id = ?, name = ?, role = ?, person_type = ?,
                   department = ?, contact = ?, status = ? WHERE id = ?""",
                (person["school_id"], person["name"], person["role"], person["person_role"],
                 person["department"], person["contact"], person["status"], person_id),
            )
            if person["status"] == "inactive":
                timestamp = manila_now()
                connection.execute(
                    """UPDATE attendance_records SET time_out = ?, status = 'admin_closed'
                       WHERE person_id = ? AND time_out IS NULL""",
                    (timestamp, person_id),
                )
        return jsonify({"message": "People information updated."})
    except (ValueError, TypeError) as error:
        return api_error(str(error))
    except sqlite3.IntegrityError:
        return api_error("That School ID is already registered.", 409)


@app.delete("/api/people/<int:person_id>")
@roles_required("MIS Admin")
def deactivate_person(person_id):
    with get_connection() as connection:
        person = connection.execute(
            "SELECT role FROM users WHERE id = ?", (person_id,)
        ).fetchone()
        if not person or person["role"] in ("MIS Admin", "Librarian"):
            return api_error("People record not found.", 404)
        timestamp = manila_now()
        connection.execute("UPDATE users SET status = 'inactive' WHERE id = ?", (person_id,))
        connection.execute(
            """UPDATE attendance_records SET time_out = ?, status = 'admin_closed'
               WHERE person_id = ? AND time_out IS NULL""",
            (timestamp, person_id),
        )
    return jsonify({"message": "Person deactivated. Any open attendance session was closed by an administrator."})


def uploaded_face_extension(image_data):
    return cover_extension(image_data)


def save_person_face(person_id, upload):
    image_data = upload.stream.read(MAX_COVER_SIZE + 1)
    if len(image_data) > MAX_COVER_SIZE:
        return None, api_error("Face images must be 5 MB or smaller.", 413)
    extension = uploaded_face_extension(image_data)
    if not extension:
        return None, api_error("Choose a valid PNG, JPEG, GIF, or WebP image.")
    FACE_DIRECTORY.mkdir(parents=True, exist_ok=True)
    filename = secrets.token_hex(16) + extension
    (FACE_DIRECTORY / filename).write_bytes(image_data)
    with get_connection() as connection:
        person = connection.execute(
            "SELECT face_image, role FROM users WHERE id = ?", (person_id,)
        ).fetchone()
        if not person or person["role"] in ("MIS Admin", "Librarian"):
            (FACE_DIRECTORY / filename).unlink(missing_ok=True)
            return None, api_error("People record not found.", 404)
        connection.execute(
            "UPDATE users SET face_image = ?, face_encoding = '' WHERE id = ?",
            (filename, person_id),
        )
    old_filename = person["face_image"]
    if old_filename and Path(old_filename).name == old_filename:
        (FACE_DIRECTORY / old_filename).unlink(missing_ok=True)
    return filename, None


@app.post("/api/people/<int:person_id>/face")
@roles_required("MIS Admin")
def upload_person_face(person_id):
    upload = request.files.get("face_image")
    if not upload:
        return api_error("Choose a face image to upload.")
    _, error = save_person_face(person_id, upload)
    if error:
        return error
    return jsonify({"message": "Face image saved. Face registration is pending IoT processing."})


@app.get("/api/people/<int:person_id>/face-image")
@roles_required("MIS Admin")
def get_person_face(person_id):
    with get_connection() as connection:
        person = connection.execute("SELECT face_image FROM users WHERE id = ?", (person_id,)).fetchone()
    if not person or not person["face_image"]:
        abort(404)
    return send_from_directory(FACE_DIRECTORY, person["face_image"], max_age=0)


@app.delete("/api/people/<int:person_id>/face")
@roles_required("MIS Admin")
def reset_person_face(person_id):
    with get_connection() as connection:
        person = connection.execute("SELECT face_image, role FROM users WHERE id = ?", (person_id,)).fetchone()
        if not person or person["role"] in ("MIS Admin", "Librarian"):
            return api_error("People record not found.", 404)
        connection.execute("UPDATE users SET face_image = '', face_encoding = '' WHERE id = ?", (person_id,))
    if person["face_image"] and Path(person["face_image"]).name == person["face_image"]:
        (FACE_DIRECTORY / person["face_image"]).unlink(missing_ok=True)
    return jsonify({"message": "Face image and recognition data removed."})


@app.get("/api/system-users")
@roles_required("MIS Admin")
def list_system_users():
    role = request.args.get("role", "").strip()
    if role and role not in ("MIS Admin", "Librarian"):
        return api_error("Choose MIS Admin or Librarian.")
    search = f"%{request.args.get('q', '').strip()}%"
    with get_connection() as connection:
        rows = connection.execute(
            """SELECT id, school_id, name, email, role, department, status, created_at, last_login_at
               FROM users WHERE role IN ('MIS Admin', 'Librarian')
               AND (? = '' OR role = ?) AND (name LIKE ? OR email LIKE ? OR school_id LIKE ?)
               ORDER BY role, name COLLATE NOCASE""",
            (role, role, search, search, search),
        ).fetchall()
    return jsonify({"users": [dict(row) for row in rows]})


@app.post("/api/system-users")
@roles_required("MIS Admin")
def create_system_user():
    data = request.get_json(silent=True) or {}
    try:
        user = validate_user(data, creating=True)
        if user["role"] not in ("MIS Admin", "Librarian"):
            return api_error("System accounts must be MIS Admin or Librarian.")
        with get_connection() as connection:
            cursor = connection.execute(
                """INSERT INTO users (school_id, name, email, password_hash, role, department)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (user["school_id"], user["name"], user["email"], generate_password_hash(user["password"]),
                 user["role"], user["department"]),
            )
        return jsonify({"id": cursor.lastrowid, "message": "System account added."}), 201
    except (ValueError, TypeError) as error:
        return api_error(str(error))
    except sqlite3.IntegrityError:
        return api_error("School ID or email is already in use.", 409)


@app.put("/api/system-users/<int:user_id>")
@roles_required("MIS Admin")
def update_system_user(user_id):
    data = request.get_json(silent=True) or {}
    data["role"] = str(data.get("role", "")).strip()
    if data["role"] not in ("MIS Admin", "Librarian"):
        return api_error("System accounts must be MIS Admin or Librarian.")
    with get_connection() as connection:
        row = connection.execute("SELECT role FROM users WHERE id = ?", (user_id,)).fetchone()
        if not row or row["role"] not in ("MIS Admin", "Librarian"):
            return api_error("System account not found.", 404)
    return update_user(user_id)


@app.delete("/api/system-users/<int:user_id>")
@roles_required("MIS Admin")
def deactivate_system_user(user_id):
    with get_connection() as connection:
        row = connection.execute("SELECT role FROM users WHERE id = ?", (user_id,)).fetchone()
        if not row or row["role"] not in ("MIS Admin", "Librarian"):
            return api_error("System account not found.", 404)
    return deactivate_user(user_id)


@app.get("/api/iot/face-enrollments")
@iot_required
def iot_face_enrollments():
    with get_connection() as connection:
        rows = connection.execute(
            f"""SELECT id, school_id, name, {person_role_expression()} AS role, department
                FROM users WHERE status = 'active' AND role NOT IN ('MIS Admin', 'Librarian')
                  AND face_image != '' AND face_encoding = '' ORDER BY id"""
        ).fetchall()
    return jsonify({"people": [dict(row) for row in rows]})


@app.get("/api/iot/people/<int:person_id>/face-image")
@iot_required
def iot_person_face_image(person_id):
    with get_connection() as connection:
        person = connection.execute(
            "SELECT face_image FROM users WHERE id = ? AND status = 'active'", (person_id,)
        ).fetchone()
    if not person or not person["face_image"]:
        abort(404)
    return send_from_directory(FACE_DIRECTORY, person["face_image"], max_age=0)


@app.put("/api/iot/people/<int:person_id>/face-encoding")
@iot_required
def iot_store_face_encoding(person_id):
    data = request.get_json(silent=True) or {}
    encoding = data.get("encoding")
    if not isinstance(encoding, list) or len(encoding) != 128:
        return api_error("Face encoding must contain 128 numeric values.")
    try:
        values = [float(value) for value in encoding]
    except (TypeError, ValueError):
        return api_error("Face encoding values must be numeric.")
    if not all(math.isfinite(value) for value in values):
        return api_error("Face encoding contains an invalid number.")
    magnitude = math.sqrt(sum(value * value for value in values))
    if magnitude < 0.000001:
        return api_error("Face encoding cannot be empty.")
    normalized = [value / magnitude for value in values]
    with get_connection() as connection:
        cursor = connection.execute(
            """UPDATE users SET face_encoding = ? WHERE id = ? AND status = 'active'
               AND role NOT IN ('MIS Admin', 'Librarian') AND face_image != ''""",
            (json.dumps(normalized, separators=(",", ":")), person_id),
        )
        if cursor.rowcount == 0:
            return api_error("Active person with an uploaded face image not found.", 404)
    return jsonify({"message": "Face recognition data registered."})


@app.get("/api/iot/face-templates")
@iot_required
def iot_face_templates():
    with get_connection() as connection:
        rows = connection.execute(
            f"""SELECT u.id, u.school_id, u.name, {person_role_expression()} AS role,
                       u.department, u.status, u.face_encoding,
                       EXISTS(SELECT 1 FROM attendance_records a WHERE a.person_id = u.id AND a.time_out IS NULL) AS is_inside
                FROM users u WHERE u.role NOT IN ('MIS Admin', 'Librarian')
                  AND u.face_encoding != '' ORDER BY u.id"""
        ).fetchall()
    templates = []
    for row in rows:
        item = dict(row)
        item["encoding"] = json.loads(item.pop("face_encoding"))
        item["is_inside"] = bool(item["is_inside"])
        templates.append(item)
    return jsonify({"people": templates})


@app.get("/")
def welcome_page():
    return send_from_directory(PROJECT_ROOT, "welcome.html")


@app.route("/<path:requested_path>", methods=["GET", "HEAD"])
def frontend_files(requested_path):
    lower_path = requested_path.lower()
    if (lower_path.startswith((".", "backend/", "face_recognition_iot/"))
            or lower_path.startswith("smart_library.db")):
        abort(404)
    file_path = (PROJECT_ROOT / requested_path).resolve()
    if not file_path.is_relative_to(PROJECT_ROOT) or not file_path.is_file():
        abort(404)

    normalized = requested_path.replace("\\", "/")
    if normalized.lower().endswith(".html"):
        role = g.user["role"] if g.user else None
        if normalized.startswith("MIS_ADMIN/") and role != "MIS Admin":
            return redirect("/LogIn.html" if not role else "/LIBRARIAN/dashboard.html")
        if normalized.startswith("LIBRARIAN/") and role != "Librarian":
            return redirect("/LogIn.html" if not role else "/MIS_ADMIN/dashboard.html")
        if role and normalized == "LogIn.html":
            return redirect("/MIS_ADMIN/dashboard.html" if role == "MIS Admin" else "/LIBRARIAN/dashboard.html")
        if normalized in {"LogIn.html", "welcome.html", "EmailVerification.html", "VerificationCode.html"}:
            return send_from_directory(PROJECT_ROOT, requested_path)
        if normalized in {"ChangePassword.html"} and not role:
            return redirect("/LogIn.html")
    return send_from_directory(PROJECT_ROOT, requested_path)


@app.errorhandler(sqlite3.Error)
def handle_database_error(error):
    app.logger.exception("Database request failed: %s", error)
    return jsonify({"error": "A database error occurred. Please try again."}), 500


@app.errorhandler(413)
def handle_large_upload(error):
    return api_error("Book images must be 5 MB or smaller.", 413)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", "5000")), debug=os.environ.get("FLASK_DEBUG") == "1")