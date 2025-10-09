from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from app.db import Base

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, autoincrement=False)  # telegram id
    username = Column(String)
    training_plan = Column(Text)  # JSON
    current_day = Column(String, nullable=True)
    exercise_idx = Column(Integer, default=0)
    set_idx = Column(Integer, default=0)
    last_updated = Column(DateTime, default=datetime.utcnow)

    logs = relationship("WorkoutLog", back_populates="user", cascade="all, delete-orphan")

class WorkoutLog(Base):
    __tablename__ = "workout_logs"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    day = Column(String)
    exercise = Column(String)
    set_number = Column(Integer)
    weight = Column(String)
    reps = Column(Integer)
    ts = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="logs")
