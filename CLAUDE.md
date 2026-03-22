# CLAUDE.md

## Project Overview

GKB-Parser is a Python microservice that parses Kazakhstan credit bureau (ГКБ) PDF reports into structured JSON. It exposes both REST (FastAPI) and gRPC interfaces. Supports full-form and short-form reports, including digitally signed (ЭЦП) PDFs.

## Repository Structure

```
app/
  main.py              # FastAPI app: /health, /parse, /parse/summary
  parser.py            # Core parsing pipeline (EDS stripping, text extraction, routing)
  models.py            # Pydantic models (GkbReport and nested types)
  grpc_servicer.py     # gRPC service implementation
  extractors/
    personal.py        # Personal info extraction (FIO, IIN, contacts, ban info)
    obligations.py     # Credit obligation parsing (contracts, overdue history)
    tables.py          # PDF table extraction (documents, applications, queries)
    short.py           # Short-form report parser
  proto/
    gkb_parser_pb2.py      # Generated protobuf messages
    gkb_parser_pb2_grpc.py # Generated gRPC stubs
proto/
  gkb_parser.proto     # Protobuf service/message definitions (source of truth)
grpc_server.py         # gRPC server entry point
client.py              # gRPC test client
requirements.txt       # Python dependencies
```

## Running the Service

```bash
# Install dependencies
pip install -r requirements.txt

# REST API (FastAPI)
uvicorn app.main:app --host 0.0.0.0 --port 8000
# OpenAPI docs at /docs

# gRPC server
python grpc_server.py

# gRPC test client
python client.py [--host HOST] [--port PORT] <file.pdf>
```

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `GRPC_PORT` | `50051` | gRPC server port |
| `GRPC_WORKERS` | `4` | ThreadPoolExecutor max workers |
| `GRPC_MAX_MSG_MB` | `50` | Max gRPC message size in MB |

## External Dependencies

- **pdftotext** (system utility) - preferred for text extraction; falls back to pdfplumber if unavailable
- **protoc** - needed to regenerate proto files from `proto/gkb_parser.proto`

## Architecture & Parsing Pipeline

1. Strip EDS (digital signature) prefix if present (locate `%PDF` marker)
2. Extract text via `pdftotext -layout` (fallback: pdfplumber)
3. Detect report type: "краткая форма" → `gkb_short`, otherwise `gkb_full`
4. Route to appropriate parser:
   - **Full form**: extract personal info, addresses, bankruptcy, obligations, tables
   - **Short form**: `extractors/short.py` handles abbreviated format
5. Assemble into `GkbReport` Pydantic model → JSON

## Code Conventions

- **Language**: Python with type hints; domain terms and comments in Russian
- **Naming**: snake_case for functions/variables, PascalCase for classes, `_` prefix for private helpers
- **Parsing pattern**: regex-based text extraction with layout-aware two-column handling (split on 2+ spaces)
- **Helper utilities**: `_clean()`, `_extract()`, `_extract_float()`, `_extract_int()` in each extractor module
- **Models**: Pydantic v2 with `Optional` fields defaulting to `None`
- **Error handling**: try/except at API entry points; extractors raise on malformed input

## API Endpoints

**REST (FastAPI)**:
- `GET /health` — health check
- `POST /parse` — full PDF parse → GkbReport JSON
- `POST /parse/summary` — quick summary (name, IIN, counts, debt)

**gRPC** (defined in `proto/gkb_parser.proto`):
- `Health`, `Parse`, `ParseSummary`

## Testing

No automated test suite exists. Manual testing via `client.py` against sample PDFs.

## CI/CD, Linting, Formatting

None configured. No linter, formatter, or CI pipeline files present.

## Key Notes for AI Assistants

- PDF parsing is regex-heavy and layout-sensitive — changes to extractors require careful testing with actual PDFs
- The proto files in `app/proto/` are **generated** — edit `proto/gkb_parser.proto` and regenerate
- `.gitignore` excludes `*.pdf`, `samples_short/`, `results/`, `Dockerfile`, `docker-compose.yml`
- The service handles Kazakh credit bureau reports — field names map to Kazakh/Russian financial terminology
