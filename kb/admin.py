from django.contrib import admin
from .models import KnowledgeBase, Document, DocumentChunk, Conversation, Message, Query

@admin.register(KnowledgeBase)
class KnowledgeBaseAdmin(admin.ModelAdmin):
    list_display = ['name', 'owner', 'created_at']
    search_fields = ['name', 'owner__username']

@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = ['title', 'knowledge_base', 'status', 'total_chunks', 'created_at']
    list_filter = ['status']
    search_fields = ['title']

@admin.register(DocumentChunk)
class DocumentChunkAdmin(admin.ModelAdmin):
    list_display = ['document', 'chunk_index', 'page_number', 'created_at']
    search_fields = ['document__title']

@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ['title', 'user', 'knowledge_base', 'created_at']

@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ['conversation', 'role', 'created_at']
    list_filter = ['role']

@admin.register(Query)
class QueryAdmin(admin.ModelAdmin):
    list_display = ['user', 'question', 'confidence', 'response_time_ms', 'created_at']