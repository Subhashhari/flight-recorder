"""Seed the 40 synthetic employees (E1001..E1040, random seed 7). Idempotent."""

from sqlalchemy import text

from flightrec.backend.mock_backend import generate_employees
from flightrec.db import engine, init_db


def main() -> None:
    init_db()
    emps = generate_employees()
    with engine().begin() as c:
        c.execute(text("TRUNCATE employees"))
        c.execute(text("""INSERT INTO employees(employee_id, name, grade, manager_id, casual, sick, earned)
                          VALUES (:employee_id, :name, :grade, :manager_id, :casual, :sick, :earned)"""), emps)
    print(f"seeded {len(emps)} employees")


if __name__ == "__main__":
    main()
