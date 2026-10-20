"""Provision teacher accounts locally; passwords are never passed in process arguments."""

import argparse
import getpass
import os
import sqlite3

from proofgrade.teacher_store import TeacherStore


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("username")
    parser.add_argument("--db", default=os.getenv("PROOFGRADE_TEACHER_DB", "data/teachers.sqlite3"))
    args = parser.parse_args()
    password = getpass.getpass("New teacher password (at least 12 characters): ")
    if password != getpass.getpass("Confirm password: "):
        parser.error("Passwords do not match.")
    try:
        TeacherStore(args.db).create_teacher(args.username, password)
    except (ValueError, sqlite3.IntegrityError) as error:
        parser.error("Username already exists." if isinstance(error, sqlite3.IntegrityError) else str(error))
    print(f"Teacher {args.username} created. Sign in at /teacher.")


if __name__ == "__main__":
    main()
