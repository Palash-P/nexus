from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from django.shortcuts import get_object_or_404
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny

from .models import KnowledgeBase, Document, Conversation, Message, Query
from .serializers import (
    KnowledgeBaseSerializer, DocumentSerializer,
    ConversationSerializer, MessageSerializer
)
from .tasks import process_document
from .rag_service import ask, chat, get_query_embedding, vector_search, build_sources


class KnowledgeBaseViewSet(viewsets.ModelViewSet):
    serializer_class = KnowledgeBaseSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return KnowledgeBase.objects.filter(owner=self.request.user)

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)


class DocumentViewSet(viewsets.ModelViewSet):
    serializer_class = DocumentSerializer
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get_queryset(self):
        return Document.objects.filter(
            knowledge_base__owner=self.request.user
        ).select_related('knowledge_base')

    def create(self, request, *args, **kwargs):
        """POST /api/documents/ — upload a document and trigger processing."""
        kb_id = request.data.get('knowledge_base')
        kb = get_object_or_404(KnowledgeBase, id=kb_id, owner=request.user)

        file = request.FILES.get('file')
        if not file:
            return Response({'error': 'No file provided'}, status=400)

        ext = file.name.rsplit('.', 1)[-1].lower()
        if ext not in ('pdf', 'txt', 'md'):
            return Response({'error': 'Unsupported file type. Use PDF, TXT, or MD.'}, status=400)

        doc = Document.objects.create(
            knowledge_base=kb,
            uploaded_by=request.user,
            title=request.data.get('title', file.name),
            file=file,
            file_type=ext,
        )

        # Fire async processing task
        process_document.delay(str(doc.id))

        serializer = self.get_serializer(doc)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'])
    def reprocess(self, request, pk=None):
        """POST /api/documents/<id>/reprocess/ — reprocess a failed/stuck doc."""
        doc = self.get_object()
        doc.status = Document.Status.PENDING
        doc.error_message = ''
        doc.save(update_fields=['status', 'error_message'])
        process_document.delay(str(doc.id))
        return Response({'status': 'reprocessing started'})


class QAView:
    """Function-based views for Q&A (simpler than ViewSet for these endpoints)."""
    pass


from rest_framework.views import APIView


class AskView(APIView):
    """POST /api/ask/ — single-shot Q&A against a knowledge base."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        kb_id = request.data.get('knowledge_base_id')
        question = request.data.get('question', '').strip()

        if not kb_id or not question:
            return Response({'error': 'knowledge_base_id and question are required'}, status=400)

        kb = get_object_or_404(KnowledgeBase, id=kb_id, owner=request.user)
        result = ask(request.user, kb, question)
        return Response(result)


class ChatView(APIView):
    """POST /api/chat/ — multi-turn chat within a conversation."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        conv_id = request.data.get('conversation_id')
        kb_id = request.data.get('knowledge_base_id')
        question = request.data.get('message', '').strip()

        if not question:
            return Response({'error': 'message is required'}, status=400)

        if conv_id:
            conversation = get_object_or_404(
                Conversation, id=conv_id, user=request.user
            )
        elif kb_id:
            kb = get_object_or_404(KnowledgeBase, id=kb_id, owner=request.user)
            conversation = Conversation.objects.create(user=request.user, knowledge_base=kb)
        else:
            return Response({'error': 'conversation_id or knowledge_base_id required'}, status=400)

        result = chat(request.user, conversation, question)
        return Response(result)


class ConversationViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = ConversationSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Conversation.objects.filter(user=self.request.user).select_related('knowledge_base')

    @action(detail=True, methods=['get'])
    def messages(self, request, pk=None):
        """GET /api/conversations/<id>/messages/"""
        conversation = self.get_object()
        messages = conversation.messages.order_by('created_at')
        serializer = MessageSerializer(messages, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['get'])
    def export(self, request, pk=None):
        """GET /api/conversations/<id>/export/ — export as plain text."""
        conversation = self.get_object()
        lines = [f"# {conversation.title or 'Conversation'}\n"]
        for msg in conversation.messages.order_by('created_at'):
            prefix = "You" if msg.role == 'user' else "Assistant"
            lines.append(f"**{prefix}:** {msg.content}\n")
        return Response({'text': '\n'.join(lines), 'title': conversation.title})


class SearchView(APIView):
    """GET /api/search/?kb=<id>&q=<query> — semantic search."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        kb_id = request.query_params.get('kb')
        query = request.query_params.get('q', '').strip()

        if not kb_id or not query:
            return Response({'error': 'kb and q params required'}, status=400)

        kb = get_object_or_404(KnowledgeBase, id=kb_id, owner=request.user)
        embedding = get_query_embedding(query)
        results = vector_search(kb.id, embedding, top_k=10)
        sources = build_sources(results)
        return Response({'query': query, 'results': sources})


class AnalyticsView(APIView):
    """GET /api/analytics/ — usage stats for the current user."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from django.db.models import Sum, Count, Avg
        from django.utils import timezone
        from datetime import timedelta

        user = request.user
        queries = Query.objects.filter(user=user)
        last_30 = queries.filter(created_at__gte=timezone.now() - timedelta(days=30))

        stats = queries.aggregate(
            total_queries=Count('id'),
            total_input_tokens=Sum('input_tokens'),
            total_output_tokens=Sum('output_tokens'),
            total_cost=Sum('estimated_cost_usd'),
            avg_response_time=Avg('response_time_ms'),
            avg_confidence=Avg('confidence'),
        )

        # Most popular questions (simple: last 20)
        recent = list(
            last_30.order_by('-created_at')
            .values('question', 'confidence', 'created_at')[:20]
        )

        # Doc stats
        doc_count = Document.objects.filter(
            knowledge_base__owner=user, status='ready'
        ).count()

        kb_count = KnowledgeBase.objects.filter(owner=user).count()

        return Response({
            'overview': {
                'total_queries': stats['total_queries'] or 0,
                'total_cost_usd': float(stats['total_cost'] or 0),
                'avg_response_time_ms': round(stats['avg_response_time'] or 0),
                'avg_confidence': round(float(stats['avg_confidence'] or 0), 3),
                'documents_indexed': doc_count,
                'knowledge_bases': kb_count,
            },
            'recent_queries': recent,
        })


# ============================================================
# ADD THESE TO THE BOTTOM OF kb/views.py
# ============================================================

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.contrib.auth import logout as auth_logout


@login_required
def home_view(request):
    from kb.models import KnowledgeBase, Document, Query
    knowledge_bases = KnowledgeBase.objects.filter(owner=request.user)
    context = {
        'knowledge_bases': knowledge_bases,
        'kb_count': knowledge_bases.count(),
        'doc_count': Document.objects.filter(knowledge_base__owner=request.user).count(),
        'query_count': Query.objects.filter(user=request.user).count(),
    }
    return render(request, 'kb/home.html', context)


@login_required
def create_kb_view(request):
    if request.method == 'POST':
        from kb.models import KnowledgeBase
        name = request.POST.get('name', '').strip()
        description = request.POST.get('description', '').strip()
        if name:
            kb = KnowledgeBase.objects.create(
                owner=request.user,
                name=name,
                description=description,
            )
            messages.success(request, f'Knowledge base "{kb.name}" created.')
            return redirect('kb:kb_detail', pk=kb.id)
    return redirect('kb:home')


@login_required
def kb_detail_view(request, pk):
    from kb.models import KnowledgeBase, Document, Query
    kb = get_object_or_404(KnowledgeBase, id=pk, owner=request.user)
    documents = Document.objects.filter(knowledge_base=kb).order_by('-created_at')
    context = {
        'kb': kb,
        'documents': documents,
        'query_count': Query.objects.filter(knowledge_base=kb).count(),
        'ready_count': documents.filter(status='ready').count(),
    }
    return render(request, 'kb/kb_detail.html', context)


@login_required
def upload_doc_view(request, pk):
    from kb.models import KnowledgeBase, Document
    from kb.tasks import process_document
    kb = get_object_or_404(KnowledgeBase, id=pk, owner=request.user)

    if request.method == 'POST':
        file = request.FILES.get('file')
        title = request.POST.get('title', '').strip()

        if not file:
            messages.error(request, 'No file selected.')
            return redirect('kb:kb_detail', pk=pk)

        ext = file.name.rsplit('.', 1)[-1].lower()
        if ext not in ('pdf', 'txt', 'md'):
            messages.error(request, 'Unsupported file type. Use PDF, TXT, or MD.')
            return redirect('kb:kb_detail', pk=pk)

        doc = Document.objects.create(
            knowledge_base=kb,
            uploaded_by=request.user,
            title=title or file.name,
            file=file,
            file_type=ext,
        )
        process_document.delay(str(doc.id))
        messages.success(request, f'"{doc.title}" uploaded. Processing started.')

    return redirect('kb:kb_detail', pk=pk)


@login_required
def analytics_view(request):
    from kb.models import Query, KnowledgeBase, Document
    from django.db.models import Sum, Count, Avg

    queries = Query.objects.filter(user=request.user)
    agg = queries.aggregate(
        total_queries=Count('id'),
        total_cost_usd=Sum('estimated_cost_usd'),
        avg_response_time_ms=Avg('response_time_ms'),
        avg_confidence=Avg('confidence'),
    )

    recent = queries.order_by('-created_at')[:20]
    recent_with_pct = []
    for q in recent:
        recent_with_pct.append({
            'question': q.question,
            'answer': q.answer,
            'confidence': q.confidence,
            'confidence_pct': round((q.confidence or 0) * 100),
            'response_time_ms': q.response_time_ms,
            'created_at': q.created_at,
        })

    stats = {
        'total_queries': agg['total_queries'] or 0,
        'total_cost_usd': round(float(agg['total_cost_usd'] or 0), 4),
        'avg_response_time_ms': round(agg['avg_response_time_ms'] or 0),
        'avg_confidence_pct': round((agg['avg_confidence'] or 0) * 100),
        'documents_indexed': Document.objects.filter(knowledge_base__owner=request.user, status='ready').count(),
        'knowledge_bases': KnowledgeBase.objects.filter(owner=request.user).count(),
    }

    return render(request, 'kb/analytics.html', {'stats': stats, 'recent_queries': recent_with_pct})


def logout_view(request):
    auth_logout(request)
    return redirect('/admin/login/?next=/')

@api_view(['GET'])
@permission_classes([AllowAny])
def health_check(request):
    from django.conf import settings
    import google.generativeai as genai
    genai.configure(api_key=settings.GEMINI_API_KEY)
    try:
        models = list(genai.list_models())
        return Response({
            'key_prefix': settings.GEMINI_API_KEY[:10],
            'models_count': len(models),
            'status': 'ok'
        })
    except Exception as e:
        return Response({
            'key_prefix': settings.GEMINI_API_KEY[:10],
            'error': str(e),
            'status': 'failed'
        })