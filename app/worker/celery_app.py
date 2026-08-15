from celery import Celery
from celery.schedules import crontab

celery_app = Celery(
    "price_tracker",
    broker="redis://redis:6379/0",
    backend="redis://redis:6379/0",
    include=["app.worker.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    broker_connection_retry_on_startup=True,
    worker_send_task_events=True,
    task_send_sent_event=True,
)

celery_app.conf.beat_schedule = {
    "update-prices-daily": {
        "task": "dispatch_price_checks",
        "schedule": crontab(hour=3, minute=0),
    },
    "dispatch-pending-telegram-notifications": {
        "task": "dispatch_pending_telegram_notifications",
        "schedule": crontab(minute="*"),
    },
}
