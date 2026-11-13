"""Every table, one module per area. Importing this package registers them all."""

from mawta_schema.tables.academic import AcademicYear, GradeLevel, NonTeachingDay, Term
from mawta_schema.tables.assessment import (
    Assessment,
    AssessmentCriterion,
    CompetencyExemption,
    CompetencyTermLevel,
    CompetencyYearSnapshot,
    DescriptiveConclusion,
    EvaluationCriterion,
    EvaluationCriterionCapability,
    GradeScale,
    GradeScaleLevel,
    Score,
    YearFinalSituation,
)
from mawta_schema.tables.chat import ChatMessage, ChatQuestionBank, ChatThread
from mawta_schema.tables.curriculum import (
    Capability,
    Competency,
    GradeLevelPerformance,
    LearningStandard,
    StandardLevelMapping,
    Subject,
)
from mawta_schema.tables.enrollment import Section, SectionMembership, Student
from mawta_schema.tables.evidence import Notification, VoiceNote, VoiceNoteRedaction
from mawta_schema.tables.planning import (
    ExperienceCompetency,
    LearningExperience,
    PlannedEvidence,
    PlannedEvidenceCriterion,
    SessionOutlineEntry,
)
from mawta_schema.tables.school import Membership, School, Teacher, User, UserSession
from mawta_schema.tables.system import AgentGeneration, Event, Job
from mawta_schema.tables.teaching import (
    AttendanceRecord,
    Class,
    ClassSchedule,
    ClassSession,
    ClassTeacher,
    Course,
)

__all__ = [
    "AcademicYear",
    "AgentGeneration",
    "Assessment",
    "AssessmentCriterion",
    "AttendanceRecord",
    "Capability",
    "ChatMessage",
    "ChatQuestionBank",
    "ChatThread",
    "Class",
    "ClassSchedule",
    "ClassSession",
    "ClassTeacher",
    "Competency",
    "CompetencyExemption",
    "CompetencyTermLevel",
    "CompetencyYearSnapshot",
    "Course",
    "DescriptiveConclusion",
    "EvaluationCriterion",
    "EvaluationCriterionCapability",
    "Event",
    "ExperienceCompetency",
    "GradeLevel",
    "GradeLevelPerformance",
    "GradeScale",
    "GradeScaleLevel",
    "Job",
    "LearningExperience",
    "LearningStandard",
    "Membership",
    "NonTeachingDay",
    "Notification",
    "PlannedEvidence",
    "PlannedEvidenceCriterion",
    "School",
    "Score",
    "Section",
    "SectionMembership",
    "SessionOutlineEntry",
    "StandardLevelMapping",
    "Student",
    "Subject",
    "Teacher",
    "Term",
    "User",
    "UserSession",
    "VoiceNote",
    "VoiceNoteRedaction",
    "YearFinalSituation",
]
