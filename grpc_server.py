"""Точка запуска gRPC сервера."""
import sys
import os
import logging
from concurrent import futures

import grpc

# чтобы импорты app.* работали из корня проекта
sys.path.insert(0, os.path.dirname(__file__))

from app.proto import gkb_parser_pb2_grpc
from app.grpc_servicer import GkbParserServicer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

_PORT = os.getenv("GRPC_PORT", "50051")
_MAX_WORKERS = int(os.getenv("GRPC_WORKERS", "4"))
# лимит на входящее сообщение — 50 МБ (PDF может быть большим)
_MAX_MSG_MB = int(os.getenv("GRPC_MAX_MSG_MB", "50"))


def serve():
    options = [
        ("grpc.max_receive_message_length", _MAX_MSG_MB * 1024 * 1024),
        ("grpc.max_send_message_length", _MAX_MSG_MB * 1024 * 1024),
    ]
    server = grpc.server(
        futures.ThreadPoolExecutor(max_workers=_MAX_WORKERS),
        options=options,
    )
    gkb_parser_pb2_grpc.add_GkbParserServicer_to_server(GkbParserServicer(), server)
    server.add_insecure_port(f"[::]:{_PORT}")
    server.start()
    logger.info(f"gRPC сервер запущен на порту {_PORT} (workers={_MAX_WORKERS})")
    server.wait_for_termination()


if __name__ == "__main__":
    serve()
