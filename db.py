import os
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

print("--- CHECKING ENVIRONMENT VARIABLES ---")
print("DATABASE_URL present:", bool(os.getenv("DATABASE_URL")))
print("MYSQL_URL present:", bool(os.getenv("MYSQL_URL")))
print("MYSQL_PRIVATE_URL present:", bool(os.getenv("MYSQL_PRIVATE_URL")))

database_url = (
        os.getenv("DATABASE_URL") or
        os.getenv("MYSQL_URL") or
        os.getenv("MYSQL_PRIVATE_URL")
)

if not database_url:
    # Fallback to individual components if URL is missing
    host = os.getenv("MYSQLHOST")
    port = os.getenv("MYSQLPORT", "3306")
    user = os.getenv("MYSQLUSER")
    password = os.getenv("MYSQLPASSWORD")
    database = os.getenv("MYSQLDATABASE")

    if host and user and password and database:
        database_url = f"mysql+pymysql://{user}:{password}@{host}:{port}/{database}"

if not database_url:
    raise ValueError(
        "CRITICAL ERROR: No database URL found! "
        "Please check your Railway Variables tab and ensure DATABASE_URL or MYSQL_URL is set."
    )

if database_url.startswith("mysql://"):
    database_url = database_url.replace("mysql://", "mysql+pymysql://", 1)

engine = create_engine(database_url)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)

Base = declarative_base()