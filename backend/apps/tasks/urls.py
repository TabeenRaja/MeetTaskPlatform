from django.urls import include, path
from rest_framework.routers import DefaultRouter
from .views import TaskViewSet
from .workload import WorkloadView

router = DefaultRouter()
router.register("tasks", TaskViewSet, basename="tasks")
urlpatterns = [path("workload/", WorkloadView.as_view()), path("", include(router.urls))]
