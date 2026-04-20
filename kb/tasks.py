import logging
import time
import tempfile
import os
import urllib.request
from celery import shared_task
from django.utils import timezone
from django.conf import settings

logger = logging.getLogger(__name__)

CHUNK_SIZE = 800
CHUNK_OVERLAP = 100


def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    if not text.strip():
        return []
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        start = end - overlap
        if start >= len(text):
            break
    return chunks


def extract_text_from_pdf(file_path: str) -> tuple[str, dict[int, str]]:
    try:
        import pdfplumber
        page_texts = {}
        full_text = ""
        with pdfplumber.open(file_path) as pdf:
            for i, page in enumerate(pdf.pages, start=1):
                text = page.extract_text() or ""
                page_texts[i] = text
                full_text += f"\n{text}"
        return full_text, page_texts
    except Exception as e:
        logger.error(f"PDF extraction failed: {e}")
        try:
            import PyPDF2
            page_texts = {}
            full_text = ""
            with open(file_path, 'rb') as f:
                reader = PyPDF2.PdfReader(f)
                for i, page in enumerate(reader.pages, start=1):
                    text = page.extract_text() or ""
                    page_texts[i] = text
                    full_text += f"\n{text}"
            return full_text, page_texts
        except Exception as e2:
            raise Exception(f"PDF extraction failed with both methods: {e2}")


def get_embeddings(texts: list) -> list:
    import google.generativeai as genai
    genai.configure(api_key=settings.GEMINI_API_KEY)
    embeddings = []
    batch_size = 5
    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        result = genai.embed_content(
            model="models/gemini-embedding-001",
            content=batch,
            task_type="retrieval_document",
        )
        embeddings.extend(result['embedding'])
        time.sleep(1)
    return embeddings


def download_to_temp(file_url: str, suffix: str) -> str:
    """Download file from Cloudinary URL to a temp file, return temp path."""
    tmp = tempfile.NamedTemporaryFile(suffix=f'.{suffix}', delete=False)
    tmp.close()
    urllib.request.urlretrieve(file_url, tmp.name)
    return tmp.name


@shared_task(bind=True, max_retries=3)
def process_document(self, document_id: str):
    from kb.models import Document, DocumentChunk

    try:
        doc = Document.objects.get(id=document_id)
    except Document.DoesNotExist:
        logger.error(f"Document {document_id} not found")
        return
    
    # ADD THESE TWO LINES
    logger.info(f"File name: {doc.file.name}")
    logger.info(f"File URL: {doc.file.url}")


    doc.status = Document.Status.PROCESSING
    doc.save(update_fields=['status'])

    tmp_path = None

    try:
        # ✅ Use URL instead of local path (Cloudinary fix)
        file_url = doc.file.url
        tmp_path = download_to_temp(file_url, doc.file_type)

        # 1. Extract text
        if doc.file_type == 'pdf':
            full_text, page_texts = extract_text_from_pdf(tmp_path)
        else:
            with open(tmp_path, 'r', encoding='utf-8', errors='ignore') as f:
                full_text = f.read()
            page_texts = {1: full_text}

        full_text = full_text.replace('\x00', '')
        page_texts = {k: v.replace('\x00', '') for k, v in page_texts.items()}

        if not full_text.strip():
            raise ValueError("No text could be extracted from this document")

        # 2. Chunk with page tracking
        chunks_with_pages = []
        if doc.file_type == 'pdf' and page_texts:
            for page_num, page_text in page_texts.items():
                page_chunks = chunk_text(page_text)
                for chunk in page_chunks:
                    chunks_with_pages.append({'text': chunk, 'page': page_num})
        else:
            for chunk in chunk_text(full_text):
                chunks_with_pages.append({'text': chunk, 'page': None})

        if not chunks_with_pages:
            raise ValueError("Document produced no chunks after processing")

        # 3. Embed
        texts_to_embed = [c['text'] for c in chunks_with_pages]
        embeddings = get_embeddings(texts_to_embed)

        # 4. Delete old chunks if reprocessing
        DocumentChunk.objects.filter(document=doc).delete()

        # 5. Bulk create
        chunk_objects = [
            DocumentChunk(
                document=doc,
                content=chunks_with_pages[i]['text'],
                embedding=embeddings[i],
                chunk_index=i,
                page_number=chunks_with_pages[i]['page'],
                metadata={'char_count': len(chunks_with_pages[i]['text'])},
            )
            for i in range(len(chunks_with_pages))
        ]
        DocumentChunk.objects.bulk_create(chunk_objects, batch_size=50)

        # 6. Mark done
        doc.status = Document.Status.READY
        doc.total_chunks = len(chunk_objects)
        doc.processed_at = timezone.now()
        doc.error_message = ''
        doc.save(update_fields=['status', 'total_chunks', 'processed_at', 'error_message'])

        logger.info(f"Document {doc.title}: {len(chunk_objects)} chunks created")

    except Exception as exc:
        logger.error(f"Document {document_id} processing failed: {exc}")
        doc.status = Document.Status.FAILED
        doc.error_message = str(exc)
        doc.save(update_fields=['status', 'error_message'])
        raise self.retry(exc=exc, countdown=60)

    finally:
        # Always clean up temp file
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)