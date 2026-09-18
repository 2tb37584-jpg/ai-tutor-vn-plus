# Technology decisions — September 2026 baseline

## Frontend
Next.js 16.x + TypeScript. App Router is suitable for the product dashboard and web client.

## Backend
FastAPI 0.141.x + Python 3.12. Python is chosen because math/science tooling and evaluation pipelines are first-class requirements.

## Database
PostgreSQL 16. No vector database is required for MVP. Add pgvector or provider-hosted file search only when curriculum retrieval becomes necessary.

## AI
OpenAI Responses API, multimodal image input and structured outputs.
Default model is configured through `OPENAI_MODEL`; do not hard-code routing decisions throughout application code.

## Verification
SymPy for the first narrow class of algebra checks. Verification is a pluggable interface conceptually; chemistry, geometry and prose answers require different strategies.

## Why not microservices
Until load/team boundaries demand it, service decomposition would increase deployment, tracing, schema and local-development complexity without improving learning quality.
