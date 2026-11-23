from django.urls import path

from . import views

app_name = 'core'

urlpatterns = [
    path('', views.home, name='home'),
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
