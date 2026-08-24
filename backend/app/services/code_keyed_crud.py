# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Shared CRUD core for every "code-keyed universe" table in this app — MacroRegion,
CountryPerfConfig, SectorPerfConfig, EquityPremiumConfig all hand-copied the identical
list/create/update/delete shape (validate code via regex + optional extra per-field
validators on create/update, reject a duplicate code, optionally reject deleting the last
remaining row) before being collapsed into this one factory. Each service module keeps its
own thin, positionally-typed wrapper functions on top (so router call sites never change) and
only owns the one instantiation call plus its own regexes/messages.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass
class CodeKeyedCrud:
    list: Callable[[AsyncSession], Awaitable[list[Any]]]
    create: Callable[..., Awaitable[Any]]
    update: Callable[..., Awaitable[Optional[Any]]]
    delete: Callable[[AsyncSession, str], Awaitable[Optional[bool]]]


def make_code_keyed_crud(
    model_cls: type,
    code_re: re.Pattern[str],
    invalid_code_message: Callable[[str], str],
    duplicate_message: Callable[[str], str],
    field_validators: Optional[dict[str, tuple[re.Pattern[str], Callable[[str], str]]]] = None,
    last_row_guard_message: Optional[str] = None,
) -> CodeKeyedCrud:
    """
    `model_cls` must have a `code` primary-key column plus whatever other columns the
    caller's own `create`/`update` wrapper passes as keyword args — this factory has no
    opinion on the field list itself, only on the validate/duplicate/guard shape around it.
    `field_validators` (e.g. currency) run identically on both create and update, matching
    every existing service's own behavior. `last_row_guard_message` set means `delete()`
    raises ValueError instead of deleting when it's the only remaining row.
    """
    validators = field_validators or {}

    def _validate_fields(values: dict[str, str]) -> None:
        for name, (pattern, message) in validators.items():
            if not pattern.match(values[name]):
                raise ValueError(message(values[name]))

    async def list_all(db: AsyncSession) -> list[Any]:
        result = await db.execute(select(model_cls).order_by(model_cls.code))
        return list(result.scalars().all())

    async def create(db: AsyncSession, code: str, **values: str) -> Any:
        """Raises ValueError (client-facing message) on an invalid code/field or a duplicate."""
        if not code_re.match(code):
            raise ValueError(invalid_code_message(code))
        _validate_fields(values)
        if await db.get(model_cls, code) is not None:
            raise ValueError(duplicate_message(code))
        obj = model_cls(code=code, **values)
        db.add(obj)
        await db.commit()
        await db.refresh(obj)
        return obj

    async def update(db: AsyncSession, code: str, **values: str) -> Optional[Any]:
        """`code` is immutable. Returns None if the row doesn't exist. Raises ValueError on
        an invalid field value."""
        obj = await db.get(model_cls, code)
        if obj is None:
            return None
        _validate_fields(values)
        for name, value in values.items():
            setattr(obj, name, value)
        await db.commit()
        await db.refresh(obj)
        return obj

    async def delete(db: AsyncSession, code: str) -> Optional[bool]:
        """Returns None if the row doesn't exist, True on success. Raises ValueError if
        `last_row_guard_message` is set and this is the last remaining row."""
        obj = await db.get(model_cls, code)
        if obj is None:
            return None
        if last_row_guard_message is not None:
            total = await db.scalar(select(func.count()).select_from(model_cls))
            if total is not None and total <= 1:
                raise ValueError(last_row_guard_message)
        await db.delete(obj)
        await db.commit()
        return True

    return CodeKeyedCrud(list=list_all, create=create, update=update, delete=delete)
