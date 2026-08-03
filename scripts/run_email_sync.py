from app import create_app
from app.workers.tasks import (
    sync_emails_outlook,
    sync_emails_imap,
)


app = create_app()


def main():
    with app.app_context():
        print("Sincronizando e-mails Outlook...")
        sync_emails_outlook.run()

        print("Sincronizando e-mails IMAP...")
        sync_emails_imap.run()

        print("Sincronização concluída.")


if __name__ == "__main__":
    main()
