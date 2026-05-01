"""Domain objects and persistence helpers for visitor registration."""

from __future__ import annotations

import asyncio
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

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

    @classmethod
    async def append_async(cls, path: str, registration: VisitorRegistration) -> None:
        await asyncio.to_thread(cls._append_at_path, path, registration)

    @classmethod
    def _append_at_path(cls, path: str, registration: VisitorRegistration) -> None:
        cls(path).append(registration)

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

    def query_visits(
        self,
        *,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        company: str | None = None,
        phone: str | None = None,
        plate_number: str | None = None,
        reason_keyword: str | None = None,
        caller: str | None = None,
        keyword: str | None = None,
        limit: int = 20,
    ) -> list[VisitorRegistration]:
        sql, values = self._build_visit_query(
            start_time=start_time,
            end_time=end_time,
            company=company,
            phone=phone,
            plate_number=plate_number,
            reason_keyword=reason_keyword,
            caller=caller,
            keyword=keyword,
            select_columns=(
                "plate_number, company, phone, reason, entry_time, caller, call_sid"
            ),
            order_by="ORDER BY datetime(entry_time) DESC, id DESC",
            limit=limit,
        )
        with self._connect() as connection:
            rows = connection.execute(sql, values).fetchall()
        return [self._row_to_registration(row) for row in rows]

    def count_visits(
        self,
        *,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        company: str | None = None,
        phone: str | None = None,
        plate_number: str | None = None,
        reason_keyword: str | None = None,
        caller: str | None = None,
        keyword: str | None = None,
    ) -> int:
        sql, values = self._build_visit_query(
            start_time=start_time,
            end_time=end_time,
            company=company,
            phone=phone,
            plate_number=plate_number,
            reason_keyword=reason_keyword,
            caller=caller,
            keyword=keyword,
            select_columns="COUNT(*) AS total",
        )
        with self._connect() as connection:
            row = connection.execute(sql, values).fetchone()
        return int(row["total"]) if row is not None else 0

    def busiest_hour(
        self,
        *,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> dict[str, Any] | None:
        sql, values = self._build_visit_query(
            start_time=start_time,
            end_time=end_time,
            select_columns=(
                "strftime('%Y-%m-%d %H:00', entry_time) AS hour_bucket, "
                "COUNT(*) AS total"
            ),
            group_by="GROUP BY hour_bucket",
            order_by="ORDER BY total DESC, hour_bucket ASC",
            limit=1,
        )
        with self._connect() as connection:
            row = connection.execute(sql, values).fetchone()
        if row is None or not row["hour_bucket"]:
            return None
        return {
            "hour_bucket": str(row["hour_bucket"]),
            "total": int(row["total"]),
        }

    def top_repeat_visitors(
        self,
        *,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        sql, values = self._build_visit_query(
            start_time=start_time,
            end_time=end_time,
            select_columns=(
                "phone_lookup, MAX(phone) AS phone, MAX(plate_number) AS plate_number, "
                "MAX(company) AS company, COUNT(*) AS total_visits, "
                "MAX(entry_time) AS latest_entry_time"
            ),
            group_by="GROUP BY phone_lookup",
            order_by="ORDER BY total_visits DESC, datetime(latest_entry_time) DESC",
            limit=limit,
        )
        with self._connect() as connection:
            rows = connection.execute(sql, values).fetchall()
        return [
            {
                "phone": str(row["phone"]),
                "plate_number": str(row["plate_number"]),
                "company": str(row["company"]),
                "total_visits": int(row["total_visits"]),
                "latest_entry_time": str(row["latest_entry_time"]),
            }
            for row in rows
        ]

    def _build_visit_query(
        self,
        *,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        company: str | None = None,
        phone: str | None = None,
        plate_number: str | None = None,
        reason_keyword: str | None = None,
        caller: str | None = None,
        keyword: str | None = None,
        select_columns: str,
        group_by: str = "",
        order_by: str = "",
        limit: int | None = None,
    ) -> tuple[str, list[Any]]:
        where_clauses: list[str] = []
        values: list[Any] = []

        if start_time is not None:
            where_clauses.append("datetime(entry_time) >= datetime(?)")
            values.append(start_time.isoformat())
        if end_time is not None:
            where_clauses.append("datetime(entry_time) <= datetime(?)")
            values.append(end_time.isoformat())
        if company:
            where_clauses.append("company LIKE ?")
            values.append(f"%{company.strip()}%")
        if phone:
            normalized_phone = _normalize_phone_lookup(phone)
            if normalized_phone:
                where_clauses.append("phone_lookup = ?")
                values.append(normalized_phone)
        if plate_number:
            where_clauses.append("UPPER(plate_number) = ?")
            values.append(plate_number.strip().upper())
        if reason_keyword:
            where_clauses.append("reason LIKE ?")
            values.append(f"%{reason_keyword.strip()}%")
        if caller:
            normalized_caller = _normalize_phone_lookup(caller)
            if normalized_caller:
                where_clauses.append(
                    "substr(replace(replace(replace(replace(ifnull(caller, ''), '+', ''), '-', ''), ' ', ''), '86', ''), -11) = ?"
                )
                values.append(normalized_caller)
        if keyword:
            cleaned_keyword = keyword.strip()
            if cleaned_keyword:
                where_clauses.append(
                    "("
                    "plate_number LIKE ? OR company LIKE ? OR phone LIKE ? OR "
                    "reason LIKE ? OR ifnull(caller, '') LIKE ?"
                    ")"
                )
                values.extend([f"%{cleaned_keyword}%"] * 5)

        sql = f"SELECT {select_columns} FROM visitor_registrations"
        if where_clauses:
            sql += " WHERE " + " AND ".join(where_clauses)
        if group_by:
            sql += f" {group_by}"
        if order_by:
            sql += f" {order_by}"
        if limit is not None and limit > 0:
            sql += " LIMIT ?"
            values.append(limit)
        return sql, values

    @classmethod
    async def recent_by_phone_async(
        cls,
        path: str,
        phone: str,
        *,
        limit: int = 5,
    ) -> list[VisitorRegistration]:
        return await asyncio.to_thread(cls._recent_by_phone_at_path, path, phone, limit)

    @classmethod
    def _recent_by_phone_at_path(
        cls,
        path: str,
        phone: str,
        limit: int,
    ) -> list[VisitorRegistration]:
        return cls(path).recent_by_phone(phone, limit=limit)
