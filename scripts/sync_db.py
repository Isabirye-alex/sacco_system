import logging
from sqlalchemy import text
from app.core.database import Base, engine
import app.models  # noqa: F401

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("sync_db")

def sync_schema_columns():
    statements = [
        "ALTER TABLE members ADD COLUMN IF NOT EXISTS dormancy_notified_stage INT DEFAULT 0;",
        "ALTER TABLE collaterals ADD COLUMN IF NOT EXISTS is_released BOOLEAN DEFAULT FALSE;",
        "ALTER TABLE collaterals ADD COLUMN IF NOT EXISTS released_at TIMESTAMP;",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS referral_code VARCHAR(16);",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_2fa_enabled BOOLEAN DEFAULT FALSE;",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS totp_secret VARCHAR(64);",
        "ALTER TABLE referrals ADD COLUMN IF NOT EXISTS referrer_id VARCHAR(36);",
        "ALTER TABLE referrals ADD COLUMN IF NOT EXISTS referred_user_id VARCHAR(36);",
        "ALTER TABLE referrals ADD COLUMN IF NOT EXISTS tier INT DEFAULT 1;",
    ]
    with engine.connect() as conn:
        for stmt in statements:
            try:
                conn.execute(text(stmt))
                conn.commit()
                logger.info("Executed schema DDL: %s", stmt)
            except Exception as exc:
                logger.error("Error executing schema DDL '%s': %s", stmt, exc)

def init_db():
    logger.info("Initializing database tables...")
    Base.metadata.create_all(bind=engine)
    sync_schema_columns()
    logger.info("Database sync complete.")

if __name__ == "__main__":
    init_db()
