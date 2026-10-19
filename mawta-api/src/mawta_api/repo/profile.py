"""The teacher's profile screen."""

from datetime import date
from uuid import UUID

from psycopg import AsyncConnection

from mawta_api.db import fetch_all, fetch_required
from mawta_api.repo.roster import roster_as_of


def _midnight_utc(value: date | None) -> str | None:
    """A date column in the API's timestamp form (midnight UTC)."""
    return f"{value.isoformat()}T00:00:00Z" if value is not None else None


async def get_profile(conn: AsyncConnection, teacher_id: UUID, term: dict, today: date) -> dict:
    head = await fetch_required(
        conn,
        """
        select t.display_name, t.title, t.hired_on, tn.name as tenant_name, tn.city as tenant_city
          from teachers t join tenants tn on tn.id = t.tenant_id
         where t.id = %s
        """,
        (teacher_id,),
    )
    resp: dict = {
        "display_name": head["display_name"],
        "title": head["title"],
        "hired_on": _midnight_utc(head["hired_on"]),
        "tenant_name": head["tenant_name"],
        "tenant_city": head["tenant_city"],
        "top_stats": {"classes": 0, "students": 0, "weekly_hours": 0.0},
        "activity": {
            "clases_dictadas": 0,
            "asistencias_registradas": 0,
            "asistencias_esperadas": 0,
            "notas_de_voz": 0,
            "evaluaciones": 0,
        },
        "classes_by_grade": None,
    }

    class_rows = await fetch_all(
        conn,
        """
        select distinct c.id, c.name, sec.id as section_id, gl.long_label as grade_label,
               gl.ordinal
          from class_teachers ct
          join classes c on c.id = ct.class_id and c.deleted_at is null and c.status = 'active'
          join sections sec on sec.id = c.section_id
          join grade_levels gl on gl.id = sec.grade_level_id
         where ct.teacher_id = %(teacher)s and ct.starts_on <= %(today)s
           and (ct.ends_on is null or ct.ends_on >= %(today)s) and ct.deleted_at is null
         order by gl.ordinal, c.name
        """,
        {"teacher": teacher_id, "today": today},
    )
    if not class_rows:
        return resp

    class_ids = [r["id"] for r in class_rows]
    section_ids = [r["section_id"] for r in class_rows]
    resp["top_stats"]["classes"] = len(class_rows)

    resp["top_stats"]["students"] = (
        await fetch_required(
            conn,
            """
            select count(distinct sm.student_id) as n from section_memberships sm
             where sm.section_id = any(%(sections)s::uuid[])
               and sm.joined_on <= %(today)s and (sm.left_on is null or sm.left_on > %(today)s)
               and sm.deleted_at is null
            """,
            {"sections": section_ids, "today": today},
        )
    )["n"]

    resp["top_stats"]["weekly_hours"] = float(
        (
            await fetch_required(
                conn,
                """
                select coalesce(sum(extract(epoch from (ends_at - starts_at)) / 3600.0), 0) as h
                  from class_schedules
                 where class_id = any(%(classes)s::uuid[]) and effective_from <= %(today)s
                   and (effective_to is null or effective_to > %(today)s) and deleted_at is null
                """,
                {"classes": class_ids, "today": today},
            )
        )["h"]
    )

    if term["id"] is not None:
        sessions = await fetch_required(
            conn,
            """
            select count(*) as taught,
                   count(*) filter (where attendance_taken_at is not null) as registered
              from class_sessions
             where class_id = any(%(classes)s::uuid[]) and term_id = %(term)s
               and status = 'completed' and deleted_at is null
            """,
            {"classes": class_ids, "term": term["id"]},
        )
        activity = resp["activity"]
        activity["clases_dictadas"] = sessions["taught"]
        activity["asistencias_registradas"] = sessions["registered"]
        activity["asistencias_esperadas"] = sessions["taught"]
        activity["notas_de_voz"] = (
            await fetch_required(
                conn,
                """
                select count(*) as n from voice_notes
                 where teacher_id = %(teacher)s
                   and recorded_at::date between %(from)s and %(to)s and deleted_at is null
                """,
                {"teacher": teacher_id, "from": term["starts_on"], "to": term["ends_on"]},
            )
        )["n"]
        activity["evaluaciones"] = (
            await fetch_required(
                conn,
                """
                select count(*) as n from assessments
                 where created_by_id = %(teacher)s and term_id = %(term)s and deleted_at is null
                """,
                {"teacher": teacher_id, "term": term["id"]},
            )
        )["n"]

    groups: dict[str, dict] = {}
    for cr in class_rows:
        roster = await roster_as_of(conn, cr["id"], today)
        slots = (
            await fetch_required(
                conn,
                """
                select count(*) as n from class_schedules
                 where class_id = %(class)s and effective_from <= %(today)s
                   and (effective_to is null or effective_to > %(today)s) and deleted_at is null
                """,
                {"class": cr["id"], "today": today},
            )
        )["n"]
        group = groups.setdefault(
            cr["grade_label"], {"grade_label": cr["grade_label"], "classes": []}
        )
        group["classes"].append(
            {
                "class_id": cr["id"],
                "name": cr["name"],
                "roster_count": len(roster),
                "slots_per_week": slots,
            }
        )
    resp["classes_by_grade"] = list(groups.values())
    return resp
