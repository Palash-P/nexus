# ⬡ Nexus — AI Knowledge Base

An enterprise-grade AI-powered knowledge base platform where teams can upload documents, ask questions, and get instant answers with citations — built with Django, pgvector, Celery, and Google Gemini.

**Live Demo:** [nexus-production-6a7c.up.railway.app](https://nexus-production-6a7c.up.railway.app)

---

## What it does

Nexus lets you upload company documents (PDFs, TXT, Markdown) and chat with them using AI. It uses RAG (Retrieval-Augmented Generation) to find the most relevant parts of your documents and generate accurate, cited answers.

- Upload documents → they get chunked and embedded automatically in the background
- Ask questions in natural language → get answers with source citations and confidence scores
- Multi-turn chat → conversations remember context across messages
- Analytics dashboard → track queries, costs, and response times

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Django 6.0 + Django REST Framework |
| Database | PostgreSQL + pgvector (vector similarity search) |
| AI | Google Gemini (gemini-2.5-flash + gemini-embedding-001) |
| Task Queue | Celery + Redis |
| Frontend | Django Templates |
| Deployment | Railway |

---

## Architecture

```
User uploads PDF
      ↓
Django view saves file → fires Celery task
      ↓
Celery worker: extract text → chunk (800 chars, 100 overlap) → embed with Gemini
      ↓
Store 3072-dim vectors in pgvector (PostgreSQL)

User asks question
      ↓
Embed question → cosine similarity search in pgvector → top 5 chunks
      ↓
Build context + send to Gemini → cited answer
      ↓
Log query (tokens, cost, confidence, response time)
```

---

## Key Concepts

**RAG (Retrieval-Augmented Generation)** — Instead of sending entire documents to the LLM (expensive, slow, hits context limits), we embed documents as vectors and only retrieve the relevant chunks per question. This keeps costs low and accuracy high.

**Chunking with overlap** — Documents are split into 800-character chunks with 100-character overlap at boundaries. The overlap ensures sentences that fall across chunk boundaries aren't lost.

**pgvector** — PostgreSQL extension for storing and searching vectors. Chosen over dedicated vector databases (Pinecone, ChromaDB) to keep everything in one database with transactional consistency.

**Celery** — Document processing (extraction + embedding) can take 30-60 seconds. Celery moves this to a background worker so the API responds immediately.

**Cosine similarity** — Used instead of Euclidean distance because it measures the angle between vectors (meaning), not their magnitude (length). A short and long document about the same topic will have similar angles but different magnitudes.

---

## API Endpoints

```
# Authentication
POST   /api/auth/token/              — get auth token

# Knowledge Bases
GET    /api/knowledge-bases/         — list all KBs
POST   /api/knowledge-bases/         — create KB
GET    /api/knowledge-bases/<id>/    — get KB detail

# Documents
POST   /api/documents/               — upload document
GET    /api/documents/               — list documents
POST   /api/documents/<id>/reprocess/ — reprocess failed doc

# Q&A
POST   /api/ask/                     — single-shot Q&A
POST   /api/chat/                    — multi-turn chat

# Search
GET    /api/search/?kb=<id>&q=<query> — semantic search

# Analytics
GET    /api/analytics/               — usage stats
```

---

## Models

```python
KnowledgeBase    # collection of documents, owned by a user
Document         # uploaded file with processing status
DocumentChunk    # text chunk with 3072-dim vector embedding
Conversation     # persistent chat session
Message          # individual message in a conversation
Query            # logged Q&A call with cost + confidence tracking
```

---

## Local Setup

**Prerequisites:** Python 3.11+, PostgreSQL with pgvector, Redis, Google Gemini API key

```bash
# Clone
git clone https://github.com/your-username/nexus.git
cd nexus

# Install dependencies
pip install -r requirements.txt

# Environment variables
cp .env.example .env
# Edit .env with your values

# Database
createdb nexus
python manage.py migrate

# Create superuser
python manage.py createsuperuser

# Run all services
python manage.py runserver          # terminal 1
celery -A nexus worker --pool=solo  # terminal 2 (Windows)
```

Visit `http://127.0.0.1:8000`

---

## Environment Variables

```
SECRET_KEY=your-django-secret-key
DEBUG=True
GEMINI_API_KEY=your-gemini-api-key
DB_NAME=nexus
DB_USER=postgres
DB_PASSWORD=your-password
DB_HOST=127.0.0.1
DB_PORT=5432
REDIS_URL=redis://localhost:6379/0
ALLOWED_HOSTS=localhost,127.0.0.1
CSRF_TRUSTED_ORIGINS=http://localhost:8000
```

---

## Deployment (Railway)

1. Push to GitHub
2. Create Railway project → Deploy from GitHub
3. Add PostgreSQL and Redis services
4. Set environment variables (see above)
5. Start command:
```
python manage.py migrate && python manage.py collectstatic --noinput && gunicorn nexus.wsgi:application --bind 0.0.0.0:$PORT
```
6. Add a second service for the Celery worker:
```
celery -A nexus worker --loglevel=info --pool=solo
```

---

## Project Structure

```
nexus/
├── nexus/              # Django project config
│   ├── settings.py
│   ├── urls.py
│   └── celery.py
├── kb/                 # Main app
│   ├── models.py       # All database models
│   ├── views.py        # API + template views
│   ├── serializers.py  # DRF serializers
│   ├── tasks.py        # Celery document processing
│   ├── rag_service.py  # Core RAG pipeline
│   └── urls.py         # URL routing
├── templates/
│   └── kb/             # Django templates
│       ├── base.html
│       ├── home.html
│       ├── kb_detail.html
│       └── analytics.html
├── requirements.txt
├── Procfile
└── railway.json
```

---

## Built by

Palash — Flutter & Django developer  
[palash-p.github.io](https://palash-p.github.io) · [GitHub](https://github.com/your-username)
