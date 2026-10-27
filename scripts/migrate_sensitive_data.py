#!/usr/bin/env python3
"""Operator-run, resumable encryption migration for user_details."""

import argparse
import sys
from pathlib import Path

from flaskr import create_app
from flaskr.db import connect_db
from flaskr.pii import (
    ENCRYPTED_PREFIX,
    PROFILE_FIELDS,
    configured_key,
    decrypt_value,
    decrypt_email,
    email_lookup,
    encrypt_email,
    encrypt_legacy_profile,
)


TEXT_COLUMNS = tuple(PROFILE_FIELDS)
ALTER_COLUMNS_SQL = ", ".join(
    f"MODIFY COLUMN `{name}` VARCHAR(1024) NULL" for name in TEXT_COLUMNS
)


def column_names(cursor):
    cursor.execute("SHOW COLUMNS FROM user_details")
    rows = cursor.fetchall()
    return {row["Field"] if isinstance(row, dict) else row[0] for row in rows}


def fetch_rows(cursor):
    columns = ", ".join(f"`{name}`" for name in TEXT_COLUMNS)
    cursor.execute(f"SELECT id, user_id, {columns} FROM user_details ORDER BY id")
    fetched = cursor.fetchall()
    if fetched and isinstance(fetched[0], dict):
        return fetched
    names = ["id", "user_id", *TEXT_COLUMNS]
    return [dict(zip(names, row)) for row in fetched]


def fetch_users(cursor):
    cursor.execute("SHOW COLUMNS FROM user")
    columns = cursor.fetchall()
    names = {row["Field"] if isinstance(row, dict) else row[0] for row in columns}
    selected = "id, username, email, email_lookup" if "email_lookup" in names else "id, username, email"
    cursor.execute(f"SELECT {selected} FROM user ORDER BY id")
    fetched = cursor.fetchall()
    if fetched and isinstance(fetched[0], dict):
        return fetched
    fields = selected.split(", ")
    return [dict(zip(fields, row)) for row in fetched]


def needs_encryption(value):
    return value not in (None, "") and not (
        isinstance(value, str) and value.startswith(ENCRYPTED_PREFIX)
    )


def invalid_encrypted_values(rows, key):
    invalid = 0
    for row in rows:
        for field in TEXT_COLUMNS:
            value = row.get(field)
            if isinstance(value, str) and value.startswith(ENCRYPTED_PREFIX):
                try:
                    decrypt_value(value, field, row.get("user_id"), key)
                except Exception:
                    invalid += 1
    return invalid


def user_email_values(user, key):
    stored_email = user["email"]
    if isinstance(stored_email, str) and stored_email.startswith(ENCRYPTED_PREFIX):
        plaintext_email = decrypt_email(stored_email, user["username"], key)
        ciphertext = stored_email
    else:
        plaintext_email = stored_email
        ciphertext = encrypt_email(plaintext_email, user["username"], key)
    return ciphertext, email_lookup(plaintext_email, key)


def ensure_user_email_schema(cursor):
    cursor.execute("SHOW COLUMNS FROM user")
    columns = cursor.fetchall()
    names = {row["Field"] if isinstance(row, dict) else row[0] for row in columns}
    if "email_lookup" not in names:
        cursor.execute("ALTER TABLE user ADD COLUMN email_lookup CHAR(64) NULL")
    cursor.execute("ALTER TABLE user MODIFY COLUMN email VARCHAR(1024) NOT NULL")


def ensure_email_lookup_index(cursor):
    cursor.execute("SHOW INDEX FROM user")
    indexes = cursor.fetchall()
    has_unique_lookup = any(
        row.get("Column_name") == "email_lookup" and int(row.get("Non_unique", 1)) == 0
        for row in indexes
    ) if indexes and isinstance(indexes[0], dict) else any(
        row[4] == "email_lookup" and int(row[1]) == 0 for row in indexes
    )
    cursor.execute("ALTER TABLE user MODIFY COLUMN email_lookup CHAR(64) NOT NULL")
    if not has_unique_lookup:
        cursor.execute("ALTER TABLE user ADD UNIQUE KEY uq_user_email_lookup (email_lookup)")


def email_lookup_schema_is_ready(cursor):
    cursor.execute("SHOW COLUMNS FROM user")
    columns = cursor.fetchall()
    lookup_column = next((
        row for row in columns
        if (row.get("Field") if isinstance(row, dict) else row[0]) == "email_lookup"
    ), None)
    if not lookup_column:
        return False
    nullable = (lookup_column.get("Null") if isinstance(lookup_column, dict)
                else lookup_column[2])
    cursor.execute("SHOW INDEX FROM user")
    indexes = cursor.fetchall()
    if indexes and isinstance(indexes[0], dict):
        unique_lookup = any(row.get("Column_name") == "email_lookup"
                            and int(row.get("Non_unique", 1)) == 0 for row in indexes)
    else:
        unique_lookup = any(row[4] == "email_lookup" and int(row[1]) == 0 for row in indexes)
    return nullable == "NO" and unique_lookup


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--apply", action="store_true", help="Apply the migration")
    action.add_argument("--verify", action="store_true", help="Fail if plaintext remains")
    parser.add_argument("--backup-file", help="Path to a completed, non-empty SQL backup (required with --apply)")
    args = parser.parse_args(argv)

    if args.apply:
        if not args.backup_file:
            parser.error("--apply requires --backup-file pointing to a completed backup")
        backup = Path(args.backup_file)
        if not backup.is_file() or backup.stat().st_size == 0:
            parser.error("The backup file must exist and be non-empty before migration")

    app = create_app()
    with app.app_context():
        key = configured_key()
        db = connect_db()
        try:
            cursor = db.cursor()
            columns = column_names(cursor)
            missing = set(TEXT_COLUMNS) - columns
            if missing:
                raise RuntimeError("Required user_details columns are missing; no migration applied.")

            rows = fetch_rows(cursor)
            users = fetch_users(cursor)
            plaintext_count = sum(
                needs_encryption(row.get(field))
                for row in rows for field in TEXT_COLUMNS
            )
            encrypted_count = sum(
                isinstance(row.get(field), str) and row[field].startswith(ENCRYPTED_PREFIX)
                for row in rows for field in TEXT_COLUMNS
            )
            invalid_count = invalid_encrypted_values(rows, key)
            for user in users:
                email = user.get("email")
                if isinstance(email, str) and email.startswith(ENCRYPTED_PREFIX):
                    try:
                        decrypt_email(email, user["username"], key)
                    except Exception:
                        invalid_count += 1
            user_plaintext = sum(
                bool(user.get("email")) and not str(user["email"]).startswith(ENCRYPTED_PREFIX)
                for user in users
            )
            email_index_errors = 0
            for user in users:
                email = user.get("email")
                if isinstance(email, str) and email.startswith(ENCRYPTED_PREFIX):
                    try:
                        plaintext_email = decrypt_email(email, user["username"], key)
                    except Exception:
                        continue
                    if user.get("email_lookup") != email_lookup(plaintext_email, key):
                        email_index_errors += 1
            email_schema_ready = email_lookup_schema_is_ready(cursor)

            if args.verify:
                if plaintext_count or user_plaintext or invalid_count or email_index_errors or not email_schema_ready:
                    print(f"Verification failed: {plaintext_count} plaintext profile values, {user_plaintext} plaintext email addresses, {invalid_count} invalid encrypted values, {email_index_errors} email index mismatches, email schema ready={email_schema_ready}.")
                    return 1
                print(f"Verification passed: {encrypted_count} encrypted profile values; no plaintext profile fields or email addresses detected.")
                return 0

            if not args.apply:
                user_encrypted = sum(
                    isinstance(user.get("email"), str) and user["email"].startswith(ENCRYPTED_PREFIX)
                    for user in users
                )
                print(f"Dry run: {len(rows)} profile rows; {plaintext_count} plaintext profile values; {encrypted_count} encrypted profile markers; {user_plaintext} plaintext email addresses; {user_encrypted} encrypted email markers; {invalid_count} markers that failed authentication.")
                print("No data or schema was changed. Back up the database, then use --apply --backup-file.")
                return 0

            if invalid_count:
                raise RuntimeError("Some encrypted markers failed authentication; resolve them before migration.")
            if email_index_errors:
                raise RuntimeError("Some email lookup indexes do not match the encrypted addresses; resolve them before migration.")

            # Widen typed/narrow columns before writing ciphertext. This ALTER
            # preserves rows, IDs, and foreign keys; MySQL DDL is not transactional.
            ensure_user_email_schema(cursor)
            cursor.execute(f"ALTER TABLE user_details {ALTER_COLUMNS_SQL}")
            db.commit()

            for user in users:
                encrypted_email, lookup = user_email_values(user, key)
                cursor.execute(
                    "UPDATE user SET email=%s, email_lookup=%s WHERE id=%s",
                    (encrypted_email, lookup, user["id"]),
                )
                db.commit()

            updated_fields = 0
            for row in rows:
                encrypted = encrypt_legacy_profile(row, row["user_id"], key)
                if not encrypted:
                    continue
                assignments = ", ".join(f"`{field}`=%s" for field in encrypted)
                params = [*encrypted.values(), row["id"]]
                cursor.execute(
                    f"UPDATE user_details SET {assignments} WHERE id=%s",
                    tuple(params),
                )
                updated_fields += len(encrypted)
                # Commit per record so an interrupted run can safely resume.
                db.commit()
            ensure_email_lookup_index(cursor)
            db.commit()
            print(f"Migration complete: {updated_fields} profile values and {len(users)} email addresses processed; no sensitive values displayed.")
            return 0
        except Exception:
            try:
                db.rollback()
            except Exception:
                pass
            raise
        finally:
            db.close()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        # Intentionally avoid printing DB rows, credentials, or exception details.
        print(f"Migration failed ({type(exc).__name__}). No sensitive data was printed; inspect database/service diagnostics.", file=sys.stderr)
        sys.exit(2)
