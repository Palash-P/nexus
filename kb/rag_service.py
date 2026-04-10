"""
rag_service.py — Core RAG pipeline.

Usage:
    from kb.rag_service import ask, chat

    result = ask(user, knowledge_base, "What is our refund policy?")
    result = chat(user, conversation, "Can you clarify point 2?")
"""
import logging
import time
from django.conf import settings

logger = logging.getLogger(__name__)

GEMINI_INPUT_COST_PER_1M = 0.075
GEMINI_OUTPUT_COST_PER_1M = 0.30
EMBEDDING_MODEL = "models/gemini-embedding-001"
GENERATION_MODEL = "gemini-2.0-flash"
TOP_K = 5


def get_query_embedding(query: str) -> list:
    import google.generativeai as genai
    genai.configure(api_key=settings.GEMINI_API_KEY)
    result = genai.embed_content(
        model="models/gemini-embedding-001",
        content=query,
        task_type="retrieval_query",
    )
    return result['embedding']


def vector_search(knowledge_base_id, query_embedding: list, top_k: int = TOP_K):
    """
    Cosine similarity search via pgvector.
    Returns list of (DocumentChunk, similarity_score).
    """
    from pgvector.django import CosineDistance
    from kb.models import DocumentChunk

    chunks = (
        DocumentChunk.objects
        .filter(document__knowledge_base_id=knowledge_base_id, document__status='ready')
        .annotate(similarity=1 - CosineDistance('embedding', query_embedding))
        .order_by('-similarity')
        .select_related('document')[:top_k]
    )
    return [(chunk, float(chunk.similarity)) for chunk in chunks]


def build_context(chunks_with_scores: list) -> str:
    parts = []
    for i, (chunk, score) in enumerate(chunks_with_scores, start=1):
        doc_title = chunk.document.title
        page_info = f", page {chunk.page_number}" if chunk.page_number else ""
        parts.append(
            f"[Source {i}: {doc_title}{page_info} | relevance: {score:.2f}]\n{chunk.content}"
        )
    return "\n\n---\n\n".join(parts)


def build_sources(chunks_with_scores: list) -> list:
    return [
        {
            'source_number': i,
            'document_title': chunk.document.title,
            'document_id': str(chunk.document.id),
            'chunk_index': chunk.chunk_index,
            'page_number': chunk.page_number,
            'relevance_score': round(score, 4),
            'excerpt': chunk.content[:200] + '...' if len(chunk.content) > 200 else chunk.content,
        }
        for i, (chunk, score) in enumerate(chunks_with_scores, start=1)
    ]


RAG_SYSTEM_PROMPT = """You are a helpful assistant with access to a company knowledge base.

Rules:
1. Answer ONLY from the provided context. Never make things up.
2. If the context lacks the answer, say: "I couldn't find that in the knowledge base."
3. Cite sources like [Source 1] or [Source 2] when referencing information.
4. Be concise. Use bullet points for lists.
5. If sources conflict, flag it.
"""


def _call_gemini(prompt: str) -> tuple:
    import google.generativeai as genai
    from google.api_core.exceptions import ResourceExhausted
    from google.api_core import retry
    genai.configure(api_key=settings.GEMINI_API_KEY)
    model = genai.GenerativeModel(model_name="gemini-2.5-flash")
    try:
        response = model.generate_content(
            prompt,
            request_options={"retry": retry.Retry(predicate=retry.if_exception_type())}
        )
        answer = response.text
        try:
            in_tok = response.usage_metadata.prompt_token_count
            out_tok = response.usage_metadata.candidates_token_count
        except Exception:
            in_tok = out_tok = 0
        return answer, in_tok, out_tok
    except ResourceExhausted:
        return "⚠️ Rate limit reached. Please wait 60 seconds and try again.", 0, 0



def ask(user, knowledge_base, question: str) -> dict:
    from kb.models import Query

    start_time = time.time()
    query_embedding = get_query_embedding(question)
    chunks_with_scores = vector_search(knowledge_base.id, query_embedding)

    if not chunks_with_scores:
        return {
            'answer': "No relevant documents found. Please upload documents to this knowledge base first.",
            'sources': [],
            'confidence': 0.0,
            'tokens_used': 0,
            'response_time_ms': int((time.time() - start_time) * 1000),
        }

    context = build_context(chunks_with_scores)
    sources = build_sources(chunks_with_scores)
    confidence = chunks_with_scores[0][1]

    prompt = f"Context from knowledge base:\n{context}\n\nQuestion: {question}\n\nAnswer:"
    answer, in_tok, out_tok = _call_gemini(prompt)

    cost = (
        (in_tok / 1_000_000) * GEMINI_INPUT_COST_PER_1M +
        (out_tok / 1_000_000) * GEMINI_OUTPUT_COST_PER_1M
    )
    response_time_ms = int((time.time() - start_time) * 1000)

    Query.objects.create(
        user=user,
        knowledge_base=knowledge_base,
        question=question,
        answer=answer,
        sources=sources,
        confidence=confidence,
        input_tokens=in_tok,
        output_tokens=out_tok,
        estimated_cost_usd=cost,
        response_time_ms=response_time_ms,
    )

    return {
        'answer': answer,
        'sources': sources,
        'confidence': round(confidence, 4),
        'tokens_used': in_tok + out_tok,
        'response_time_ms': response_time_ms,
    }


def chat(user, conversation, question: str) -> dict:
    from kb.models import Message

    start_time = time.time()
    knowledge_base = conversation.knowledge_base

    query_embedding = get_query_embedding(question)
    chunks_with_scores = vector_search(knowledge_base.id, query_embedding)
    context = build_context(chunks_with_scores)
    sources = build_sources(chunks_with_scores)
    confidence = chunks_with_scores[0][1] if chunks_with_scores else 0.0

    # Last 10 messages for context window
    history = list(conversation.messages.order_by('-created_at')[:10])[::-1]
    history_text = "\n".join(
        f"{'User' if m.role == 'user' else 'Assistant'}: {m.content}"
        for m in history
    )

    prompt = (
        f"Context from knowledge base:\n{context}\n\n"
        f"Conversation so far:\n{history_text}\n\n"
        f"User: {question}\n\nAssistant:"
    )
    answer, in_tok, out_tok = _call_gemini(prompt)
    response_time_ms = int((time.time() - start_time) * 1000)

    # Auto-title the conversation from the first user message
    if not conversation.title:
        conversation.title = question[:100]
        conversation.save(update_fields=['title'])

    # Save user message + assistant reply
    Message.objects.create(
        conversation=conversation,
        role=Message.Role.USER,
        content=question,
    )
    assistant_msg = Message.objects.create(
        conversation=conversation,
        role=Message.Role.ASSISTANT,
        content=answer,
        sources=sources,
        confidence=round(confidence, 4),
        tokens_used=in_tok + out_tok,
    )

    return {
        'answer': answer,
        'sources': sources,
        'confidence': round(confidence, 4),
        'tokens_used': in_tok + out_tok,
        'response_time_ms': response_time_ms,
        'conversation_id': str(conversation.id),
        'message_id': str(assistant_msg.id),
    }
