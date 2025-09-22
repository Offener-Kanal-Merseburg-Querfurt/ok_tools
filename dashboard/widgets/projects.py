from datetime import datetime
from datetime import timedelta
from django.db.models import Avg
from django.db.models import Count
from django.db.models import Q
from django.db.models import Sum
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from projects.models import MediaEducationSupervisor
from projects.models import Project
from projects.models import ProjectCategory
from projects.models import ProjectLeader
from projects.models import TargetGroup


class ProjectsWidget:
    """Widget for projects statistics and analytics."""

    def __init__(self, request):
        self.request = request
        self._cache = {}
        self._cache_timeout = 300  # 5 minutes

    def get_data(self):
        """Get all projects data."""
        return {
            'basic_stats': self.get_basic_stats(),
            'projects_by_category': self.get_projects_by_category(),
            'projects_by_target_group': self.get_projects_by_target_group(),
            'projects_by_leader': self.get_projects_by_leader(),
            'projects_trend': self.get_projects_trend(),
            'participants_stats': self.get_participants_stats(),
            'demographic_stats': self.get_demographic_stats(),
            'project_characteristics': self.get_project_characteristics(),
        }

    def get_basic_stats(self):
        """Get basic project statistics."""
        filtered_projects = self._get_filtered_projects()

        total_projects = filtered_projects.count()
        external_venue_projects = filtered_projects.filter(external_venue=True).count()
        jugendmedienschutz_projects = filtered_projects.filter(jugendmedienschutz=True).count()
        democracy_projects = filtered_projects.filter(democracy_project=True).count()

        # Calculate total participants
        total_participants = filtered_projects.aggregate(
            total=Sum('tn_female') + Sum('tn_male') + Sum('tn_gender_not_given') + Sum('tn_diverse')
        )['total'] or 0

        # Calculate average participants per project
        avg_participants = filtered_projects.aggregate(
            avg=Avg('tn_female') + Avg('tn_male') + Avg('tn_gender_not_given') + Avg('tn_diverse')
        )['avg'] or 0

        return {
            'total_projects': total_projects,
            'external_venue_projects': external_venue_projects,
            'jugendmedienschutz_projects': jugendmedienschutz_projects,
            'democracy_projects': democracy_projects,
            'total_participants': total_participants,
            'avg_participants_per_project': round(avg_participants, 1),
        }

    def get_projects_by_category(self):
        """Get projects grouped by category."""
        filtered_projects = self._get_filtered_projects()

        return list(filtered_projects.values(
            'project_category__name'
        ).annotate(
            count=Count('id')
        ).order_by('-count'))

    def get_projects_by_target_group(self):
        """Get projects grouped by target group."""
        filtered_projects = self._get_filtered_projects()

        return list(filtered_projects.values(
            'target_group__name'
        ).annotate(
            count=Count('id')
        ).order_by('-count'))

    def get_projects_by_leader(self):
        """Get projects grouped by project leader."""
        filtered_projects = self._get_filtered_projects()

        return list(filtered_projects.values(
            'project_leader__name'
        ).annotate(
            count=Count('id')
        ).order_by('-count')[:10])  # Top 10 leaders

    def get_projects_trend(self):
        """Get projects trend over time."""
        filtered_projects = self._get_filtered_projects()

        # Group by month
        return list(filtered_projects.extra(
            select={'month': "DATE_TRUNC('month', date)"}
        ).values('month').annotate(
            count=Count('id')
        ).order_by('month'))

    def get_participants_stats(self):
        """Get participants statistics by age groups."""
        filtered_projects = self._get_filtered_projects()

        age_stats = filtered_projects.aggregate(
            tn_0_bis_6=Sum('tn_0_bis_6'),
            tn_7_bis_10=Sum('tn_7_bis_10'),
            tn_11_bis_14=Sum('tn_11_bis_14'),
            tn_15_bis_18=Sum('tn_15_bis_18'),
            tn_19_bis_34=Sum('tn_19_bis_34'),
            tn_35_bis_50=Sum('tn_35_bis_50'),
            tn_51_bis_65=Sum('tn_51_bis_65'),
            tn_ueber_65=Sum('tn_ueber_65'),
            tn_age_not_given=Sum('tn_age_not_given'),
        )

        gender_stats = filtered_projects.aggregate(
            tn_female=Sum('tn_female'),
            tn_male=Sum('tn_male'),
            tn_diverse=Sum('tn_diverse'),
            tn_gender_not_given=Sum('tn_gender_not_given'),
        )

        return {
            'age_groups': age_stats,
            'gender_groups': gender_stats,
        }

    def get_demographic_stats(self):
        """Get demographic statistics."""
        filtered_projects = self._get_filtered_projects()

        # Age group distribution
        age_distribution = {
            'under_18': filtered_projects.aggregate(
                total=Sum('tn_0_bis_6') + Sum('tn_7_bis_10') + Sum('tn_11_bis_14') + Sum('tn_15_bis_18')
            )['total'] or 0,
            '18_34': filtered_projects.aggregate(
                total=Sum('tn_19_bis_34')
            )['total'] or 0,
            '35_50': filtered_projects.aggregate(
                total=Sum('tn_35_bis_50')
            )['total'] or 0,
            'over_50': filtered_projects.aggregate(
                total=Sum('tn_51_bis_65') + Sum('tn_ueber_65')
            )['total'] or 0,
        }

        # Gender distribution
        gender_distribution = {
            'female': filtered_projects.aggregate(total=Sum('tn_female'))['total'] or 0,
            'male': filtered_projects.aggregate(total=Sum('tn_male'))['total'] or 0,
            'diverse': filtered_projects.aggregate(total=Sum('tn_diverse'))['total'] or 0,
            'not_given': filtered_projects.aggregate(total=Sum('tn_gender_not_given'))['total'] or 0,
        }

        return {
            'age_distribution': age_distribution,
            'gender_distribution': gender_distribution,
        }

    def get_project_characteristics(self):
        """Get project characteristics statistics."""
        filtered_projects = self._get_filtered_projects()

        total_projects = filtered_projects.count()

        if total_projects == 0:
            return {
                'external_venue_rate': 0,
                'jugendmedienschutz_rate': 0,
                'democracy_rate': 0,
            }

        external_venue_rate = (filtered_projects.filter(external_venue=True).count() / total_projects) * 100
        jugendmedienschutz_rate = (filtered_projects.filter(jugendmedienschutz=True).count() / total_projects) * 100
        democracy_rate = (filtered_projects.filter(democracy_project=True).count() / total_projects) * 100

        return {
            'external_venue_rate': round(external_venue_rate, 1),
            'jugendmedienschutz_rate': round(jugendmedienschutz_rate, 1),
            'democracy_rate': round(democracy_rate, 1),
        }

    def _get_filtered_projects(self):
        """Get projects filtered by request parameters."""
        projects = Project.objects.all()

        # Date range filter
        days = self.request.GET.get('days', '30')
        if days != 'all':
            try:
                days_int = int(days)
                start_date = timezone.now().date() - timedelta(days=days_int)
                projects = projects.filter(date__gte=start_date)
            except (ValueError, TypeError):
                pass

        # Custom date range
        start_date = self.request.GET.get('start_date')
        end_date = self.request.GET.get('end_date')
        if start_date and end_date:
            try:
                start_date_obj = datetime.strptime(start_date, '%Y-%m-%d').date()
                end_date_obj = datetime.strptime(end_date, '%Y-%m-%d').date()
                projects = projects.filter(date__range=[start_date_obj, end_date_obj])
            except ValueError:
                pass

        # Category filter
        category = self.request.GET.get('category')
        if category:
            projects = projects.filter(project_category_id=category)

        # Target group filter
        target_group = self.request.GET.get('target_group')
        if target_group:
            projects = projects.filter(target_group_id=target_group)

        # Project leader filter
        project_leader = self.request.GET.get('project_leader')
        if project_leader:
            projects = projects.filter(project_leader_id=project_leader)

        # External venue filter
        external_venue = self.request.GET.get('external_venue')
        if external_venue == 'true':
            projects = projects.filter(external_venue=True)
        elif external_venue == 'false':
            projects = projects.filter(external_venue=False)

        # Jugendmedienschutz filter
        jugendmedienschutz = self.request.GET.get('jugendmedienschutz')
        if jugendmedienschutz == 'true':
            projects = projects.filter(jugendmedienschutz=True)
        elif jugendmedienschutz == 'false':
            projects = projects.filter(jugendmedienschutz=False)

        # Democracy project filter
        democracy_project = self.request.GET.get('democracy_project')
        if democracy_project == 'true':
            projects = projects.filter(democracy_project=True)
        elif democracy_project == 'false':
            projects = projects.filter(democracy_project=False)

        return projects

    def get_detailed_projects(self, project_type=None):
        """Get detailed list of projects based on filters."""
        from projects.models import Project

        queryset = Project.objects.select_related(
            'project_category',
            'target_group',
            'project_leader'
        ).all()
        filtered_queryset = self._get_filtered_projects()

        # Apply additional filters
        if project_type == 'external':
            filtered_queryset = filtered_queryset.filter(external_venue=True)
        elif project_type == 'internal':
            filtered_queryset = filtered_queryset.filter(external_venue=False)
        elif project_type == 'youth_protection':
            filtered_queryset = filtered_queryset.filter(jugendmedienschutz=True)
        elif project_type == 'democracy':
            filtered_queryset = filtered_queryset.filter(democracy_project=True)

        # Get detailed project data
        projects_data = []
        for project in filtered_queryset[:100]:  # Limit to 100 for performance
            project_data = {
                'id': project.id,
                'title': project.title or "",
                'date': project.date.strftime('%Y-%m-%d') if project.date else "",
                'category': project.project_category.name if project.project_category else "",
                'target_group': project.target_group.name if project.target_group else "",
                'project_leader': project.project_leader.name if project.project_leader else "",
                'external_venue': project.external_venue,
                'jugendmedienschutz': project.jugendmedienschutz,
                'democracy_project': project.democracy_project,
                'total_participants': self._calculate_total_participants(project),
                'female_participants': project.tn_female or 0,
                'male_participants': project.tn_male or 0,
                'diverse_participants': project.tn_diverse or 0,
                'age_0_6': project.tn_0_bis_6 or 0,
                'age_7_10': project.tn_7_bis_10 or 0,
                'age_11_14': project.tn_11_bis_14 or 0,
                'age_15_18': project.tn_15_bis_18 or 0,
                'age_19_34': project.tn_19_bis_34 or 0,
                'age_35_50': project.tn_35_bis_50 or 0,
                'age_51_65': project.tn_51_bis_65 or 0,
                'age_over_65': project.tn_ueber_65 or 0,
            }
            projects_data.append(project_data)

        return {
            'projects': projects_data,
            'total_count': filtered_queryset.count(),
            'displayed_count': len(projects_data)
        }

    def get_detailed_projects_by_participants(self):
        """Get detailed list of projects with participants > 0."""
        from projects.models import Project

        filtered_queryset = self._get_filtered_projects()

        # Filter projects with participants > 0
        projects_with_participants = []
        for project in filtered_queryset:
            total_participants = self._calculate_total_participants(project)
            if total_participants > 0:
                project_data = {
                    'id': project.id,
                    'title': project.title or "",
                    'date': project.date.strftime('%Y-%m-%d') if project.date else "",
                    'category': project.project_category.name if project.project_category else "",
                    'target_group': project.target_group.name if project.target_group else "",
                    'project_leader': project.project_leader.name if project.project_leader else "",
                    'external_venue': project.external_venue,
                    'jugendmedienschutz': project.jugendmedienschutz,
                    'democracy_project': project.democracy_project,
                    'total_participants': total_participants,
                    'female_participants': project.tn_female or 0,
                    'male_participants': project.tn_male or 0,
                    'diverse_participants': project.tn_diverse or 0,
                    'age_0_6': project.tn_0_bis_6 or 0,
                    'age_7_10': project.tn_7_bis_10 or 0,
                    'age_11_14': project.tn_11_bis_14 or 0,
                    'age_15_18': project.tn_15_bis_18 or 0,
                    'age_19_34': project.tn_19_bis_34 or 0,
                    'age_35_50': project.tn_35_bis_50 or 0,
                    'age_51_65': project.tn_51_bis_65 or 0,
                    'age_over_65': project.tn_ueber_65 or 0,
                }
                projects_with_participants.append(project_data)

        return {
            'projects': projects_with_participants,
            'total_count': len(projects_with_participants),
            'displayed_count': len(projects_with_participants)
        }

    def get_detailed_projects_by_average_participants(self):
        """Get detailed list of projects ordered by participant count (average)."""
        from projects.models import Project

        filtered_queryset = self._get_filtered_projects()

        # Get projects with participant data and sort by total participants
        projects_with_participants = []
        for project in filtered_queryset:
            total_participants = self._calculate_total_participants(project)
            project_data = {
                'id': project.id,
                'title': project.title or "",
                'date': project.date.strftime('%Y-%m-%d') if project.date else "",
                'category': project.project_category.name if project.project_category else "",
                'target_group': project.target_group.name if project.target_group else "",
                'project_leader': project.project_leader.name if project.project_leader else "",
                'external_venue': project.external_venue,
                'jugendmedienschutz': project.jugendmedienschutz,
                'democracy_project': project.democracy_project,
                'total_participants': total_participants,
                'female_participants': project.tn_female or 0,
                'male_participants': project.tn_male or 0,
                'diverse_participants': project.tn_diverse or 0,
                'age_0_6': project.tn_0_bis_6 or 0,
                'age_7_10': project.tn_7_bis_10 or 0,
                'age_11_14': project.tn_11_bis_14 or 0,
                'age_15_18': project.tn_15_bis_18 or 0,
                'age_19_34': project.tn_19_bis_34 or 0,
                'age_35_50': project.tn_35_bis_50 or 0,
                'age_51_65': project.tn_51_bis_65 or 0,
                'age_over_65': project.tn_ueber_65 or 0,
            }
            projects_with_participants.append(project_data)

        # Sort by total participants (descending)
        projects_with_participants.sort(key=lambda x: x['total_participants'], reverse=True)

        return {
            'projects': projects_with_participants,
            'total_count': len(projects_with_participants),
            'displayed_count': len(projects_with_participants)
        }

    def _calculate_total_participants(self, project):
        """Calculate total participants for a project."""
        return (
            (project.tn_female or 0) +
            (project.tn_male or 0) +
            (project.tn_diverse or 0) +
            (project.tn_gender_not_given or 0)
        )

    def get_projects_by_venue(self):
        """Get projects grouped by venue type."""
        filtered_projects = self._get_filtered_projects()

        external_count = filtered_projects.filter(external_venue=True).count()
        internal_count = filtered_projects.filter(external_venue=False).count()

        return [
            {'venue_type': 'External', 'count': external_count},
            {'venue_type': 'Internal', 'count': internal_count}
        ]

    def get_participant_stats(self):
        """Get participant statistics."""
        return self.get_participants_stats()

    def get_gender_distribution(self):
        """Get gender distribution statistics."""
        gender_stats = self.get_participants_stats()['gender_groups']
        return {
            'female': gender_stats.get('tn_female', 0),
            'male': gender_stats.get('tn_male', 0),
            'diverse': gender_stats.get('tn_diverse', 0),
            'not_given': gender_stats.get('tn_gender_not_given', 0)
        }

    def get_age_distribution(self):
        """Get age distribution statistics."""
        age_stats = self.get_participants_stats()['age_groups']
        return {
            'age_0_6': age_stats.get('tn_0_bis_6', 0),
            'age_7_10': age_stats.get('tn_7_bis_10', 0),
            'age_11_14': age_stats.get('tn_11_bis_14', 0),
            'age_15_18': age_stats.get('tn_15_bis_18', 0),
            'age_19_34': age_stats.get('tn_19_bis_34', 0),
            'age_35_50': age_stats.get('tn_35_bis_50', 0),
            'age_51_65': age_stats.get('tn_51_bis_65', 0),
            'age_over_65': age_stats.get('tn_ueber_65', 0)
        }

    def get_youth_protection_stats(self):
        """Get youth protection statistics."""
        filtered_projects = self._get_filtered_projects()
        total_projects = filtered_projects.count()
        youth_protection_projects = filtered_projects.filter(jugendmedienschutz=True).count()

        return {
            'total_projects': total_projects,
            'youth_protection_projects': youth_protection_projects,
            'percentage': round((youth_protection_projects / total_projects * 100) if total_projects > 0 else 0, 1)
        }

    def get_democracy_project_stats(self):
        """Get democracy project statistics."""
        filtered_projects = self._get_filtered_projects()
        total_projects = filtered_projects.count()
        democracy_projects = filtered_projects.filter(democracy_project=True).count()

        return {
            'total_projects': total_projects,
            'democracy_projects': democracy_projects,
            'percentage': round((democracy_projects / total_projects * 100) if total_projects > 0 else 0, 1)
        }

    def get_detailed_data(self):
        """Get detailed data for the projects widget."""
        return {
            'projects': self.get_detailed_projects(),
            'basic_stats': self.get_basic_stats(),
            'projects_by_category': self.get_projects_by_category(),
            'projects_by_target_group': self.get_projects_by_target_group(),
            'projects_by_leader': self.get_projects_by_leader(),
            'projects_by_venue': self.get_projects_by_venue(),
            'projects_trend': self.get_projects_trend(),
            'participant_stats': self.get_participant_stats(),
            'gender_distribution': self.get_gender_distribution(),
            'age_distribution': self.get_age_distribution(),
            'youth_protection_stats': self.get_youth_protection_stats(),
            'democracy_project_stats': self.get_democracy_project_stats(),
        }
