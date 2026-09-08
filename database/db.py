from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from config import DATABASE_URL


class Base(DeclarativeBase):
    pass


engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
)


def _remove_chat_id_unique_constraint(conn):
    """SQLite cannot drop a UNIQUE column constraint directly, so rebuild countries."""
    indexes = conn.exec_driver_sql("PRAGMA index_list(countries)").fetchall()
    needs_rebuild = False
    for row in indexes:
        # row: seq, name, unique, origin, partial
        if int(row[2]) != 1:
            continue
        cols = conn.exec_driver_sql(f'PRAGMA index_info("{row[1]}")').fetchall()
        if len(cols) == 1 and cols[0][2] == "chat_id":
            needs_rebuild = True
            break

    if not needs_rebuild:
        return

    conn.exec_driver_sql("PRAGMA foreign_keys=OFF")
    conn.exec_driver_sql("ALTER TABLE countries RENAME TO countries_old")
    conn.exec_driver_sql("""
        CREATE TABLE countries (
            id INTEGER NOT NULL PRIMARY KEY,
            chat_id BIGINT NOT NULL,
            title VARCHAR(255) NOT NULL,
            continent_name VARCHAR(255),
            chat_type VARCHAR(32) NOT NULL,
            leader_user_id BIGINT NOT NULL,
            leader_name VARCHAR(255) NOT NULL,
            money REAL NOT NULL DEFAULT 10000.0,
            fuel REAL NOT NULL DEFAULT 0.0,
            metal REAL NOT NULL DEFAULT 0.0,
            uranium REAL NOT NULL DEFAULT 0.0,
            command_center_level INTEGER NOT NULL DEFAULT 1,
            metal_mine_level INTEGER NOT NULL DEFAULT 0,
            metal_mine_storage REAL NOT NULL DEFAULT 0.0,
            metal_mine_last_production_at DATETIME,
            power_plant_level INTEGER NOT NULL DEFAULT 0,
            bank_level INTEGER NOT NULL DEFAULT 0,
            laboratory_level INTEGER NOT NULL DEFAULT 0,
            defense INTEGER NOT NULL DEFAULT 0,
            drones INTEGER NOT NULL DEFAULT 0,
            missiles INTEGER NOT NULL DEFAULT 0,
            created_at DATETIME
        )
    """)
    conn.exec_driver_sql("""
        INSERT INTO countries (
            id, chat_id, title, continent_name, chat_type, leader_user_id, leader_name,
            money, fuel, metal, uranium, command_center_level,
            metal_mine_level, metal_mine_storage, metal_mine_last_production_at,
            power_plant_level, bank_level, laboratory_level,
            defense, drones, missiles, created_at
        )
        SELECT
            id, chat_id, title, continent_name, chat_type, leader_user_id, leader_name,
            money, fuel, metal, uranium, command_center_level,
            metal_mine_level, metal_mine_storage, metal_mine_last_production_at,
            power_plant_level, bank_level, laboratory_level,
            defense, drones, missiles, created_at
        FROM countries_old
    """)
    conn.exec_driver_sql("DROP TABLE countries_old")
    conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_countries_chat_id ON countries(chat_id)")
    conn.exec_driver_sql("PRAGMA foreign_keys=ON")


def _migrate_country_schema(conn):
    """Rebuild countries plus dependent FK tables when economic columns need REAL or legacy UNIQUE(chat_id) exists."""
    cols = {row[1]: row[2].upper() for row in conn.exec_driver_sql("PRAGMA table_info(countries)").fetchall()}
    economic = ("money", "fuel", "metal", "uranium", "metal_mine_storage")
    indexes = conn.exec_driver_sql("PRAGMA index_list(countries)").fetchall()
    unique_chat = False
    for row in indexes:
        if int(row[2]) != 1:
            continue
        info = conn.exec_driver_sql(f'PRAGMA index_info("{row[1]}")').fetchall()
        if len(info) == 1 and info[0][2] == "chat_id":
            unique_chat = True
            break

    if not (any(cols.get(name) != "REAL" for name in economic) or unique_chat):
        return

    conn.exec_driver_sql("PRAGMA foreign_keys=OFF")

    # Rename all dependent tables first; they are recreated with correct FK targets below.
    conn.exec_driver_sql("ALTER TABLE users RENAME TO users_legacy")
    conn.exec_driver_sql("ALTER TABLE user_countries RENAME TO user_countries_legacy")
    conn.exec_driver_sql("ALTER TABLE countries RENAME TO countries_legacy")

    conn.exec_driver_sql("""
        CREATE TABLE users (
            id INTEGER NOT NULL PRIMARY KEY,
            telegram_id BIGINT NOT NULL UNIQUE,
            username VARCHAR(255),
            first_name VARCHAR(255),
            default_country_id INTEGER,
            created_at DATETIME NOT NULL,
            last_active_at DATETIME NOT NULL,
            is_banned BOOLEAN NOT NULL DEFAULT 0,
            phone_number VARCHAR(32),
            ban_reason VARCHAR(1000),
            FOREIGN KEY(default_country_id) REFERENCES countries (id)
        )
    """)
    conn.exec_driver_sql("""
        CREATE TABLE countries (
            id INTEGER NOT NULL PRIMARY KEY,
            chat_id BIGINT NOT NULL,
            title VARCHAR(255) NOT NULL,
            continent_name VARCHAR(255),
            chat_type VARCHAR(32) NOT NULL,
            leader_user_id BIGINT NOT NULL,
            leader_name VARCHAR(255) NOT NULL,
            money REAL NOT NULL DEFAULT 20000.0,
            fuel REAL NOT NULL DEFAULT 1000.0,
            metal REAL NOT NULL DEFAULT 2000.0,
            uranium REAL NOT NULL DEFAULT 0.0,
            infinite_money BOOLEAN NOT NULL DEFAULT 0,
            infinite_fuel BOOLEAN NOT NULL DEFAULT 0,
            infinite_metal BOOLEAN NOT NULL DEFAULT 0,
            infinite_uranium BOOLEAN NOT NULL DEFAULT 0,
            command_center_level INTEGER NOT NULL DEFAULT 1,
            metal_mine_level INTEGER NOT NULL DEFAULT 0,
            metal_mine_storage REAL NOT NULL DEFAULT 0.0,
            metal_mine_last_production_at DATETIME,
            power_plant_level INTEGER NOT NULL DEFAULT 0,
            bank_level INTEGER NOT NULL DEFAULT 0,
            laboratory_level INTEGER NOT NULL DEFAULT 0,
            defense INTEGER NOT NULL DEFAULT 0,
            drones INTEGER NOT NULL DEFAULT 0,
            missiles INTEGER NOT NULL DEFAULT 0,
            created_at DATETIME
        )
    """)
    conn.exec_driver_sql("""
        CREATE TABLE user_countries (
            id INTEGER NOT NULL PRIMARY KEY,
            user_id INTEGER NOT NULL,
            country_id INTEGER NOT NULL,
            CONSTRAINT uq_user_country UNIQUE (user_id, country_id),
            FOREIGN KEY(user_id) REFERENCES users (id),
            FOREIGN KEY(country_id) REFERENCES countries (id)
        )
    """)

    conn.exec_driver_sql("""
        INSERT INTO users (id, telegram_id, username, first_name, default_country_id, created_at, last_active_at, is_banned, phone_number, ban_reason)
        SELECT id, telegram_id, username, first_name, default_country_id, created_at, last_active_at, is_banned, phone_number, ban_reason
        FROM users_legacy
    """)
    conn.exec_driver_sql("""
        INSERT INTO countries (
            id, chat_id, title, continent_name, chat_type, leader_user_id, leader_name,
            money, fuel, metal, uranium, infinite_money, infinite_fuel, infinite_metal, infinite_uranium, command_center_level,
            metal_mine_level, metal_mine_storage, metal_mine_last_production_at,
            power_plant_level, bank_level, laboratory_level,
            defense, drones, missiles, created_at
        )
        SELECT
            id, chat_id, title, continent_name, chat_type, leader_user_id, leader_name,
            CAST(money AS REAL), CAST(fuel AS REAL), CAST(metal AS REAL), CAST(uranium AS REAL),
            COALESCE(infinite_money, 0), COALESCE(infinite_fuel, 0), COALESCE(infinite_metal, 0), COALESCE(infinite_uranium, 0),
            command_center_level, metal_mine_level, CAST(metal_mine_storage AS REAL),
            metal_mine_last_production_at, power_plant_level, bank_level, laboratory_level,
            defense, drones, missiles, created_at
        FROM countries_legacy
    """)
    conn.exec_driver_sql("""
        INSERT INTO user_countries (id, user_id, country_id)
        SELECT id, user_id, country_id FROM user_countries_legacy
    """)

    conn.exec_driver_sql("DROP TABLE user_countries_legacy")
    conn.exec_driver_sql("DROP TABLE users_legacy")
    conn.exec_driver_sql("DROP TABLE countries_legacy")

    conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_users_telegram_id_idx ON users(telegram_id)")
    conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_countries_chat_id ON countries(chat_id)")
    conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_user_countries_user_id ON user_countries(user_id)")
    conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_user_countries_country_id ON user_countries(country_id)")
    conn.exec_driver_sql("PRAGMA foreign_keys=ON")



def _ensure_missing_columns(conn):
    """Repair columns that may be absent in databases created by older bot versions.

    This is intentionally additive and runs AFTER any table rebuild, because a rebuild
    must never erase newer columns such as the infinite-resource flags.
    """
    required = {
        "users": {
            "last_active_at": "DATETIME",
            "is_banned": "BOOLEAN NOT NULL DEFAULT 0",
            "phone_number": "VARCHAR(32)",
            "ban_reason": "VARCHAR(1000)",
            "ban_until": "DATETIME",
        },
        "countries": {
            "continent_name": "VARCHAR(255)",
            "leader_user_id": "BIGINT",
            "leader_name": "VARCHAR(255)",
            "metal_mine_storage": "REAL NOT NULL DEFAULT 0",
            "metal_mine_last_production_at": "DATETIME",
            "infinite_money": "BOOLEAN NOT NULL DEFAULT 0",
            "infinite_fuel": "BOOLEAN NOT NULL DEFAULT 0",
            "infinite_metal": "BOOLEAN NOT NULL DEFAULT 0",
            "infinite_uranium": "BOOLEAN NOT NULL DEFAULT 0",
            "arsenal_level": "INTEGER NOT NULL DEFAULT 0",
            "arsenal_storage": "REAL NOT NULL DEFAULT 0",
            "leadership_experience": "REAL NOT NULL DEFAULT 0",
            "command_center_construction_until": "DATETIME",
            "command_center_construction_target_level": "INTEGER",
            "metal_mine_construction_until": "DATETIME",
            "metal_mine_construction_target_level": "INTEGER",
            "arsenal_construction_until": "DATETIME",
            "arsenal_construction_target_level": "INTEGER",
        },
    }
    for table, columns in required.items():
        existing = {row[1] for row in conn.exec_driver_sql(f"PRAGMA table_info({table})").fetchall()}
        for name, ddl in columns.items():
            if name not in existing:
                conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")


def init_db():
    from database.models import Country, User, UserCountry, BotSetting, GroupStatus

    Base.metadata.create_all(bind=engine)

    with engine.begin() as conn:
        user_columns = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(users)").fetchall()}
        if "last_active_at" not in user_columns:
            conn.exec_driver_sql("ALTER TABLE users ADD COLUMN last_active_at DATETIME")
            conn.exec_driver_sql("UPDATE users SET last_active_at = created_at WHERE last_active_at IS NULL")
        if "is_banned" not in user_columns:
            conn.exec_driver_sql("ALTER TABLE users ADD COLUMN is_banned BOOLEAN NOT NULL DEFAULT 0")
        if "phone_number" not in user_columns:
            conn.exec_driver_sql("ALTER TABLE users ADD COLUMN phone_number VARCHAR(32)")
        if "ban_reason" not in user_columns:
            conn.exec_driver_sql("ALTER TABLE users ADD COLUMN ban_reason VARCHAR(1000)")
        if "ban_until" not in user_columns:
            conn.exec_driver_sql("ALTER TABLE users ADD COLUMN ban_until DATETIME")

        conn.exec_driver_sql("INSERT OR IGNORE INTO bot_settings (key, value) VALUES ('phone_required_users', '0')")
        conn.exec_driver_sql("INSERT OR IGNORE INTO bot_settings (key, value) VALUES ('phone_required_admins', '0')")

        columns = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(countries)").fetchall()}
        for col in ("infinite_money", "infinite_fuel", "infinite_metal", "infinite_uranium"):
            if col not in columns:
                conn.exec_driver_sql(f"ALTER TABLE countries ADD COLUMN {col} BOOLEAN NOT NULL DEFAULT 0")

        columns = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(countries)").fetchall()}

        if "continent_name" not in columns:
            conn.exec_driver_sql("ALTER TABLE countries ADD COLUMN continent_name VARCHAR(255)")

        if "metal_mine_storage" not in columns:
            conn.exec_driver_sql("ALTER TABLE countries ADD COLUMN metal_mine_storage INTEGER NOT NULL DEFAULT 0")

        if "metal_mine_last_production_at" not in columns:
            conn.exec_driver_sql("ALTER TABLE countries ADD COLUMN metal_mine_last_production_at DATETIME")
            conn.exec_driver_sql("UPDATE countries SET metal_mine_last_production_at = CURRENT_TIMESTAMP WHERE metal_mine_last_production_at IS NULL")

        if "leader_user_id" not in columns:
            conn.exec_driver_sql("ALTER TABLE countries ADD COLUMN leader_user_id INTEGER")

        if "leader_name" not in columns:
            conn.exec_driver_sql("ALTER TABLE countries ADD COLUMN leader_name VARCHAR(255)")

        if "arsenal_level" not in columns:
            conn.exec_driver_sql("ALTER TABLE countries ADD COLUMN arsenal_level INTEGER NOT NULL DEFAULT 0")
        if "arsenal_storage" not in columns:
            conn.exec_driver_sql("ALTER TABLE countries ADD COLUMN arsenal_storage REAL NOT NULL DEFAULT 0")
        if "leadership_experience" not in columns:
            conn.exec_driver_sql("ALTER TABLE countries ADD COLUMN leadership_experience REAL NOT NULL DEFAULT 0")

        conn.exec_driver_sql("""
            UPDATE countries
            SET leader_user_id = COALESCE(leader_user_id, (
                SELECT u.telegram_id
                FROM user_countries uc
                JOIN users u ON u.id = uc.user_id
                WHERE uc.country_id = countries.id
                ORDER BY uc.id
                LIMIT 1
            ))
            WHERE leader_user_id IS NULL
        """)
        conn.exec_driver_sql("UPDATE countries SET leader_user_id = COALESCE(leader_user_id, 0) WHERE leader_user_id IS NULL")

        conn.exec_driver_sql("""
            UPDATE countries
            SET leader_name = COALESCE(leader_name, (
                SELECT COALESCE(u.first_name, u.username, CAST(u.telegram_id AS TEXT))
                FROM user_countries uc
                JOIN users u ON u.id = uc.user_id
                WHERE uc.country_id = countries.id
                ORDER BY uc.id
                LIMIT 1
            ))
            WHERE leader_name IS NULL
        """)
        conn.exec_driver_sql("UPDATE countries SET leader_name = COALESCE(NULLIF(TRIM(leader_name), ''), 'نامشخص') WHERE leader_name IS NULL OR TRIM(leader_name) = ''")

        _migrate_country_schema(conn)
        # The rebuild above targets older schemas. Re-ensure every additive column
        # after the rebuild so newer fields can never disappear.
        _ensure_missing_columns(conn)

        # Repair timestamps introduced in older databases.
        conn.exec_driver_sql("UPDATE users SET last_active_at = COALESCE(last_active_at, created_at, CURRENT_TIMESTAMP) WHERE last_active_at IS NULL")
        conn.exec_driver_sql("UPDATE countries SET metal_mine_last_production_at = COALESCE(metal_mine_last_production_at, CURRENT_TIMESTAMP) WHERE metal_mine_last_production_at IS NULL")
