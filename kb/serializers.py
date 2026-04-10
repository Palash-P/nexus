from rest_framework import serializers
from .models import KnowledgeBase, Document, Conversation, Message, Query


class KnowledgeBaseSerializer(serializers.ModelSerializer):
    document_count = serializers.SerializerMethodField()

    class Meta:
        model = KnowledgeBase
        fields = ['id', 'name', 'description', 'document_count', 'created_at']
        read_only_fields = ['id', 'created_at']

    def get_document_count(self, obj):
        return obj.documents.count()


class DocumentSerializer(serializers.ModelSerializer):
    file = serializers.FileField(write_only=True, required=True)

    class Meta:
        model = Document
        fields = ['id', 'knowledge_base', 'title', 'file', 'file_type', 'status', 'total_chunks', 'created_at', 'processed_at', 'error_message']
        read_only_fields = ['id', 'file_type', 'status', 'total_chunks', 'created_at', 'processed_at', 'error_message']

class MessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = Message
        fields = ['id', 'role', 'content', 'sources', 'confidence', 'created_at']


class ConversationSerializer(serializers.ModelSerializer):
    message_count = serializers.SerializerMethodField()

    class Meta:
        model = Conversation
        fields = ['id', 'title', 'knowledge_base', 'message_count', 'created_at', 'updated_at']

    def get_message_count(self, obj):
        return obj.messages.count()