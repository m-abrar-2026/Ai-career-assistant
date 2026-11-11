import os
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

# 1. Try checking standard URL environment variables
database_url = (
        os.getenv("MYSQL_URL") or
        os.getenv("MYSQL_PRIVATE_URL") or
        os.getenv("DATABASE_URL")
)

# 2. If URLs aren't found, build it automatically from Railway's native MySQL variables
if not database_url:
    host = os.getenv("MYSQLHOST")
    port = os.getenv("MYSQLPORT", "3306")
    user = os.getenv("MYSQLUSER")
    password = os.getenv("MYSQLPASSWORD")
    database = os.getenv("MYSQLDATABASE")

    if host and user and password and database:
        database_url = f"mysql+pymysql://{user}:{password}@{host}:{port}/{database}"

if not database_url:
    raise ValueError("No database URL or MySQL credentials found in environment variables!")

# Ensure SQLAlchemy uses the pymysql driver
if database_url.startswith("mysql://"):
    database_url = database_url.replace("mysql://", "mysql+pymysql://", 1)

engine = create_engine(database_url)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)

Base = declarative_base()