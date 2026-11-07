"""The test school, I.E. Cristo Rey (modular 0400001), written with mawta_schema.tables.

Ported from the old tests/fixture.sql (school A only). Ids are fixed and mirrored in FX
(tests/conftest.py); the trailing segment says what the row is.

The scenario: Quispe teaches Matemática to 5to B; Rojas is an active teacher of the same school
who teaches nothing, the colleague who must not reach Quispe's class. Bimestre II is live;
Bimestre I sits closed behind it. Two directors (Ana, Beto) use the chat.
"""

import datetime as dt
from decimal import Decimal
from uuid import UUID as U

from sqlalchemy import Connection, insert

from mawta_schema.tables import (
    AcademicYear,
    Assessment,
    AssessmentCriterion,
    Capability,
    Class,
    ClassSession,
    ClassTeacher,
    Competency,
    Course,
    EvaluationCriterion,
    GradeLevel,
    GradeScale,
    GradeScaleLevel,
    Membership,
    School,
    Score,
    Section,
    SectionMembership,
    Student,
    Subject,
    Teacher,
    Term,
    User,
)


def load(conn: Connection) -> None:
    """Insert the whole test school. The caller owns the transaction."""
    conn.execute(
        insert(AcademicYear),
        [
            {
                "id": U("a0000000-0000-4000-8000-000000000030"),
                "year": 2026,
                "name": "2026",
                "starts_on": dt.date.fromisoformat("2026-03-01"),
                "ends_on": dt.date.fromisoformat("2026-12-18"),
                "term_structure": "bimestre",
                "status": "active",
            },
        ],
    )
    conn.execute(
        insert(GradeLevel),
        [
            {
                "id": U("a0000000-0000-4000-8000-000000000040"),
                "code": "5S",
                "label": "5to",
                "long_label": "Quinto de secundaria",
                "stage": "secundaria",
                "ordinal": 11,
            },
        ],
    )
    conn.execute(
        insert(GradeScale),
        [
            {
                "id": U("a0000000-0000-4000-8000-000000000070"),
                "code": "minedu_ad_a_b_c",
                "name": "Escala MINEDU AD/A/B/C",
                "kind": "ordinal",
                "min_value": Decimal("1.0000"),
                "max_value": Decimal("4.0000"),
                "decimals": 0,
            },
        ],
    )
    conn.execute(
        insert(School),
        [
            {
                "id": U("a0000000-0000-4000-8000-000000000001"),
                "name": "I.E. Cristo Rey",
                "modular_code": "0400001",
                "kind": "publica",
                "timezone": "America/Lima",
                "status": "active",
            },
        ],
    )
    conn.execute(
        insert(Student),
        [
            {
                "id": U("a0000000-0000-4000-8000-000000000101"),
                "student_code": "EST-2026-001",
                "given_name": "Ana",
                "paternal_surname": "Alvarez",
                "maternal_surname": "Ruiz",
                "sex": "F",
                "status": "active",
                "inclusion_support": False,
            },
            {
                "id": U("a0000000-0000-4000-8000-000000000102"),
                "student_code": "EST-2026-002",
                "given_name": "Bruno",
                "paternal_surname": "Bravo",
                "maternal_surname": "Soto",
                "sex": "M",
                "status": "active",
                "inclusion_support": False,
            },
            {
                "id": U("a0000000-0000-4000-8000-000000000103"),
                "student_code": "EST-2026-003",
                "given_name": "Carla",
                "paternal_surname": "Cordova",
                "maternal_surname": "Ttito",
                "sex": "F",
                "status": "active",
                "inclusion_support": False,
            },
            {
                "id": U("a0000000-0000-4000-8000-000000000104"),
                "student_code": "EST-2026-004",
                "given_name": "Diego",
                "paternal_surname": "Diaz",
                "maternal_surname": "Uscamayta",
                "sex": "M",
                "status": "active",
                "inclusion_support": False,
            },
            {
                "id": U("a0000000-0000-4000-8000-000000000105"),
                "student_code": "EST-2026-005",
                "given_name": "Elena",
                "paternal_surname": "Espinoza",
                "maternal_surname": "Vilca",
                "sex": "F",
                "status": "active",
                "inclusion_support": False,
            },
        ],
    )
    conn.execute(
        insert(Subject),
        [
            {
                "id": U("a0000000-0000-4000-8000-000000000050"),
                "code": "MAT",
                "name": "Matemática",
                "is_tutoria": False,
                "sort_order": 0,
            },
        ],
    )
    conn.execute(
        insert(User),
        [
            {
                "id": U("a0000000-0000-4000-8000-000000000010"),
                "email": "janice.quispe@cristorey.edu.pe",
                "given_name": "Janice",
                "family_name": "Quispe",
                "status": "active",
                "username": "jquispe",
                "password_hash": "$2a$04$abcdefghijklmnopqrstuvREPLACEDBYTESTSxxxxxxxxxxxxxxxxxxxx",
                "failed_login_count": 0,
            },
            {
                "id": U("a0000000-0000-4000-8000-000000000020"),
                "email": "marco.rojas@cristorey.edu.pe",
                "given_name": "Marco",
                "family_name": "Rojas",
                "status": "active",
                "username": "mrojas",
                "password_hash": "$2a$04$abcdefghijklmnopqrstuvREPLACEDBYTESTSxxxxxxxxxxxxxxxxxxxx",
                "failed_login_count": 0,
            },
        ],
    )
    conn.execute(
        insert(Competency),
        [
            {
                "id": U("a0000000-0000-4000-8000-000000000060"),
                "subject_id": U("a0000000-0000-4000-8000-000000000050"),
                "code": "MAT-C1",
                "name": "Resuelve problemas de cantidad",
                "kind": "area",
                "sort_order": 0,
                "is_active": True,
            },
            {
                "id": U("a0000000-0000-4000-8000-000000000061"),
                "subject_id": U("a0000000-0000-4000-8000-000000000050"),
                "code": "MAT-C2",
                "name": "Resuelve problemas de regularidad, equivalencia y cambio",
                "kind": "area",
                "sort_order": 0,
                "is_active": True,
            },
        ],
    )
    conn.execute(
        insert(Course),
        [
            {
                "id": U("a0000000-0000-4000-8000-000000000051"),
                "academic_year_id": U("a0000000-0000-4000-8000-000000000030"),
                "subject_id": U("a0000000-0000-4000-8000-000000000050"),
                "grade_level_id": U("a0000000-0000-4000-8000-000000000040"),
                "name": "Matemática 5to",
            },
        ],
    )
    conn.execute(
        insert(GradeScaleLevel),
        [
            {
                "id": U("a0000000-0000-4000-8000-000000000071"),
                "scale_id": U("a0000000-0000-4000-8000-000000000070"),
                "code": "AD",
                "label": "Destacado",
                "ordinal": 4,
                "min_normalized": Decimal("0.85000"),
                "max_normalized": Decimal("1.00000"),
            },
            {
                "id": U("a0000000-0000-4000-8000-000000000072"),
                "scale_id": U("a0000000-0000-4000-8000-000000000070"),
                "code": "A",
                "label": "Esperado",
                "ordinal": 3,
                "min_normalized": Decimal("0.70000"),
                "max_normalized": Decimal("0.85000"),
            },
            {
                "id": U("a0000000-0000-4000-8000-000000000073"),
                "scale_id": U("a0000000-0000-4000-8000-000000000070"),
                "code": "B",
                "label": "En proceso",
                "ordinal": 2,
                "min_normalized": Decimal("0.55000"),
                "max_normalized": Decimal("0.70000"),
            },
            {
                "id": U("a0000000-0000-4000-8000-000000000074"),
                "scale_id": U("a0000000-0000-4000-8000-000000000070"),
                "code": "C",
                "label": "En inicio",
                "ordinal": 1,
                "min_normalized": Decimal("0.00000"),
                "max_normalized": Decimal("0.55000"),
            },
        ],
    )
    conn.execute(
        insert(Membership),
        [
            {
                "id": U("a0000000-0000-4000-8000-000000000012"),
                "user_id": U("a0000000-0000-4000-8000-000000000010"),
                "role": "teacher",
                "status": "active",
            },
            {
                "id": U("a0000000-0000-4000-8000-000000000022"),
                "user_id": U("a0000000-0000-4000-8000-000000000020"),
                "role": "teacher",
                "status": "active",
            },
        ],
    )
    conn.execute(
        insert(Capability),
        [
            {
                "id": U("a0000000-0000-4000-8000-000000000062"),
                "competency_id": U("a0000000-0000-4000-8000-000000000061"),
                "code": "MAT-C2-CAP1",
                "name": "Traduce datos y condiciones a expresiones algebraicas",
                "sort_order": 0,
                "is_active": True,
            },
        ],
    )
    conn.execute(
        insert(Teacher),
        [
            {
                "id": U("a0000000-0000-4000-8000-000000000011"),
                "membership_id": U("a0000000-0000-4000-8000-000000000012"),
                "display_name": "Janice Quispe",
                "status": "active",
            },
            {
                "id": U("a0000000-0000-4000-8000-000000000021"),
                "membership_id": U("a0000000-0000-4000-8000-000000000022"),
                "display_name": "Marco Rojas",
                "status": "active",
            },
        ],
    )
    conn.execute(
        insert(Section),
        [
            {
                "id": U("a0000000-0000-4000-8000-000000000041"),
                "academic_year_id": U("a0000000-0000-4000-8000-000000000030"),
                "grade_level_id": U("a0000000-0000-4000-8000-000000000040"),
                "label": "B",
                "name": "5to B",
                "shift": "manana",
                "status": "active",
            },
        ],
    )
    conn.execute(
        insert(Term),
        [
            {
                "id": U("a0000000-0000-4000-8000-000000000031"),
                "academic_year_id": U("a0000000-0000-4000-8000-000000000030"),
                "sequence": 1,
                "name": "Bimestre I",
                "starts_on": dt.date.fromisoformat("2026-03-01"),
                "ends_on": dt.date.fromisoformat("2026-05-15"),
                "status": "closed",
                "closed_at": dt.datetime.fromisoformat("2026-05-16T00:00:00+00:00"),
            },
        ],
    )
    conn.execute(
        insert(Term),
        [
            {
                "id": U("a0000000-0000-4000-8000-000000000032"),
                "academic_year_id": U("a0000000-0000-4000-8000-000000000030"),
                "sequence": 2,
                "name": "Bimestre II",
                "starts_on": dt.date.fromisoformat("2026-05-16"),
                "ends_on": dt.date.fromisoformat("2026-07-31"),
                "status": "active",
            },
        ],
    )
    conn.execute(
        insert(Class),
        [
            {
                "id": U("a0000000-0000-4000-8000-000000000052"),
                "academic_year_id": U("a0000000-0000-4000-8000-000000000030"),
                "grade_level_id": U("a0000000-0000-4000-8000-000000000040"),
                "course_id": U("a0000000-0000-4000-8000-000000000051"),
                "section_id": U("a0000000-0000-4000-8000-000000000041"),
                "name": "Matemática 5to B",
                "code": "MAT-5B",
                "status": "active",
            },
        ],
    )
    conn.execute(
        insert(SectionMembership),
        [
            {
                "student_id": U("a0000000-0000-4000-8000-000000000104"),
                "section_id": U("a0000000-0000-4000-8000-000000000041"),
                "academic_year_id": U("a0000000-0000-4000-8000-000000000030"),
                "joined_on": dt.date.fromisoformat("2026-03-01"),
                "status": "active",
            },
            {
                "student_id": U("a0000000-0000-4000-8000-000000000102"),
                "section_id": U("a0000000-0000-4000-8000-000000000041"),
                "academic_year_id": U("a0000000-0000-4000-8000-000000000030"),
                "joined_on": dt.date.fromisoformat("2026-03-01"),
                "status": "active",
            },
            {
                "student_id": U("a0000000-0000-4000-8000-000000000105"),
                "section_id": U("a0000000-0000-4000-8000-000000000041"),
                "academic_year_id": U("a0000000-0000-4000-8000-000000000030"),
                "joined_on": dt.date.fromisoformat("2026-03-01"),
                "status": "active",
            },
            {
                "student_id": U("a0000000-0000-4000-8000-000000000103"),
                "section_id": U("a0000000-0000-4000-8000-000000000041"),
                "academic_year_id": U("a0000000-0000-4000-8000-000000000030"),
                "joined_on": dt.date.fromisoformat("2026-03-01"),
                "status": "active",
            },
            {
                "student_id": U("a0000000-0000-4000-8000-000000000101"),
                "section_id": U("a0000000-0000-4000-8000-000000000041"),
                "academic_year_id": U("a0000000-0000-4000-8000-000000000030"),
                "joined_on": dt.date.fromisoformat("2026-03-01"),
                "status": "active",
            },
        ],
    )
    conn.execute(
        insert(ClassTeacher),
        [
            {
                "class_id": U("a0000000-0000-4000-8000-000000000052"),
                "teacher_id": U("a0000000-0000-4000-8000-000000000011"),
                "role": "titular",
                "starts_on": dt.date.fromisoformat("2026-03-01"),
            },
        ],
    )
    conn.execute(
        insert(ClassSession),
        [
            {
                "id": U("a0000000-0000-4000-8000-000000000110"),
                "academic_year_id": U("a0000000-0000-4000-8000-000000000030"),
                "class_id": U("a0000000-0000-4000-8000-000000000052"),
                "term_id": U("a0000000-0000-4000-8000-000000000032"),
                "session_date": dt.date.fromisoformat("2026-05-18"),
                "scheduled_start_at": dt.datetime.fromisoformat("2026-05-18T13:00:00+00:00"),
                "scheduled_end_at": dt.datetime.fromisoformat("2026-05-18T14:30:00+00:00"),
                "actual_start_at": dt.datetime.fromisoformat("2026-05-18T13:02:00+00:00"),
                "status": "completed",
                "started_by_id": U("a0000000-0000-4000-8000-000000000011"),
            },
        ],
    )
    conn.execute(
        insert(EvaluationCriterion),
        [
            {
                "id": U("a0000000-0000-4000-8000-000000000063"),
                "competency_id": U("a0000000-0000-4000-8000-000000000061"),
                "capability_id": U("a0000000-0000-4000-8000-000000000062"),
                "code": "CR1",
                "description": "Plantea la ecuación que modela la situación",
                "sort_order": 1,
                "is_active": True,
                "proposed_by": "teacher",
            },
            {
                "id": U("a0000000-0000-4000-8000-000000000064"),
                "competency_id": U("a0000000-0000-4000-8000-000000000061"),
                "capability_id": U("a0000000-0000-4000-8000-000000000062"),
                "code": "CR2",
                "description": "Justifica el procedimiento empleado",
                "sort_order": 2,
                "is_active": True,
                "proposed_by": "teacher",
            },
        ],
    )
    conn.execute(
        insert(Assessment),
        [
            {
                "id": U("a0000000-0000-4000-8000-000000000120"),
                "class_id": U("a0000000-0000-4000-8000-000000000052"),
                "term_id": U("a0000000-0000-4000-8000-000000000032"),
                "session_id": U("a0000000-0000-4000-8000-000000000110"),
                "title": "Práctica 1",
                "kind": "produccion",
                "value_scale": "numeric",
                "max_score": Decimal("20.0000"),
                "status": "published",
                "published_at": dt.datetime.fromisoformat("2026-05-18T13:00:00+00:00"),
                "created_by_id": U("a0000000-0000-4000-8000-000000000011"),
            },
        ],
    )
    conn.execute(
        insert(Assessment),
        [
            {
                "id": U("a0000000-0000-4000-8000-000000000121"),
                "class_id": U("a0000000-0000-4000-8000-000000000052"),
                "term_id": U("a0000000-0000-4000-8000-000000000032"),
                "title": "Proyecto de modelación",
                "kind": "produccion",
                "value_scale": "ordinal",
                "status": "published",
                "published_at": dt.datetime.fromisoformat("2026-05-18T13:00:00+00:00"),
                "created_by_id": U("a0000000-0000-4000-8000-000000000011"),
            },
        ],
    )
    conn.execute(
        insert(AssessmentCriterion),
        [
            {
                "assessment_id": U("a0000000-0000-4000-8000-000000000121"),
                "criterion_id": U("a0000000-0000-4000-8000-000000000064"),
            },
            {
                "assessment_id": U("a0000000-0000-4000-8000-000000000121"),
                "criterion_id": U("a0000000-0000-4000-8000-000000000063"),
            },
            {
                "assessment_id": U("a0000000-0000-4000-8000-000000000120"),
                "criterion_id": U("a0000000-0000-4000-8000-000000000063"),
            },
        ],
    )
    conn.execute(
        insert(Score),
        [
            {
                "id": U("a0000000-0000-4000-8000-000000000122"),
                "assessment_id": U("a0000000-0000-4000-8000-000000000120"),
                "student_id": U("a0000000-0000-4000-8000-000000000101"),
                "status": "graded",
                "raw_value": Decimal("16.0000"),
                "max_value": Decimal("20.0000"),
                "source": "manual",
                "recorded_by_id": U("a0000000-0000-4000-8000-000000000011"),
            },
        ],
    )

    # The two directors of the school: a user and a director membership each, no teacher row.
    # Their passwords are "ana-clave-2026" and "beto-clave-2026" (bcrypt, cost 4).
    conn.execute(
        insert(User),
        [
            {
                "id": U("a0000000-0000-4000-8000-0000000000d0"),
                "email": "ana.directora@cristorey.edu.pe",
                "given_name": "Ana",
                "family_name": "Directora",
                "username": "adirectora",
                "password_hash": "$2b$04$3CaPNgVZKzCrlc5beTPF..nuoxUXmmrv.U5XBcaO7i9Ig5DaFpldW",
                "status": "active",
            },
            {
                "id": U("a0000000-0000-4000-8000-0000000000e0"),
                "email": "beto.director@cristorey.edu.pe",
                "given_name": "Beto",
                "family_name": "Director",
                "username": "bdirector",
                "password_hash": "$2b$04$hUydWTVu890NaqsjLwwhauz0cLVWIYlMkXrqGpXwrQKBn93XyWpCO",
                "status": "active",
            },
        ],
    )
    conn.execute(
        insert(Membership),
        [
            {
                "id": U("a0000000-0000-4000-8000-0000000000d1"),
                "user_id": U("a0000000-0000-4000-8000-0000000000d0"),
                "role": "director",
                "status": "active",
            },
            {
                "id": U("a0000000-0000-4000-8000-0000000000e1"),
                "user_id": U("a0000000-0000-4000-8000-0000000000e0"),
                "role": "director",
                "status": "active",
            },
        ],
    )
