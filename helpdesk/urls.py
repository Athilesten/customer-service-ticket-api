from django.urls import path

from tickets import browser, views

handler400 = "tickets.http.bad_request"
handler404 = "tickets.http.not_found"

urlpatterns = [
    path("", browser.console, name="ticket-console"),
    path("console/assets/<str:name>", browser.asset, name="ticket-console-asset"),
    path("health/live", views.live, name="live"),
    path("health/ready", views.ready, name="ready"),
    path("api/v1/me", views.identity, name="actor-identity"),
    path("api/v1/tickets", views.tickets, name="tickets"),
    path("api/v1/tickets/<uuid:ticket_id>", views.ticket_detail, name="ticket-detail"),
    path("api/v1/tickets/<uuid:ticket_id>/assignment", views.assign, name="ticket-assignment"),
    path("api/v1/tickets/<uuid:ticket_id>/priority", views.reprioritize, name="ticket-priority"),
    path("api/v1/tickets/<uuid:ticket_id>/transition", views.transition, name="ticket-transition"),
    path("api/v1/tickets/<uuid:ticket_id>/audit", views.audit, name="ticket-audit"),
    path("api/v1/metrics/queue", views.metrics, name="queue-metrics"),
]
