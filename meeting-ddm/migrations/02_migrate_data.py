import json
from datetime import date, datetime, time
from decimal import Decimal
from uuid import UUID

import psycopg
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL

from config import mysql_config, postgres_config


POSTGRES_SCHEMA = "meeting_ai"

TABLES = [
    "emails",
    "interacoes",
    "painel_acessos",
    "resumos_diarios",
    "reunioes",
    "setores",
    "usuarios",
]


def get_postgres_connection():
    pg = postgres_config()

    if pg.url:
        return psycopg.connect(
            pg.url,
            connect_timeout=30,
            prepare_threshold=None,
        )

    return psycopg.connect(
        host=pg.host,
        port=pg.port,
        dbname=pg.database,
        user=pg.user,
        password=pg.password,
        sslmode=pg.sslmode,
        connect_timeout=30,
        prepare_threshold=None,
    )


def get_mysql_engine():
    my = mysql_config()

    mysql_url = URL.create(
        "mysql+mysqlconnector",
        username=my.user,
        password=my.password,
        host=my.host,
        port=my.port,
        database=my.database,
    )

    return create_engine(
        mysql_url,
        future=True,
        pool_pre_ping=True,
    )


def get_postgres_columns(pg_cursor, table_name):
    pg_cursor.execute(
        """
        SELECT column_name, data_type, udt_name
        FROM information_schema.columns
        WHERE table_schema = %s
          AND table_name = %s
        ORDER BY ordinal_position;
        """,
        (POSTGRES_SCHEMA, table_name),
    )

    return pg_cursor.fetchall()


def get_mysql_columns(mysql_connection, table_name):
    result = mysql_connection.execute(
        text(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = DATABASE()
              AND table_name = :table_name
            ORDER BY ordinal_position
            """
        ),
        {"table_name": table_name},
    )

    return [row[0] for row in result.fetchall()]


def serialize_value(value, data_type, udt_name):
    if value is None:
        return None

    if isinstance(value, UUID):
        return str(value)

    if isinstance(value, (dict, list, tuple)):
        return json.dumps(
            value,
            ensure_ascii=False,
            default=str,
        )

    if data_type in ("json", "jsonb"):
        return json.dumps(
            value,
            ensure_ascii=False,
            default=str,
        )

    if data_type == "ARRAY" or udt_name.startswith("_"):
        return json.dumps(
            value,
            ensure_ascii=False,
            default=str,
        )

    if isinstance(value, Decimal):
        return value

    if isinstance(value, (datetime, date, time)):
        return value

    return value


def build_insert_sql(table_name, columns):
    quoted_columns = ", ".join(f"`{column}`" for column in columns)
    parameters = ", ".join(f":{column}" for column in columns)
    updates = ", ".join(
        f"`{column}` = VALUES(`{column}`)"
        for column in columns
    )

    return f"""
        INSERT INTO `{table_name}` (
            {quoted_columns}
        )
        VALUES (
            {parameters}
        )
        ON DUPLICATE KEY UPDATE
        {updates}
        """


def migrate_table(
    pg_cursor,
    mysql_connection,
    table_name,
):
    postgres_column_data = get_postgres_columns(
        pg_cursor,
        table_name,
    )

    if not postgres_column_data:
        print(
            f"Tabela ignorada: {table_name} "
            f"nao existe no PostgreSQL."
        )
        return 0

    mysql_columns = get_mysql_columns(
        mysql_connection,
        table_name,
    )

    if not mysql_columns:
        print(
            f"Tabela ignorada: {table_name} "
            f"nao existe no MariaDB."
        )
        return 0

    postgres_types = {
        column_name: {
            "data_type": data_type,
            "udt_name": udt_name,
        }
        for column_name, data_type, udt_name in postgres_column_data
    }

    postgres_columns = [
        column_name
        for column_name, _, _ in postgres_column_data
    ]

    common_columns = [
        column
        for column in postgres_columns
        if column in mysql_columns
    ]

    if not common_columns:
        raise RuntimeError(
            f"Nenhuma coluna compativel encontrada na tabela '{table_name}'."
        )

    select_columns = ", ".join(f'"{column}"' for column in common_columns)

    pg_cursor.execute(
        f"""
        SELECT {select_columns}
        FROM "{POSTGRES_SCHEMA}"."{table_name}"
        """
    )

    rows = pg_cursor.fetchall()
    insert_sql = text(
        build_insert_sql(
            table_name,
            common_columns,
        )
    )

    for row in rows:
        record = {}

        for column, value in zip(
            common_columns,
            row,
        ):
            column_type = postgres_types[column]
            record[column] = serialize_value(
                value=value,
                data_type=column_type["data_type"],
                udt_name=column_type["udt_name"],
            )

        mysql_connection.execute(
            insert_sql,
            record,
        )

    return len(rows)


def main():
    pg_connection = None
    mysql_engine = None

    total_migrated = 0
    results = []

    try:
        print("Conectando ao PostgreSQL...")
        pg_connection = get_postgres_connection()

        print("Conectando ao MariaDB...")
        mysql_engine = get_mysql_engine()

        with pg_connection as pg_conn:
            with pg_conn.cursor() as pg_cursor:
                with mysql_engine.begin() as mysql_connection:
                    mysql_connection.execute(
                        text("SET FOREIGN_KEY_CHECKS = 0")
                    )

                    try:
                        for table_name in TABLES:
                            print("-" * 60)
                            print(f"Migrando tabela: {table_name}")

                            migrated = migrate_table(
                                pg_cursor=pg_cursor,
                                mysql_connection=mysql_connection,
                                table_name=table_name,
                            )

                            total_migrated += migrated
                            results.append((table_name, migrated))

                            print(f"Registros processados: {migrated}")

                    finally:
                        mysql_connection.execute(
                            text("SET FOREIGN_KEY_CHECKS = 1")
                        )

        print("=" * 60)
        print("MIGRACAO CONCLUIDA")
        print("=" * 60)

        for table_name, count in results:
            print(f"{table_name}: {count}")

        print("-" * 60)
        print(f"Total de registros processados: {total_migrated}")

    except Exception as error:
        print("=" * 60)
        print("ERRO DURANTE A MIGRACAO")
        print(f"Tipo: {type(error).__name__}")
        print(f"Detalhes: {error}")
        print("=" * 60)

        raise

    finally:
        if pg_connection:
            pg_connection.close()

        if mysql_engine:
            mysql_engine.dispose()


if __name__ == "__main__":
    main()
