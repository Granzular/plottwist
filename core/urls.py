from django.urls import path
from django.views.generic import TemplateView

from . import views

app_name = 'core'

urlpatterns = [
    path('workspace/', views.home, name='home'),
    path(
        '',
        TemplateView.as_view(template_name='core/public/home.html'),
        name='public_home',
    ),
    path('guide/', views.user_guide, name='user_guide'),
    path(
        'about/',
        TemplateView.as_view(template_name='core/public/about.html'),
        name='about',
    ),
    path(
        'contact/',
        TemplateView.as_view(template_name='core/public/contact.html'),
        name='contact',
    ),
    path('privacy/', views.privacy_policy, name='privacy'),
    path(
        'terms/',
        TemplateView.as_view(template_name='core/public/terms.html'),
        name='terms',
    ),
    path('run/', views.run, name='run'),
    path('results/<uuid:execution_id>/figures/<int:index>/', views.figure, name='figure'),
    path('results/<uuid:execution_id>/figures/<int:index>/download/<str:format>/',
         views.download, {'kind': 'figure'}, name='download_figure'),
    path('results/<uuid:execution_id>/download/<str:format>/',
         views.download, {'kind': 'combined'}, name='download_figures'),
    path('results/<uuid:execution_id>/python/',
         views.download, {'kind': 'python', 'format': 'py'}, name='download_python'),
    path('results/<uuid:execution_id>/matlab/',
         views.download, {'kind': 'matlab', 'format': 'm'}, name='download_matlab'),
]
