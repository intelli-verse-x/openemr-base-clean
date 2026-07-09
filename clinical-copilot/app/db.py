"""Read-only bounded access to the OpenEMR MariaDB.

Design (from AUDIT §3): the agent never replays the dashboard UI and never uses a
cookie session (PHP file-locking serializes those). It issues a small number of
parameterized, column-explicit, LIMIT-bounded queries. All queries are read-only.
"""
from __future__ import annotations

from typing import Any

import aiomysql

from .config import get_settings

_pool: aiomysql.Pool | None = None


async def init_pool() -> bool:
    """Create the connection pool. Resilient by design: if OpenEMR is unreachable
    at startup we log and return False rather than crashing the process, so the
    service still boots and /ready can report the dependency as down (avoids a
    Kubernetes crash-loop and preserves separate liveness/readiness semantics).
    """
    global _pool
    if _pool is not None:
        return True
    s = get_settings()
    try:
        _pool = await aiomysql.create_pool(
            host=s.db_host,
            port=s.db_port,
            user=s.db_user,
            password=s.db_password,
            db=s.db_name,
            minsize=s.db_pool_min,
            maxsize=s.db_pool_max,
            autocommit=True,
            charset="utf8mb4",
            connect_timeout=5,
        )
        return True
    except Exception as exc:
        import logging

        logging.getLogger("copilot").warning("db pool init failed (will retry lazily): %s", exc)
        _pool = None
        return False


async def _ensure_pool() -> bool:
    """Lazily (re)establish the pool on demand for readiness/queries."""
    if _pool is not None:
        return True
    return await init_pool()


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        await _pool.wait_closed()
        _pool = None


async def ping() -> bool:
    if not await _ensure_pool() or _pool is None:
        return False
    async with _pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT 1")
            return (await cur.fetchone())[0] == 1


async def fetch_all(sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    if not await _ensure_pool() or _pool is None:
        raise RuntimeError("OpenEMR database unreachable")
    async with _pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute(sql, params)
            return list(await cur.fetchall())


async def fetch_one(sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
    if not await _ensure_pool() or _pool is None:
        raise RuntimeError("OpenEMR database unreachable")
    async with _pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute(sql, params)
            return await cur.fetchone()


# --------------------------------------------------------------------------- #
# Bounded clinical reads (explicit columns, patient-scoped, LIMIT-ed)
# --------------------------------------------------------------------------- #
async def get_patient(pid: int) -> dict[str, Any] | None:
    return await fetch_one(
        """SELECT pid, fname, lname, mname, DOB, sex, providerID, care_team_provider
           FROM patient_data WHERE pid = %s LIMIT 1""",
        (pid,),
    )


async def get_lists(pid: int, list_type: str, limit: int = 200) -> list[dict[str, Any]]:
    return await fetch_all(
        """SELECT id, uuid, type, title, diagnosis, begdate, enddate, activity,
                  reaction, severity_al, comments
           FROM lists
           WHERE pid = %s AND type = %s
           ORDER BY activity DESC, begdate DESC
           LIMIT %s""",
        (pid, list_type, limit),
    )


async def get_prescriptions(pid: int, active_only: bool = True, limit: int = 100) -> list[dict[str, Any]]:
    where = "patient_id = %s" + (" AND active = 1" if active_only else "")
    return await fetch_all(
        f"""SELECT id, uuid, drug, rxnorm_drugcode, dosage, quantity, unit, form,
                   route, `interval`, start_date, end_date, active, note, provider_id
            FROM prescriptions
            WHERE {where}
            ORDER BY date_added DESC
            LIMIT %s""",
        (pid, limit),
    )


async def get_lab_results(pid: int, limit: int = 100) -> list[dict[str, Any]]:
    return await fetch_all(
        """SELECT po.patient_id, pr.date_report, pres.result_code, pres.result_text,
                  pres.result, pres.units, pres.range, pres.abnormal,
                  pres.date AS result_date, pres.result_status
           FROM procedure_order po
           JOIN procedure_report pr ON pr.procedure_order_id = po.procedure_order_id
           JOIN procedure_result pres ON pres.procedure_report_id = pr.procedure_report_id
           WHERE po.patient_id = %s
           ORDER BY COALESCE(pres.date, pr.date_report) DESC
           LIMIT %s""",
        (pid, limit),
    )


async def get_encounters(pid: int, limit: int = 25) -> list[dict[str, Any]]:
    return await fetch_all(
        """SELECT id, uuid, encounter, date, reason, provider_id, class_code
           FROM form_encounter
           WHERE pid = %s
           ORDER BY date DESC
           LIMIT %s""",
        (pid, limit),
    )


async def get_soap_notes(pid: int, limit: int = 10) -> list[dict[str, Any]]:
    return await fetch_all(
        """SELECT id, date, subjective, objective, assessment, plan
           FROM form_soap
           WHERE pid = %s AND activity = 1
           ORDER BY date DESC
           LIMIT %s""",
        (pid, limit),
    )


async def get_vitals(pid: int, limit: int = 10) -> list[dict[str, Any]]:
    return await fetch_all(
        """SELECT id, uuid, date, bps, bpd, weight, height, temperature, pulse,
                  respiration, BMI, oxygen_saturation
           FROM form_vitals
           WHERE pid = %s AND activity = 1
           ORDER BY date DESC
           LIMIT %s""",
        (pid, limit),
    )


async def get_immunizations(pid: int, limit: int = 50) -> list[dict[str, Any]]:
    return await fetch_all(
        """SELECT id, uuid, administered_date, cvx_code, note, route
           FROM immunizations
           WHERE patient_id = %s AND added_erroneously = 0
           ORDER BY administered_date DESC
           LIMIT %s""",
        (pid, limit),
    )


async def resolve_provider(user_id: str) -> dict[str, Any] | None:
    """Map an authenticated username to a provider row (for the authz allow-set)."""
    return await fetch_one(
        "SELECT id, username, fname, lname, authorized FROM users WHERE username = %s LIMIT 1",
        (user_id,),
    )
