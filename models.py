from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import Column, Integer, String, LargeBinary


class Base(DeclarativeBase):
    pass


# =========================
# EMPLOYEES
# =========================
class Employee(Base):
    __tablename__ = "employees"

    emp_id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    embedding = Column(LargeBinary, nullable=False)
    created_at = Column(String)
    department = Column(String)
    active = Column(Integer)


# =========================
# ATTENDANCE
# =========================
class Attendance(Base):
    __tablename__ = "attendance"

    id = Column(Integer, primary_key=True, autoincrement=True)
    emp_id = Column(String, nullable=False)
    name = Column(String, nullable=False)
    timestamp = Column(String, nullable=False)
    date = Column(String, nullable=False)
    event = Column(String, nullable=False)
    source = Column(String)
    note = Column(String)
    voided = Column(Integer)


# =========================
# HOLIDAYS
# =========================
class Holiday(Base):
    __tablename__ = "holidays"

    day = Column(String, primary_key=True)
    name = Column(String, nullable=False)


# =========================
# LEAVES
# =========================
class Leave(Base):
    __tablename__ = "leaves"

    id = Column(Integer, primary_key=True, autoincrement=True)
    emp_id = Column(String, nullable=False)
    day = Column(String, nullable=False)
    type = Column(String, nullable=False)
    note = Column(String)


# =========================
# SETTINGS
# =========================
class Setting(Base):
    __tablename__ = "settings"

    key = Column(String, primary_key=True)
    value = Column(String)
