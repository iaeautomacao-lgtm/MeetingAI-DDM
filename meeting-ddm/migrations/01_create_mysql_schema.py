import os
from pathlib import Path

import mysql.connector
import psycopg
from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BASE_DIR.parent
ENV_FILE = BASE_DIR / ".env"
if not ENV_FILE.exists():
    ENV_FILE = PROJECT_ROOT / ".env"

load_dotenv(ENV_FILE)

POSTGRES_SCHEMA = os.getenv("PG_SCHEMA", "meeting_ai")


def get_postgres_connection():
    postgres_url = os.getenv("POSTGRES_URL") or os.getenv("DATABASE_URL")
    if postgres_url:
        return psycopg.connect(
            postgres_url,
            connect_timeout=30,
            prepare_threshold=None,
        )

    required = ("PG_HOST", "PG_USER", "PG_PASSWORD")
    missing = [name for name in required if not os.getenv(name)]
    if missing:
        raise RuntimeError(
            f"Variáveis Postgres ausentes no {ENV_FILE}: "
            + ", ".join(missing)
            + ". Preencha POSTGRES_URL ou os campos PG_HOST, PG_USER e PG_PASSWORD."
        )

    return psycopg.connect(
        host=os.getenv("PG_HOST"),
        port=int(os.getenv("PG_PORT", "5432")),
        dbname=os.getenv("PG_DATABASE", "postgres"),
        user=os.getenv("PG_USER"),
        password=os.getenv("PG_PASSWORD"),
        sslmode=os.getenv("PG_SSLMODE", "require"),
        connect_timeout=30,
        prepare_threshold=None,
    )


def get_mysql_connection():
    required = ("MYSQL_HOST", "MYSQL_DATABASE", "MYSQL_USER", "MYSQL_PASSWORD")
    missing = [name for name in required if not os.getenv(name)]
    if missing:
        raise RuntimeError(
            f"Variáveis MariaDB ausentes no {ENV_FILE}: "
            + ", ".join(missing)
        )

    return mysql.connector.connect(
        host=os.getenv("MYSQL_HOST"),
        port=int(os.getenv("MYSQL_PORT", "3306")),
        database=os.getenv("MYSQL_DATABASE"),
        user=os.getenv("MYSQL_USER"),
        password=os.getenv("MYSQL_PASSWORD"),
        connection_timeout=15,
    )


def map_postgres_type_to_mysql(
    data_type: str,
    udt_name: str,
    max_length: int | None,
) -> str:
    if data_type == "uuid":
        return "CHAR(36)"

    if data_type == "character varying":
        if max_length:
            return f"VARCHAR({max_length})"
        return "LONGTEXT"

    if data_type == "text":
        return "LONGTEXT"

    if data_type == "boolean":
        return "BOOLEAN"

    if data_type in ("integer", "smallint"):
        return "INT"

    if data_type == "bigint":
        return "BIGINT"

    if data_type in ("numeric", "decimal"):
        return "DECIMAL(20,6)"

    if data_type in ("real", "double precision"):
        return "DOUBLE"

    if data_type in (
        "timestamp without time zone",
        "timestamp with time zone",
    ):
        return "DATETIME"

    if data_type == "date":
        return "DATE"

    if data_type.startswith("time"):
        return "TIME"

    if data_type in ("json", "jsonb"):
        return "JSON"

    if data_type == "ARRAY" or udt_name.startswith("_"):
        return "JSON"

    return "LONGTEXT"


def get_tables(pg_cursor):
    pg_cursor.execute(
        """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = %s
          AND table_type = 'BASE TABLE'
        ORDER BY table_name;
        """,
        (POSTGRES_SCHEMA,),
    )
    return [row[0] for row in pg_cursor.fetchall()]


def get_columns(pg_cursor, table_name: str):
    pg_cursor.execute(
        """
        SELECT
          column_name,
          data_type,
          udt_name,
          is_nullable,
          column_default,
          character_maximum_length
        FROM information_schema.columns
        WHERE table_schema = %s
          AND table_name = %s
        ORDER BY ordinal_position;
        """,
        (POSTGRES_SCHEMA, table_name),
    )
    return pg_cursor.fetchall()


def get_primary_keys(pg_cursor, table_name: str):
    pg_cursor.execute(
        """
        SELECT kcu.column_name
        FROM information_schema.table_constraints tc
        JOIN information_schema.key_column_usage kcu
          ON tc.constraint_name = kcu.constraint_name
         AND tc.table_schema = kcu.table_schema
        WHERE tc.table_schema = %s
          AND tc.table_name = %s
          AND tc.constraint_type = 'PRIMARY KEY'
        ORDER BY kcu.ordinal_position;
        """,
        (POSTGRES_SCHEMA, table_name),
    )
    return [row[0] for row in pg_cursor.fetchall()]


def create_mysql_table(
    mysql_cursor,
    table_name: str,
    columns: list,
    primary_keys: list[str],
):
    definitions = []

    for (
        column_name,
        data_type,
        udt_name,
        is_nullable,
        _column_default,
        max_length,
    ) in columns:
        mysql_type = map_postgres_type_to_mysql(
            data_type=data_type,
            udt_name=udt_name,
            max_length=max_length,
        )
        nullable = "NULL" if is_nullable == "YES" else "NOT NULL"
        definitions.append(f"`{column_name}` {mysql_type} {nullable}")

    if primary_keys:
        keys = ", ".join(f"`{column_name}`" for column_name in primary_keys)
        definitions.append(f"PRIMARY KEY ({keys})")

    columns_sql = ",\n        ".join(definitions)
    sql = f"""
    CREATE TABLE IF NOT EXISTS `{table_name}` (
        {columns_sql}
    )
    ENGINE=InnoDB
    DEFAULT CHARSET=utf8mb4
    COLLATE=utf8mb4_unicode_ci;
    """
    mysql_cursor.execute(sql)


def main():
    pg_conn = None
    mysql_conn = None
    pg_cursor = None
    mysql_cursor = None

    try:
        print("Conectando ao Supabase...")
        pg_conn = get_postgres_connection()

        print("Conectando ao MariaDB...")
        mysql_conn = get_mysql_connection()

        pg_cursor = pg_conn.cursor()
        mysql_cursor = mysql_conn.cursor()

        tables = get_tables(pg_cursor)

        print(f"Schema encontrado: {POSTGRES_SCHEMA}")
        print(f"Tabelas encontradas: {len(tables)}")

        if not tables:
            raise RuntimeError(
                f"Nenhuma tabela encontrada no schema '{POSTGRES_SCHEMA}'."
            )

        for table_name in tables:
            columns = get_columns(pg_cursor, table_name)
            primary_keys = get_primary_keys(pg_cursor, table_name)

            create_mysql_table(
                mysql_cursor=mysql_cursor,
                table_name=table_name,
                columns=columns,
                primary_keys=primary_keys,
            )

            print(f"Tabela criada/verificada: {table_name}")

        mysql_conn.commit()

        print("=" * 60)
        print("ESTRUTURA CRIADA COM SUCESSO NO MARIADB")
        print("=" * 60)

    except Exception as error:
        if mysql_conn:
            mysql_conn.rollback()

        print("=" * 60)
        print("ERRO AO CRIAR ESTRUTURA")
        print(f"Tipo: {type(error).__name__}")
        print(f"Detalhes: {error}")
        print("=" * 60)
        raise

    finally:
        if pg_cursor:
            pg_cursor.close()
        if mysql_cursor:
            mysql_cursor.close()
        if pg_conn:
            pg_conn.close()
        if mysql_conn:
            mysql_conn.close()


if __name__ == "__main__":
    main()
