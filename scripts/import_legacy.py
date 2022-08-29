from licenses.models import Category
from openpyxl import load_workbook
from openpyxl.worksheet.worksheet import Worksheet
import logging


logger = logging.getLogger('console')


def run():
    """Run the import."""
    # TODO set filename by settings.by
    wb = load_workbook(filename="../legacy_data/data.xlsx")

    import_categories(wb['categories'])


def import_categories(ws: Worksheet):
    """
    Import categories from xlsx.

    The data sheet has a first column with named 'RubrikNr', which gets ignored
    and a second column named 'Rubrik' from which is use for the categories.
    """
    rows = ws.rows

    titles = next(rows)
    assert titles[0].value == 'RubrikNr'
    assert titles[1].value == 'Rubrik'
    for row in rows:
        if not Category.objects.filter(name=row[1].value):
            Category.objects.create(name=row[1].value)
        else:
            logger.info(f'Category "{row[1].value}" already exists!')
