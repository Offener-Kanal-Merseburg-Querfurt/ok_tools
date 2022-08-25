from licenses.models import Category
from openpyxl import load_workbook
import logging


def run():
    """Run the import."""
    # TODO set filename by settings.by
    wb = load_workbook(filename="../legacy_data/data.xlsx")

    category_wb = wb['categories']
    category_rows = category_wb.rows

    titles = next(category_rows)
    assert titles[0].value == 'RubrikNr'
    assert titles[1].value == 'Rubrik'
    for row in category_rows:
        if not Category.objects.filter(name=row[1].value):
            Category.objects.create(name=row[1].value)
        else:
            logging.info(f'Category "{row[1]}" already exists!')
