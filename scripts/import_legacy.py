from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.db import transaction
from licenses.models import Category
from openpyxl import load_workbook
from openpyxl.cell import cell as cell_meta
from openpyxl.cell.cell import Cell
from openpyxl.worksheet.worksheet import Worksheet
from registration.models import Profile
import datetime
import logging
import pytz


User = get_user_model()
logger = logging.getLogger('console')


def run():
    """Run the import."""
    # TODO set filename by settings.by
    wb = load_workbook(filename="../legacy_data/data.xlsx")

    import_categories(wb['categories'])

    import_users(wb['users'])


@transaction.atomic
def import_users(ws: Worksheet):
    """Import users from xlsx."""
    rows = ws.rows

    header = next(rows)

    NR = 0
    W = 2
    M = 3
    FIRST_NAME = 5
    LAST_NAME = 6
    STREET = 7
    H_NUMBER = 8
    ZIPCODE = 9
    CITY = 10
    BIRTHDAY = 12
    PHONE = 13
    MOBILE = 14
    E_MAIL = 15
    CREATED_AT = 16

    assert header[W].value == 'weiblich'
    assert header[M].value == 'männlich'
    assert header[FIRST_NAME].value == 'Vorname'
    assert header[LAST_NAME].value == 'Name'
    assert header[STREET].value == 'Straße'
    assert header[H_NUMBER].value == 'Haus_Nr'
    assert header[ZIPCODE].value == 'PLZ'
    assert header[CITY].value == 'Ort'
    assert header[BIRTHDAY].value == 'Geb_tag'
    assert header[PHONE].value == 'Tel_priv'
    assert header[MOBILE].value == 'Tel_diest'
    assert header[E_MAIL].value == 'e_mail'
    assert header[CREATED_AT].value == 'Nutzer seit'

    for row in rows:

        # determine gender
        m = _get_bool(row[M])
        w = _get_bool(row[W])
        if not (m != w):
            gender = "none"
            logger.warn(
                f'Could not determine gender from user {row[NR].value}')
        if w:
            gender = "w"
        else:
            gender = "M"

        if row[E_MAIL].value:
            user, user_created = User.objects.get_or_create(
                email=row[E_MAIL].value)

            try:
                user.profile
                logger.error(f'Could not add profile {row[NR].value}, because'
                             f' user with {row[E_MAIL].value} already exists.')
            except User.profile.RelatedObjectDoesNotExist:
                pass

            if not user_created:
                logger.info(f'Already found a user for {row[NR].value}')

        else:
            user = None

        try:
            obj, created = Profile.objects.get_or_create(
                okuser=user,
                first_name=row[FIRST_NAME].value,
                last_name=row[LAST_NAME].value,
                gender=gender,
                phone_number=_get_phone_number(row[PHONE]),
                mobile_number=_get_phone_number(row[MOBILE]),
                birthday=_get_datetime(row[BIRTHDAY]),
                street=row[STREET].value,
                house_number=row[H_NUMBER].value,
                zipcode=row[ZIPCODE].value,
                city=row[CITY].value,
                created_at=(_get_datetime(row[CREATED_AT])
                            or datetime.datetime.now(
                                pytz.timezone(settings.TIME_ZONE))
                            ),
            )

        except IntegrityError as e:
            if (str(e) ==
                    'UNIQUE constraint failed:'
                    ' registration_profile.okuser_id'):
                logger.warn(
                    f'User Nr. {row[NR].value} already has a profile with'
                    f' different properties {row[E_MAIL].value}')
            else:
                raise

        if not created:
            logger.warn(f'Profile for {obj} from user number {row[NR].value}'
                        ' already exists.')


def _get_phone_number(cell: Cell) -> int:
    if number := cell.value:
        return "".join([n for n in number if n.isdigit()])
    else:
        return None


def _get_datetime(cell: Cell) -> datetime.datetime:
    if cell.is_date:
        aware_datetime = cell.value.replace(
            tzinfo=pytz.timezone(settings.TIME_ZONE))
        return aware_datetime
    else:
        if cell.value:
            logger.warn(f'Could not format date {cell.value}')

        return None


def _get_bool(cell: Cell) -> bool:
    """
    Try to convert the cell value to a boolen.

    The default value is False.
    """
    if not cell.value:
        return False

    match cell.data_type:
        case cell_meta.TYPE_BOOL:
            return cell.value
        case cell_meta.TYPE_FORMULA:
            if cell.value == '=TRUE()':
                return True
            elif cell.value == '=FALSE()':
                return False
            else:
                logger.warn(f'Could not covert formula {cell.value} to bool.')
                return False
        case _:
            logger.warn(f'Could not convert {cell.value} with type'
                        f'{cell.data_type} to bool ')
            return False


@transaction.atomic
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
        obj, created = Category.objects.get_or_create(name=row[1].value)
        if not created:
            logger.info(f'Category "{row[1].value}" already exists!')
