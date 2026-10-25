"""Copy the local SQLite database into an empty PostgreSQL database."""

import argparse
import os
import sqlite3
import sys
from pathlib import Path

import psycopg2
from dotenv import load_dotenv
from psycopg2 import extensions, sql
from psycopg2.extras import execute_values


ROOT_DIRECTORY = Path(__file__).resolve().parent
SQLITE_PATH = ROOT_DIRECTORY / "smart_library.db"
BATCH_SIZE = 500
TABLE_COLUMNS = {
    "users": (
        "id", "school_id", "name", "email", "password_hash", "role", "department",
        "status", "created_at", "person_type", "contact", "face_image", "face_encoding",
        "last_login_at",
    ),
    "books": (
        "id", "barcode", "title", "author", "category", "published_date", "quantity",
        "available_quantity", "cover_image", "status", "created_at", "book_number",
    ),
    "book_transactions": (
        "id", "book_id", "borrower_id", "processed_by", "borrower_school_id",
        "borrower_name", "borrower_department", "processor_school_id", "processor_name",
        "processor_department", "barcode", "institutional_email", "borrow_date",
        "due_date", "return_date", "status", "created_at",
    ),
    "attendance_records": (
        "id", "person_id", "person_school_id", "person_name", "person_role",
        "person_department", "time_in", "time_out", "attendance_date", "source",
        "status", "created_at",
    ),
    "password_recovery_requests": (
        "id", "user_id", "email", "code_hash", "token_hash", "reset_token_hash",
        "verify_attempts", "verified_at", "status", "requested_at", "expires_at",
        "approved_by", "approved_at", "reviewed_at", "used_at", "created_at",
    ),
    "password_recovery_audit": (
        "id", "request_id", "actor_id", "action", "created_at",
    ),
    "password_recovery_rate_limits": (
        "action", "key_hash", "window_start", "attempts",
    ),
}


def open_sqlite_read_only():
    if not SQLITE_PATH.is_file():
        raise FileNotFoundError(f"SQLite source database not found: {SQLITE_PATH}")
    connection = sqlite3.connect(f"{SQLITE_PATH.as_uri()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def validate_columns(sqlite_connection, postgres_cursor):
    for table, expected_columns in TABLE_COLUMNS.items():
        sqlite_columns = tuple(
            row["name"] for row in sqlite_connection.execute(f'PRAGMA table_info("{table}")')
        )
        # Column order differs between databases created fresh and ones upgraded
        # with ALTER TABLE; every query names its columns, so compare as sets.
        if set(sqlite_columns) != set(expected_columns):
            raise RuntimeError(
                f"SQLite columns for {table} do not match the migration column list."
            )

        postgres_cursor.execute(
            """SELECT column_name
               FROM information_schema.columns
               WHERE table_schema = current_schema() AND table_name = %s
               ORDER BY ordinal_position""",
            (table,),
        )
        postgres_columns = tuple(row[0] for row in postgres_cursor.fetchall())
        if set(postgres_columns) != set(expected_columns):
            raise RuntimeError(
                f"PostgreSQL columns for {table} do not match the migration column list."
            )


def get_postgres_column_types(cursor):
    column_types = {}
    for table in TABLE_COLUMNS:
        cursor.execute(
            """SELECT column_name, data_type
               FROM information_schema.columns
               WHERE table_schema = current_schema() AND table_name = %s""",
            (table,),
        )
        column_types[table] = {row[0]: row[1] for row in cursor.fetchall()}
    return column_types


def adapt_value(value, target_type, table, column):
    if value is None:
        return None
    if isinstance(value, bytes):
        if target_type != "bytea":
            raise TypeError(
                f"SQLite contains a BLOB in {table}.{column}, but PostgreSQL expects {target_type}."
            )
        return psycopg2.Binary(value)
    if target_type == "boolean" and isinstance(value, int):
        if value not in (0, 1):
            raise ValueError(
                f"SQLite boolean value in {table}.{column} is not 0 or 1."
            )
        return bool(value)
    return value


def count_rows(cursor, table):
    cursor.execute(sql.SQL("SELECT COUNT(*) FROM {}").format(sql.Identifier(table)))
    return cursor.fetchone()[0]


def insert_table(sqlite_connection, postgres_cursor, table, column_types):
    columns = TABLE_COLUMNS[table]
    quoted_columns = ", ".join(f'"{column}"' for column in columns)
    source_cursor = sqlite_connection.execute(
        f'SELECT {quoted_columns} FROM "{table}" ORDER BY "{columns[0]}"'
    )
    insert_query = sql.SQL("INSERT INTO {} ({}) VALUES %s").format(
        sql.Identifier(table),
        sql.SQL(", ").join(sql.Identifier(column) for column in columns),
    )

    copied_rows = 0
    while batch := source_cursor.fetchmany(BATCH_SIZE):
        values = [
            tuple(
                adapt_value(value, column_types[table][column], table, column)
                for column, value in zip(columns, row)
            )
            for row in batch
        ]
        execute_values(postgres_cursor, insert_query.as_string(postgres_cursor), values)
        copied_rows += len(values)
    return copied_rows


def get_identity_sequence(cursor, table):
    cursor.execute(
        "SELECT pg_get_serial_sequence(quote_ident(current_schema()) || '.' || quote_ident(%s), 'id')",
        (table,),
    )
    sequence_name = cursor.fetchone()[0]
    if sequence_name is None:
        raise RuntimeError(f"No identity sequence found for {table}.")
    return sequence_name


def identity_sequence_state(cursor, table):
    sequence_name = get_identity_sequence(cursor, table)
    sequence_parts = sequence_name.split(".")
    cursor.execute(
        sql.SQL("SELECT last_value, is_called FROM {}").format(
            sql.Identifier(*sequence_parts)
        )
    )
    return sequence_name, cursor.fetchone()


def capture_identity_sequence_states(cursor):
    return [
        identity_sequence_state(cursor, table)
        for table in TABLE_COLUMNS
        if table != "password_recovery_rate_limits"
    ]


def reset_identity_sequences(cursor):
    for table in TABLE_COLUMNS:
        if table == "password_recovery_rate_limits":
            continue
        sequence_name = get_identity_sequence(cursor, table)
        cursor.execute(sql.SQL("SELECT COALESCE(MAX(id), 0) + 1 FROM {}").format(
            sql.Identifier(table)
        ))
        next_id = cursor.fetchone()[0]
        cursor.execute(
            "SELECT setval(%s::regclass, %s, false)",
            (sequence_name, next_id),
        )


def restore_identity_sequences(cursor, previous_states):
    for sequence_name, (last_value, is_called) in previous_states:
        cursor.execute(
            "SELECT setval(%s::regclass, %s, %s)",
            (sequence_name, last_value, is_called),
        )


def report_spot_checks(sqlite_connection, postgres_cursor):
    columns = ("school_id", "name", "role", "status", "face_encoding")
    column_sql = sql.SQL(", ").join(sql.Identifier(column) for column in columns)
    sqlite_rows = sqlite_connection.execute(
        "SELECT id, school_id, name, role, status, face_encoding FROM users ORDER BY id LIMIT 3"
    ).fetchall()
    print("\nUser spot check (field values must match; encoding content is not printed):")
    for source_row in sqlite_rows:
        postgres_cursor.execute(
            sql.SQL("SELECT {} FROM users WHERE id = %s").format(column_sql),
            (source_row["id"],),
        )
        destination_row = postgres_cursor.fetchone()
        if destination_row is None:
            raise RuntimeError(f"User spot check failed for id {source_row['id']}.")

        values_match = all(
            source_row[column] == destination_row[index]
            for index, column in enumerate(columns[:-1])
        )
        source_has_encoding = source_row["face_encoding"] not in (None, "")
        destination_has_encoding = destination_row[-1] not in (None, "")
        encoding_flag_matches = source_has_encoding == destination_has_encoding
        print(
            f"id={source_row['id']}: school_id/name/role/status match={values_match}; "
            f"face_encoding non-empty SQLite={source_has_encoding}, "
            f"PostgreSQL={destination_has_encoding}"
        )
        if not values_match or not encoding_flag_matches:
            raise RuntimeError(f"User spot check failed for id {source_row['id']}.")
    if not sqlite_rows:
        print("No users are available to spot-check.")


def run_migration(dry_run):
    load_dotenv(ROOT_DIRECTORY / ".env")
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is not set in the project .env file or environment.")

    sqlite_connection = open_sqlite_read_only()
    postgres_connection = None
    previous_sequence_states = []
    sequence_reset_started = False
    try:
        dsn = extensions.make_dsn(database_url, sslmode="require")
        postgres_connection = psycopg2.connect(dsn)
        postgres_connection.autocommit = False
        # Create the tables if the web service has not started yet (idempotent).
        with postgres_connection.cursor() as cursor:
            cursor.execute(
                (ROOT_DIRECTORY / "backend" / "schema_postgres.sql").read_text(encoding="utf-8")
            )
        postgres_connection.commit()
        with postgres_connection.cursor() as cursor:
            cursor.execute(
                sql.SQL("LOCK TABLE {} IN ACCESS EXCLUSIVE MODE").format(
                    sql.SQL(", ").join(sql.Identifier(table) for table in TABLE_COLUMNS)
                )
            )
            destination_counts = {
                table: count_rows(cursor, table) for table in TABLE_COLUMNS
            }
            print("Destination rows before migration:")
            for table, count in destination_counts.items():
                print(f"  {table}: {count}")
            if any(destination_counts.values()):
                postgres_connection.rollback()
                print(
                    "Refusing to migrate: every destination table must be empty.",
                    file=sys.stderr,
                )
                return 2

            validate_columns(sqlite_connection, cursor)
            column_types = get_postgres_column_types(cursor)
            source_counts = {
                table: sqlite_connection.execute(
                    f'SELECT COUNT(*) FROM "{table}"'
                ).fetchone()[0]
                for table in TABLE_COLUMNS
            }

            for table in TABLE_COLUMNS:
                copied_count = insert_table(
                    sqlite_connection, cursor, table, column_types
                )
                if copied_count != source_counts[table]:
                    raise RuntimeError(
                        f"Copied row count for {table} does not match its SQLite count."
                    )

            destination_after_counts = {
                table: count_rows(cursor, table) for table in TABLE_COLUMNS
            }
            print("\nRow counts (PostgreSQL counts are before dry-run rollback):")
            print(f"{'Table':38} {'SQLite source':>14} {'PostgreSQL':>14}")
            counts_match = True
            for table in TABLE_COLUMNS:
                source_count = source_counts[table]
                destination_count = destination_after_counts[table]
                counts_match = counts_match and source_count == destination_count
                print(f"{table:38} {source_count:14} {destination_count:14}")
            if not counts_match:
                raise RuntimeError("One or more source and destination row counts differ.")

            report_spot_checks(sqlite_connection, cursor)
            previous_sequence_states = capture_identity_sequence_states(cursor)
            sequence_reset_started = True
            reset_identity_sequences(cursor)
            if dry_run:
                postgres_connection.rollback()
                with postgres_connection.cursor() as cursor:
                    restore_identity_sequences(cursor, previous_sequence_states)
                postgres_connection.commit()
                print("\nDry run complete; copied data was rolled back.")
                return 0

            postgres_connection.commit()
            print("\nMigration committed successfully.")
            return 0
    except Exception as error:
        if postgres_connection is not None:
            postgres_connection.rollback()
            if sequence_reset_started and previous_sequence_states:
                try:
                    with postgres_connection.cursor() as cursor:
                        restore_identity_sequences(cursor, previous_sequence_states)
                except Exception:
                    print(
                        "Warning: sequence state restoration also failed.",
                        file=sys.stderr,
                    )
                else:
                    postgres_connection.commit()
        print(
            f"Migration failed: {type(error).__name__}; PostgreSQL changes were rolled back.",
            file=sys.stderr,
        )
        return 1
    finally:
        sqlite_connection.close()
        if postgres_connection is not None:
            postgres_connection.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="copy and validate all rows, then roll back instead of committing",
    )
    arguments = parser.parse_args()
    return run_migration(arguments.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
