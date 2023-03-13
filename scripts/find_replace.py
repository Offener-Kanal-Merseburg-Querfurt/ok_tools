from licenses.models import License


def run():
    """
    Implement a find and replace tool for Licenses.

    Considers the fields 'title', 'subtitle' and 'description'.
    """
    FIND = '_x000d_'
    REPLACE = ''

    queryset = License.objects.all()
    for lc in queryset:
        description = lc.description and FIND in lc.description
        title = lc.title and FIND in lc.title
        subtitle = lc.subtitle and FIND in lc.subtitle

        if not (description or title or subtitle):
            continue

        confirmed = lc.confirmed

        if confirmed:
            # If the license is already confirmed we need to unconfirm them
            # before we can make our changes.
            lc.confirmed = False
            lc.save(update_fields=['confirmed'])

        if description:
            lc.description = lc.description.replace(FIND, REPLACE)
        if title:
            lc.title = lc.title.replace(FIND, REPLACE)
        if subtitle:
            lc.subtitle = lc.subtitle.replace(FIND, REPLACE)

        lc.confirmed = confirmed
        lc.save()
