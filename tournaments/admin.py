from django.contrib import admin

from .models import Court, Group, Match, MatchSet, ScoreLog, Team, Tournament


class MatchSetInline(admin.TabularInline):
    model = MatchSet
    extra = 0


class CourtInline(admin.TabularInline):
    model = Court
    extra = 0


class GroupInline(admin.TabularInline):
    model = Group
    extra = 0


@admin.register(Tournament)
class TournamentAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "date",
        "status",
        "num_groups",
        "teams_per_group",
        "num_courts",
    )
    prepopulated_fields = {"slug": ("name",)}
    inlines = [CourtInline, GroupInline]


@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    list_display = ("name", "tournament", "group", "seed", "player1", "player2")
    list_filter = ("tournament", "group")
    search_fields = ("name", "player1", "player2")


@admin.register(Match)
class MatchAdmin(admin.ModelAdmin):
    list_display = (
        "__str__",
        "tournament",
        "phase",
        "round_label",
        "court",
        "slot_index",
        "status",
        "score_display",
    )
    list_filter = ("tournament", "phase", "status", "group")
    raw_id_fields = ("team_a", "team_b", "winner", "source_a", "source_b")
    inlines = [MatchSetInline]


@admin.register(ScoreLog)
class ScoreLogAdmin(admin.ModelAdmin):
    list_display = ("created", "tournament", "action", "detail", "ip")
    list_filter = ("tournament", "action")
    readonly_fields = ("created", "tournament", "match", "action", "detail", "ip")


admin.site.register(Group)
admin.site.register(Court)
