from app import create_app
from app.extensions import get_mysql_connection


app = create_app()


def main():
    connection = None
    cursor = None

    try:
        with app.app_context():
            connection = get_mysql_connection()
            cursor = connection.cursor(dictionary=True)

            cursor.execute("SELECT DATABASE() AS banco")
            banco = cursor.fetchone()

            cursor.execute("SELECT VERSION() AS versao")
            versao = cursor.fetchone()

            cursor.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = %s
                ORDER BY table_name
                """,
                (app.config["MYSQL_DATABASE"],),
            )

            tabelas = cursor.fetchall()

            print("=" * 60)
            print("CONEXÃO DO BACKEND COM MYSQL: OK")
            print("=" * 60)
            print(f"Banco: {banco['banco']}")
            print(f"Versão: {versao['versao']}")
            print()
            print("Tabelas encontradas:")

            for tabela in tabelas:
                print(f"- {tabela['table_name']}")

    except Exception as exc:
        print("=" * 60)
        print("ERRO NA CONEXÃO DO BACKEND COM MYSQL")
        print("=" * 60)
        print(type(exc).__name__)
        print(str(exc))
        raise

    finally:
        if cursor is not None:
            cursor.close()

        if connection is not None and connection.is_connected():
            connection.close()


if __name__ == "__main__":
    main()