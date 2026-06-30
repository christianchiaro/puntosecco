from django.urls import path

from . import views

app_name = "tournaments"

urlpatterns = [
    path("nuovo/", views.new_tournament, name="new"),
    path("t/<slug:slug>/", views.dashboard, name="dashboard"),
    path("t/<slug:slug>/iscrizione/", views.register, name="register"),
    path("t/<slug:slug>/gestione/", views.manage, name="manage"),
    path("t/<slug:slug>/classifiche/", views.standings, name="standings"),
    path(
        "t/<slug:slug>/classifiche/board/",
        views.standings_board,
        name="standings_board",
    ),
    path("t/<slug:slug>/spareggio/", views.spareggio, name="spareggio"),
    path("t/<slug:slug>/calendario/", views.schedule, name="schedule"),
    path("t/<slug:slug>/tabelloni/", views.brackets, name="brackets"),
    path("t/<slug:slug>/classifica/", views.classifica, name="classifica"),
    path("t/<slug:slug>/live/", views.live, name="live"),
    path("t/<slug:slug>/live/board/", views.live_board, name="live_board"),
    path("t/<slug:slug>/tv/", views.tv, name="tv"),
    path("t/<slug:slug>/tv/board/", views.tv_board, name="tv_board"),
    path("t/<slug:slug>/statistiche/", views.stats, name="stats"),
    path("t/<slug:slug>/albo/", views.albo, name="albo"),
    path("t/<slug:slug>/registro/", views.score_log, name="score_log"),
    path("t/<slug:slug>/squadra/<int:team_id>/", views.team_detail, name="team"),
    # Area staff
    path("t/<slug:slug>/staff/", views.score_panel, name="score_panel"),
    path(
        "t/<slug:slug>/staff/match/<int:match_id>/",
        views.score_match,
        name="score_match",
    ),
    path(
        "t/<slug:slug>/staff/match/<int:match_id>/status/",
        views.set_match_status,
        name="set_match_status",
    ),
    # Pagina partita pubblica
    path(
        "t/<slug:slug>/partita/<int:match_id>/",
        views.match_detail,
        name="match_detail",
    ),
    path(
        "t/<slug:slug>/partita/<int:match_id>/live/",
        views.match_live,
        name="match_live",
    ),
    path(
        "t/<slug:slug>/partita/<int:match_id>/og.png",
        views.match_og_image,
        name="match_og_image",
    ),
]
