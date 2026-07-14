web: gunicorn run:app --bind 0.0.0.0:$PORT --workers 2 --threads 4 --timeout 300
# worker/beat: só se provisionar Redis (processamento assíncrono via Celery).
# Sem Redis o app processa em thread no próprio web — funciona p/ o fluxo Recall.
worker: celery -A celery_worker.celery worker --loglevel=info -B
