from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    KnowledgeBaseViewSet, DocumentViewSet,
    ConversationViewSet, AskView, ChatView,
    SearchView, AnalyticsView,
    # Template views
    home_view, create_kb_view, kb_detail_view,
    upload_doc_view, analytics_view, logout_view,
)

router = DefaultRouter()
router.register(r'knowledge-bases', KnowledgeBaseViewSet, basename='knowledgebase')
router.register(r'documents', DocumentViewSet, basename='document')
router.register(r'conversations', ConversationViewSet, basename='conversation')

# API URLs
api_urlpatterns = [
    path('', include(router.urls)),
    path('ask/', AskView.as_view(), name='ask'),
    path('chat/', ChatView.as_view(), name='chat'),
    path('search/', SearchView.as_view(), name='search'),
    path('analytics/', AnalyticsView.as_view(), name='analytics'),
]

# Template URLs
app_name = 'kb'
urlpatterns = [
    # Template pages
    path('', home_view, name='home'),
    path('kb/create/', create_kb_view, name='create_kb'),
    path('kb/<uuid:pk>/', kb_detail_view, name='kb_detail'),
    path('kb/<uuid:pk>/upload/', upload_doc_view, name='upload_doc'),
    path('analytics/', analytics_view, name='analytics'),
    path('logout/', logout_view, name='logout'),

    # API
    path('api/', include(api_urlpatterns)),
]