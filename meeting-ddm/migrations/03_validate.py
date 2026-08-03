import psycopg
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL

from config import mysql_config, postgres_config


TABLES = [
    "emails",
    "interacoes",
    "painel_acessos",
    "resumos_diarios",
    "reunioes",
    "setores",
    "usuarios",
]


def main() -> None:
    pg = postgres_config()
    pg_connect_args = {}

    if not pg.url:
        pg_connect_args = {
            "host": pg.host,
            "port": pg.port,
            "dbname": pg.database,
            "user": pg.user,
            "password": pg.password,
            "sslmode": pg.sslmode,
            "connect_timeout": 30,
        }

    my = mysql_config()
    mysql_url = URL.create(
        "mysql+mysqlconnector",
        username=my.user,
        password=my.password,
        host=my.host,
        port=my.port,
        database=my.database,
    )
    mysql_engine = create_engine(
        mysql_url,
        future=True,
        pool_pre_ping=True,
    )

    pg_connection = (
        psycopg.connect(
            pg.url,
            connect_timeout=30,
            prepare_threshold=None,
        )
        if pg.url
        else psycopg.connect(
            **pg_connect_args,
            prepare_threshold=None,
        )
    )

    validation_failed = False

    with pg_connection as pg_conn:
        with pg_conn.cursor() as pg_cursor:
            with mysql_engine.connect() as mysql_conn:
                for table_name in TABLES:
                    pg_cursor.execute(
                        f'SELECT COUNT(*) FROM meeting_ai."{table_name}"'
                    )
                    pg_count = pg_cursor.fetchone()[0]

                    mysql_count = mysql_conn.execute(
                        text(f"SELECT COUNT(*) FROM `{table_name}`")
                    ).scalar_one()

                    status = "OK" if pg_count == mysql_count else "ERRO"

                    print("-" * 60)
                    print(f"Tabela: {table_name}")
                    print(f"Postgres: {pg_count}")
                    print(f"MySQL: {mysql_count}")
                    print(f"Status: {status}")

                    if pg_count != mysql_count:
                        validation_failed = True

    print("=" * 60)

    if validation_failed:
        raise SystemExit(
            "Validation failed: existem tabelas com quantidades diferentes."
        )

    print("VALIDAÇÃO CONCLUÍDA COM SUCESSO")
    print("Todas as tabelas possuem a mesma quantidade de registros.")


if __name__ == "__main__":
    main()
