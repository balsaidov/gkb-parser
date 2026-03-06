"""gRPC клиент для тестирования gkb-parser."""
import sys
import json
import grpc
from app.proto import gkb_parser_pb2, gkb_parser_pb2_grpc


def main():
    host = "localhost"
    port = 50051
    pdf_path = None

    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "--host" and i + 1 < len(args):
            host = args[i + 1]
            i += 2
        elif args[i] == "--port" and i + 1 < len(args):
            port = int(args[i + 1])
            i += 2
        else:
            pdf_path = args[i]
            i += 1

    channel = grpc.insecure_channel(f"{host}:{port}")
    stub = gkb_parser_pb2_grpc.GkbParserStub(channel)

    # Health check
    health = stub.Health(gkb_parser_pb2.HealthRequest())
    print(f"Health: {health.status}")

    if not pdf_path:
        print("Usage: python client.py [--host HOST] [--port PORT] <file.pdf>")
        return

    with open(pdf_path, "rb") as f:
        pdf_bytes = f.read()

    # Parse
    resp = stub.Parse(gkb_parser_pb2.ParseRequest(pdf_data=pdf_bytes))
    r = resp.report

    result = {
        "client_name": r.client_name,
        "iin": r.iin or None,
        "report_type": r.report_type or None,
        "birth_date": r.birth_date or None,
        "gender": r.gender or None,
        "active_obligations": [],
        "completed_obligations": len(r.completed_obligations),
    }

    for o in r.active_obligations:
        result["active_obligations"].append({
            "creditor": o.creditor,
            "contract_number": o.contract_number,
            "overdue_amount": o.overdue_amount if o.HasField("overdue_amount") else None,
            "overdue_days": o.overdue_days if o.HasField("overdue_days") else None,
            "last_payment_date": o.last_payment_date or None,
            "last_payment_amount": o.last_payment_amount if o.HasField("last_payment_amount") else None,
        })

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
