"""
Database Initialization Script.
Creates all database tables defined in SQLAlchemy models and seeds default values.
"""

import sys
import logging
from pathlib import Path

# Add project root to path
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from infrastructure.database.session import engine, SessionLocal
from infrastructure.database.models import Base, DepartmentModel, UserModel, EntityAliasModel

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("init_db")


def init_database():
    logger.info("Creating all tables in PostgreSQL if they do not exist...")
    Base.metadata.create_all(bind=engine)
    logger.info("Tables created successfully.")

    db = SessionLocal()
    try:
        # Seed default departments
        dept_it = db.query(DepartmentModel).filter_by(id="dept-it").first()
        if not dept_it:
            logger.info("Seeding default departments...")
            departments = [
                DepartmentModel(id="dept-it", name="Phòng Công nghệ Thông tin", code="IT"),
                DepartmentModel(id="dept-finance", name="Phòng Tài chính Kế toán", code="FINANCE"),
                DepartmentModel(id="dept-hr", name="Phòng Nhân sự", code="HR"),
                DepartmentModel(id="dept-sales", name="Phòng Kinh doanh", code="SALES"),
            ]
            db.add_all(departments)
            db.commit()

        # Seed default admin user
        admin_user = db.query(UserModel).filter_by(id="user-admin").first()
        if not admin_user:
            logger.info("Seeding default admin user...")
            admin = UserModel(
                id="user-admin",
                username="admin",
                email="admin@enterprise.local",
                full_name="Quản trị hệ thống",
                department_id="dept-it",
                role="admin",
                is_active=True
            )
            db.add(admin)
            db.commit()

        # Seed entity aliases
        alias_count = db.query(EntityAliasModel).count()
        if alias_count == 0:
            logger.info("Seeding default entity aliases...")
            aliases = [
                EntityAliasModel(id="alias-hn", standard_name="Hà Nội", alias="hn", entity_type="location"),
                EntityAliasModel(id="alias-hcm", standard_name="Hồ Chí Minh", alias="hcm", entity_type="location"),
                EntityAliasModel(id="alias-tphcm", standard_name="Hồ Chí Minh", alias="tphcm", entity_type="location"),
                EntityAliasModel(id="alias-sg", standard_name="Hồ Chí Minh", alias="sg", entity_type="location"),
                EntityAliasModel(id="alias-dn", standard_name="Đà Nẵng", alias="dn", entity_type="location"),
                EntityAliasModel(id="alias-hp", standard_name="Hải Phòng", alias="hp", entity_type="location"),
                EntityAliasModel(id="alias-ct", standard_name="Cần Thơ", alias="ct", entity_type="location"),
                EntityAliasModel(id="alias-q1", standard_name="Quý 1", alias="q1", entity_type="quarter"),
                EntityAliasModel(id="alias-q2", standard_name="Quý 2", alias="q2", entity_type="quarter"),
                EntityAliasModel(id="alias-q3", standard_name="Quý 3", alias="q3", entity_type="quarter"),
                EntityAliasModel(id="alias-q4", standard_name="Quý 4", alias="q4", entity_type="quarter"),
            ]
            db.add_all(aliases)
            db.commit()

        logger.info("Database initialization and initial seeding complete!")
    except Exception as e:
        logger.error(f"Error during database initialization: {e}")
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    init_database()
