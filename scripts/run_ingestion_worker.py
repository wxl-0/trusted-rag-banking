#!/usr/bin/env python
import logging

from src.database import get_database
from src.document_uploads import get_ingestion_queue, get_object_store
from src.ingestion_worker import IngestionWorker


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def main() -> None:
    queue = get_ingestion_queue()
    worker = IngestionWorker(get_database(), get_object_store())
    queue.heartbeat()
    for job in worker.recoverable_jobs():
        queue.enqueue(job)
    logger.info("ingestion worker started")
    while True:
        try:
            queue.heartbeat()
            job = queue.dequeue()
            if job is not None:
                result = worker.process(job)
                if result == "retry":
                    queue.enqueue(job)
            else:
                for recoverable_job in worker.recoverable_jobs():
                    queue.enqueue(recoverable_job)
        except KeyboardInterrupt:
            return
        except Exception:
            logger.exception("ingestion worker loop failed")


if __name__ == "__main__":
    main()
