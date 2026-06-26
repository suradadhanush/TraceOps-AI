"""Small startup migrations for deployments without Alembic history."""
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection


async def run_compat_migrations(conn: AsyncConnection) -> None:
    """Bring older TraceOps databases up to the current ORM shape.

    ``Base.metadata.create_all`` creates missing tables, but it does not add
    columns to tables that already exist. Render's persistent Postgres keeps
    those old tables between deploys, so we patch nullable user-scoping columns
    in place before the app starts serving requests.
    """
    if conn.dialect.name != "postgresql":
        return

    statements = [
        "ALTER TABLE IF EXISTS tasks ADD COLUMN IF NOT EXISTS user_id VARCHAR",
        "ALTER TABLE IF EXISTS events ADD COLUMN IF NOT EXISTS user_id VARCHAR",
        "ALTER TABLE IF EXISTS reports ADD COLUMN IF NOT EXISTS user_id VARCHAR",
        "ALTER TABLE IF EXISTS ai_proxy_logs ADD COLUMN IF NOT EXISTS user_id VARCHAR",
        "CREATE INDEX IF NOT EXISTS ix_tasks_user_id ON tasks (user_id)",
        "CREATE INDEX IF NOT EXISTS ix_events_user_id ON events (user_id)",
        "CREATE INDEX IF NOT EXISTS ix_reports_user_id ON reports (user_id)",
        "CREATE INDEX IF NOT EXISTS ix_ai_proxy_logs_user_id ON ai_proxy_logs (user_id)",
    ]
    for statement in statements:
        await conn.execute(text(statement))
