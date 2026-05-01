"""Domain objects and persistence helpers for visitor registration."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, Field, field_validator


class VisitorRegistration(BaseModel):
    plate_number: str = Field(..., description="访客车牌号")
    company: str = Field(..., description="来访单位")
    phone: str = Field(..., description="访客手机号")
    reason: str = Field(..., description="来访事由")
    entry_time: datetime = Field(default_factory=datetime.now)
    caller: str | None = None
    call_sid: str | None = None

    @field_validator("plate_number", "company", "phone", "reason")
    @classmethod
    def trim_required_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("value must not be empty")
        return cleaned

    def guard_message(self) -> str:
        entry_time = self.entry_time.strftime("%Y-%m-%d %H:%M")
        return (
            f"访客车辆登记\n"
            f"车牌：{self.plate_number}\n"
            f"来访单位：{self.company}\n"
            f"手机号：{self.phone}\n"
            f"事由：{self.reason}\n"
            f"入场时间：{entry_time}"
        )


def _normalize_phone_lookup(phone: str | None) -> str:
    digits = "".join(char for char in (phone or "") if char.isdigit())
    if digits.startswith("86") and len(digits) > 11:
        digits = digits[2:]
    if len(digits) >= 11:
        return digits[-11:]
    return digits


class VisitorStore:
    def __init__(self, path: str) -> None:
        self.path = Path(path)
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _ensure_schema(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS visitor_registrations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    plate_number TEXT NOT NULL,
                    company TEXT NOT NULL,
                    phone TEXT NOT NULL,
                    phone_lookup TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    entry_time TEXT NOT NULL,
                    caller TEXT,
                    call_sid TEXT
                )
                """
            )
            columns = {
                row["name"]
                for row in connection.execute(
                    "PRAGMA table_info(visitor_registrations)"
                ).fetchall()
            }
            if "phone_lookup" not in columns:
                connection.execute(
                    "ALTER TABLE visitor_registrations ADD COLUMN phone_lookup TEXT"
                )
                connection.execute(
                    """
                    UPDATE visitor_registrations
                    SET phone_lookup = substr(
                        replace(replace(replace(replace(phone, '+', ''), '-', ''), ' ', ''), '86', ''),
                        -11
                    )
                    WHERE phone_lookup IS NULL OR phone_lookup = ''
                    """
                )
            connection.commit()

    @staticmethod
    def _row_to_registration(row: sqlite3.Row) -> VisitorRegistration:
        return VisitorRegistration.model_validate(dict(row))

    def append(self, registration: VisitorRegistration) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO visitor_registrations (
                    plate_number,
                    company,
                    phone,
                    phone_lookup,
                    reason,
                    entry_time,
                    caller,
                    call_sid
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    registration.plate_number,
                    registration.company,
                    registration.phone,
                    _normalize_phone_lookup(registration.phone),
                    registration.reason,
                    registration.entry_time.isoformat(),
                    registration.caller,
                    registration.call_sid,
                ),
            )
            connection.commit()

    def latest_by_phone(self, phone: str) -> VisitorRegistration | None:
        return self.latest_by_phone_or_plate(phone=phone)

    def latest_by_plate_number(self, plate_number: str) -> VisitorRegistration | None:
        return self.latest_by_phone_or_plate(plate_number=plate_number)

    def latest_by_phone_or_plate(
        self,
        phone: str | None = None,
        plate_number: str | None = None,
    ) -> VisitorRegistration | None:
        phone = _normalize_phone_lookup(phone) if phone else None
        plate_number = plate_number.strip().upper() if plate_number else None
        if not phone and not plate_number:
            return None

        where_clauses: list[str] = []
        values: list[str] = []
        if phone:
            where_clauses.append("phone_lookup = ?")
            values.append(phone)
        if plate_number:
            where_clauses.append("UPPER(plate_number) = ?")
            values.append(plate_number)
        if not where_clauses:
            return None

        with self._connect() as connection:
            row = connection.execute(
                f"""
                SELECT plate_number, company, phone, reason, entry_time, caller, call_sid
                FROM visitor_registrations
                WHERE {" OR ".join(where_clauses)}
                ORDER BY datetime(entry_time) DESC, id DESC
                LIMIT 1
                """,
                values,
            ).fetchone()
        if row is None:
            return None
        return self._row_to_registration(row)

    def recent_by_phone(
        self,
        phone: str,
        *,
        limit: int = 5,
    ) -> list[VisitorRegistration]:
        normalized_phone = _normalize_phone_lookup(phone)
        if not normalized_phone or limit <= 0:
            return []

        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT plate_number, company, phone, reason, entry_time, caller, call_sid
                FROM visitor_registrations
                WHERE phone_lookup = ?
                ORDER BY datetime(entry_time) DESC, id DESC
                LIMIT ?
                """,
                (normalized_phone, limit),
            ).fetchall()
        return [self._row_to_registration(row) for row in rows]
