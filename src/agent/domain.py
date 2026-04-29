"""Domain objects and persistence helpers for visitor registration."""

from __future__ import annotations

import json
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


class VisitorStore:
    def __init__(self, path: str) -> None:
        self.path = Path(path)

    def append(self, registration: VisitorRegistration) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(registration.model_dump_json() + "\n")

    def latest_by_phone(self, phone: str) -> VisitorRegistration | None:
        return self.latest_by_phone_or_plate(phone=phone)

    def latest_by_plate_number(self, plate_number: str) -> VisitorRegistration | None:
        return self.latest_by_phone_or_plate(plate_number=plate_number)

    def latest_by_phone_or_plate(
        self,
        phone: str | None = None,
        plate_number: str | None = None,
    ) -> VisitorRegistration | None:
        phone = phone.strip() if phone else None
        plate_number = plate_number.strip().upper() if plate_number else None
        if not phone and not plate_number:
            return None

        if not self.path.exists():
            return None

        latest: VisitorRegistration | None = None
        with self.path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                data = json.loads(line)
                saved_plate = data.get("plate_number", "")
                phone_matches = bool(phone and data.get("phone") == phone)
                plate_matches = bool(plate_number and isinstance(saved_plate, str))
                if plate_matches:
                    plate_matches = saved_plate.upper() == plate_number
                if phone_matches or plate_matches:
                    latest = VisitorRegistration.model_validate(data)
        return latest
