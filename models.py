from sqlalchemy import Column
from sqlalchemy import Integer
from sqlalchemy import String
from sqlalchemy import Date
from sqlalchemy import Text
from sqlalchemy import ForeignKey
from sqlalchemy import Boolean
from sqlalchemy import DateTime
from datetime import datetime
from db import Base

class User(Base):
    __tablename__ = "users"

    id = Column(
        Integer,
        primary_key=True,
        index=True
    )

    email = Column(
        String(100),
        unique=True
    )

    password = Column(
        String(255)
    )

    # Email toggled off by default
    email_enabled = Column(
        Boolean,
        default=False,
        nullable=False
    )


class Job(Base):
    __tablename__ = "jobs"

    id = Column(Integer, primary_key=True)

    user_id = Column(Integer, ForeignKey("users.id"))

    company = Column(String(100))

    role = Column(String(100))

    status = Column(String(50))

    applied_date = Column(Date)

    interview_date = Column(Date, nullable=True)

    notes = Column(Text)


class Resume(Base):
    __tablename__ = "resumes"

    id = Column(Integer, primary_key=True)

    user_id = Column(
        Integer,
        ForeignKey("users.id")
    )

    filename = Column(String(255))

    ats_score = Column(
        Integer,
        default=0
    )

    resume_text = Column(Text)


class Activity(Base):
    __tablename__ = "activities"

    id = Column(
        Integer,
        primary_key=True
    )

    user_id = Column(
        Integer
    )

    action = Column(
        String(255)
    )

    # created_at = Column(
    #     DateTime,
    #     default=datetime.utcnow
    # )


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(
        Integer,
        primary_key=True
    )

    user_id = Column(
        Integer
    )

    message = Column(
        String(255)
    )

    is_read = Column(
        Boolean,
        default=False
    )