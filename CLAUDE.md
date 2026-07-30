# Brown Bear

Local AI/ML infrastructure stack for running LLMs with vector storage and management.

## Overview

Brown Bear provides a self-hosted, Docker-based environment for local LLM inference and vector database operations. Everything runs via Docker Compose on a single machine.

## Architecture

```
┌─────────────────────────────────────────────────┐
│                  Brown Bear                      │
│                                                  │
│  ┌──────────┐  ┌──────────┐  ┌──────────────┐  │
│  │  Ollama  │  │ ChromaDB │  │ VectorAdmin  │  │
│  │  :11434  │  │  :8000   │  │    :3002     │  │
│  └──────────┘  └──────────┘  └──────┬───────┘  │
│                                     │           │
│  ┌──────────┐  ┌──────────────┐     │           │
│  │  Redis   │  │  PostgreSQL  │◄────┘           │
│  │  :6379   │  │    :5432     │                │
│  └────┬─────┘  └──────────────┘                │
│       │                                         │
│  ┌────┴─────┐                                   │
│  │RedisInsi-│                                   │
│  │ght :5540 │                                   │
│  └──────────┘                                   │
└─────────────────────────────────────────────────┘
```

## Services

| Service | Image | Port | Purpose |
|---------|-------|------|---------|
| `ollama` | `ollama/ollama:latest` | `11434` | Local LLM inference server |
| `chromadb` | `chromadb/chroma:latest` | `8000` | Vector database for embeddings |
| `postgres` | `postgres:16-alpine` | `5432` | VectorAdmin metadata database |
| `vectoradmin` | `mintplexlabs/vectoradmin:latest` | `3002` (→ 3000) | ChromaDB admin/management UI |
| `redis` | `redis:7-alpine` | `6379` | Caching, sessions, queues |
| `redisinsight` | `redis/redisinsight:latest` | `5540` | Redis GUI / monitoring |

## Tech Stack

- **LLM Serving:** Ollama (supports Llama, Mistral, Phi, Gemma, etc.)
- **Vector DB:** ChromaDB (persistent, with collection management)
- **Vector Admin UI:** VectorAdmin (browse collections, manage embeddings)
- **Metadata DB:** PostgreSQL 16
- **Cache/Sessions:** Redis 7 (password-protected)
- **Redis GUI:** RedisInsight
- **Orchestration:** Docker Compose v3.8

## Getting Started

### Prerequisites

- Docker Engine 20.10+
- Docker Compose v2+
- ~4GB+ RAM (more for larger models)

### Start all services

```bash
docker compose up -d
```

### Pull an Ollama model

```bash
# Enter the Ollama container
docker exec -it ollama bash

# Pull a model (e.g., llama3, mistral, phi3)
ollama pull llama3
```

### Access the UIs

| Service | URL |
|---------|-----|
| Ollama API | `http://localhost:11434` |
| ChromaDB API | `http://localhost:8000` |
| VectorAdmin | `http://localhost:3002` |
| RedisInsight | `http://localhost:5540` |

### Verify services

```bash
# Check all containers are running
docker compose ps

# Test Ollama
curl http://localhost:11434/api/tags

# Test ChromaDB
curl http://localhost:8000/api/v1/heartbeat
```

## Usage

### Ollama — Generate embeddings

```bash
curl http://localhost:11434/api/embed -d '{
  "model": "llama3",
  "input": "Hello world"
}'
```

### Ollama — Chat completion

```bash
curl http://localhost:11434/api/chat -d '{
  "model": "llama3",
  "messages": [{"role": "user", "content": "Hello!"}]
}'
```

### ChromaDB — Create collection & add documents

```python
import chromadb

client = chromadb.HttpClient(host="localhost", port=8000)
collection = client.create_collection("my_collection")

collection.add(
    documents=["Document 1", "Document 2"],
    ids=["doc1", "doc2"],
    embeddings=[[0.1, 0.2, ...], [0.3, 0.4, ...]]
)

results = collection.query(query_embeddings=[[0.1, 0.2, ...]], n_results=2)
```

### VectorAdmin

Open `http://localhost:3002` in your browser to browse and manage ChromaDB collections through the web UI.

## Security Notes

- **Redis** is password-protected (change `your_strong_password` in `compose.yaml`)
- **VectorAdmin** JWT secret and Inngest keys should be changed before production use
- **PostgreSQL** credentials are local-only (not exposed beyond Docker network)
- GPU support for Ollama is available but commented out — uncomment the `deploy` block if NVIDIA GPU is available

## Project Structure

```
brown_bear/
├── compose.yaml        # Docker Compose — all services defined here
└── QWEN.md             # This file
```

## Future Considerations

- Add application code that integrates Ollama + ChromaDB (RAG pipeline, chatbot, etc.)
- Configure Ollama GPU acceleration if hardware supports it
- Add monitoring (Prometheus + Grafana)
- Add Nginx/Caddy reverse proxy with TLS
- Environment-specific compose overrides (`.env`, `compose.prod.yaml`)
