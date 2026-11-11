import os
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

# Pull the database URL from Railway environment variables
database_url = os.getenv("MYSQL_URL") or os.getenv("MYSQL_PRIVATE_URL") or os.getenv("DATABASE_URL")

if not database_url:
    raise ValueError("No database URL found in environment variables!")

# Ensure SQLAlchemy uses the pymysql driver correctly with Railway's URL format
if database_url.startswith("mysql://"):
    database_url = database_url.replace("mysql://", "mysql+pymysql://", 1)

engine = create_engine(database_url)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)

Base = declarative_base()