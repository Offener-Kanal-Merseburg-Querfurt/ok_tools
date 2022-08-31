from contributions.models import Contribution
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from licenses.models import Category
from licenses.models import LicenseRequest
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


@transaction.atomic
class IdNumberMap:
    """
    Mapping between old numbers and new Ids.

    One number has only one Id.
    One Id can have multiple numbers.
    """

    number_to_id: dict[int, int] = {}
    id_to_numbers: dict[int, set[int]] = {}

    def __init__(self) -> None:
        self.number_to_id = {}
        self.id_to_numbers = {}

    def get_id(self, number: int) -> int:
        """Get the id of a number."""
        return self.number_to_id.get(number)

    def get_numbers(self, id: int) -> set[int]:
        """Get the numbers of an id."""
        value = self.id_to_numbers.get(id) or set()
        return value

    def add(self, number: int, id: int) -> None:
        """Add a number id tuple."""
        self.number_to_id[number] = id
        numbers = self.get_numbers(id)
        numbers.add(number)
        self.id_to_numbers[id] = numbers

    def remove(self, number: int, id: int) -> None:
        """Remove a number id tuple."""
        del self.number_to_id[number]
        numbers = self.get_numbers(id)
        numbers.remove(number)

    def remove_by_id(self, id: int) -> set[int]:
        """
        Remove all numbers associated to the given id.

        Returns a set of deleted numbers.
        """
        numbers = self.get_numbers(id).copy()
        for n in numbers:
            self.remove(n, id)

        return numbers


def run():
    """Run the import."""
    # TODO set filename by settings.by
    wb = load_workbook(filename="../legacy_data/data.xlsx")

    category_ids: IdNumberMap = import_categories(wb['categories'])

    user_ids = import_users(wb['users'])

    import_primary_categories(wb['contributions'], user_ids, category_ids)


@transaction.atomic
def import_users(ws: Worksheet) -> IdNumberMap:
    """
    Import users from xlsx.

    When two profiles where found for one user the newer one gets chosen.
    When there is no creation datetime given the profile gets handled as the
    newest.
    Returns a bidict mapping the old user numbers to the new ids.
    """
    ids: IdNumberMap = IdNumberMap()
    rows = ws.rows
    header = next(rows)

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
        switched = False

        if row[E_MAIL].value:
            user, user_created = User.objects.get_or_create(
                email=row[E_MAIL].value)

            if not user_created:
                # user with email already exists
                logger.info('Already found a user. I will take the newer one.')
                created_profile = user.profile
                # TODO maybe catch if no profile

                # if datetime is none handle as the newest
                new_created = _get_datetime(row[CREATED_AT])
                if (not new_created or
                        new_created > created_profile.created_at):

                    # set switched to true to add the numbers to the new
                    # id later
                    switched = True
                    Profile.objects.get(id=created_profile.id).delete()
                    old_numbers = ids.remove_by_id(created_profile.id)

                    logger.info(_chosen_profile(
                        row=row, profile=created_profile, switched=switched))
                elif (new_created == created_profile.created_at):
                    # assume that this is the same user
                    ids.add(row[NR].value, created_profile.id)
                    continue
                else:
                    ids.add(row[NR].value, created_profile.id)
                    logger.info(_chosen_profile(
                        row=row, profile=created_profile, switched=switched))
                    continue

        else:
            user = None

        obj, created = Profile.objects.get_or_create(
            okuser=user,
            first_name=row[FIRST_NAME].value,
            last_name=row[LAST_NAME].value,
            gender=_get_gender(row),
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

        if not created:
            # user without email but same properties already exists
            logger.warn(f'Profile for {obj} from user number {row[NR].value}'
                        ' already exists.')

        ids.add(row[NR].value, obj.id)
        if switched:
            # if the profile was updated add the old profile numbers to
            # the new id
            for n in old_numbers:
                ids.add(n, obj.id)

        if len(list := Profile.objects.filter(
                first_name=row[FIRST_NAME], last_name=row[LAST_NAME])) > 1:
            logger.warn(f'Found two similar profiles for {list[0]}')
            raise NotImplementedError

    return ids


def _get_gender(row) -> str:
    """Return the gender of the profile."""
    m = _get_bool(row[M])
    w = _get_bool(row[W])
    if not (m != w):
        logger.warn(
            f'Could not determine gender from user {row[NR].value}')
        return "none"
    if w:
        return "w"
    else:
        return "m"


def _chosen_profile(row, profile: Profile, switched):
    """Show which profile where chosen."""
    return f"""
    (1) {'==chosen==' if switched else ''}

    created at:.....{row[CREATED_AT].value}
    email:..........{row[E_MAIL].value}
    first name:.....{row[FIRST_NAME].value}
    last name:......{row[LAST_NAME].value}
    street:.........{row[STREET].value}
    house number:...{row[H_NUMBER].value}
    zipcode:........{row[ZIPCODE].value}
    city:...........{row[CITY].value}
    birthday:.......{row[BIRTHDAY].value}
    phone:..........{row[PHONE].value}
    mobile:.........{row[MOBILE].value}

    ======================================
    (2) {'==chosen==' if not switched else ''}


    created at:.....{profile.created_at}
    email:..........{profile.okuser.email}
    first name:.....{profile.first_name}
    last name:......{profile.last_name}
    street:.........{profile.street}
    house number:...{profile.house_number}
    zipcode:........{profile.zipcode}
    city:...........{profile.city}
    birthday:.......{profile.birthday}
    phone:..........{profile.phone_number}
    mobile:.........{profile.mobile_number}

    """


def _get_phone_number(cell: Cell) -> int:
    """Clean the phon number from non digit characters."""
    if number := cell.value:
        return "".join([n for n in number if n.isdigit()])
    else:
        return None


def _get_datetime(cell: Cell) -> datetime.datetime:
    """Return a Datetime or None if the cell is not a date."""
    if cell.is_date:
        # TODO trotzdem offset berücksichtigen
        aware_datetime = cell.value.replace(
            # because djangos datetimefield stores with tz utc
            tzinfo=datetime.timezone.utc)
        return aware_datetime
    else:
        if cell.value:
            logger.warn(f'Could not format date {cell.value}')

        return None


def _get_bool(cell: Cell) -> bool:
    """
    Try to convert the cell value to a boolean.

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
def import_categories(ws: Worksheet) -> dict:
    """
    Import categories from xlsx.

    The data sheet has a first column with named 'RubrikNr', which gets ignored
    and a second column named 'Rubrik' from which is use for the categories.
    Returns a dictionary mapping the old 'RubrikNr' to the new ids.
    """
    ids = {}
    rows = ws.rows
    titles = next(rows)

    assert titles[0].value == 'RubrikNr'
    assert titles[1].value == 'Rubrik'
    for row in rows:
        obj, created = Category.objects.get_or_create(name=row[1].value)
        ids[row[0].value] = obj.id
        if not created:
            logger.info(f'Category "{row[1].value}" already exists!')

    return ids


@transaction.atomic
def import_primary_categories(
        ws: Worksheet, user_ids: IdNumberMap, category_ids: dict):
    """
    Import contributions from xlsx.

    Because the contributions are primary, for every imported contribution
    a license gets created.
    """
    NR = 0
    DATE = 3
    TITLE = 4
    SUBTITLE = 5
    USER_NR = 6
    DURATION = 7
    TIME = 8
    CATEGORY_NR = 9
    DESCRIPTION = 10
    F_USER = 11
    CAMERA = 12
    CUT = 13
    LIVE = 16

    SCREEN_BOARD_STR = 'Programmvorschau / Trailer / Bildschirmtafeln'

    rows = ws.rows
    header = next(rows)

    assert header[NR].value == 'Beitrag_Nr'
    assert header[DATE].value == 'Sendedatum'
    assert header[TITLE].value == 'Titel'
    assert header[SUBTITLE].value == 'Untertitel'
    assert header[USER_NR].value == 'Nutzer_Nr'
    assert header[DURATION].value == 'Länge'
    assert header[TIME].value == 'Anfang'
    assert header[CATEGORY_NR].value == 'RubrikNr'
    assert header[DESCRIPTION].value == 'Beschreibung'
    assert header[F_USER].value == 'Fremdnutzer'
    assert header[CAMERA].value == 'Kameraführung'
    assert header[CUT].value == 'Schnitt'
    assert header[LIVE].value == 'live'

    def _get_profile(user_nr: Cell) -> User:
        """Return the corresponding profile or None if an error occured."""
        assert user_nr.data_type == cell_meta.TYPE_NUMERIC

        id = user_ids.get_id(user_nr.value)
        if not id:
            logger.error(f'Invalid user number {user_nr.value}.')
            return

        try:
            profile = Profile.objects.get(id=id)
        except Profile.DoesNotExist:
            logger.error(f'Invalid id {id}.')
            return

        return profile

    def _get_further_persons(camera: Cell, cut: Cell):
        further_persons = []

        if camera.value:
            further_persons.append(f'Kamera: {camera.value}')
        if cut.value:
            further_persons.append(f'Schnitt: {cut.value}')

        return '\n'.join(further_persons)

    def _get_duration(row):
        if _is_screen_board(row):
            return datetime.timedelta(seconds=settings.SCREEN_BOARD_DURATION)

        assert row[DURATION].data_type == cell_meta.TYPE_NUMERIC

        return datetime.timedelta(minutes=row[DURATION].value)

    def _is_screen_board(row):
        return row[TITLE] == SCREEN_BOARD_STR

    def _get_category(category_nr: Cell):
        assert category_nr.data_type == cell_meta.TYPE_NUMERIC

        id = category_ids.get(category_nr.value)
        if not id:
            logger.error(f'Invalid category number {category_nr.value}.')
            return

        try:
            category = Category.objects.get(id=id)
        except Category.DoesNotExist:
            logger.error(f'Invalid id {id}.')
            return

        return category

    def _get_broadcast_date(date_c: Cell, time_c: Cell):
        date = _get_datetime(date_c)

        if not time_c.value:
            logger.warn('No time found.')
            return date

        if not time_c.is_date:
            logger.error(f'Unsupported start date format {time_c.value}')
            return date

        time: datetime.time = time_c.value
        date.replace(
            hour=time.hour,
            minute=time.minute,
            second=time.second,
            microsecond=time.microsecond,
        )

        return date

    for row in rows:

        profile = _get_profile(row[USER_NR])
        if not profile:
            continue

        category = _get_category(row[USER_NR])
        if not category:
            category = Category.objects.get_or_create(name='Sonstiges')[0]

        lr, lr_created = LicenseRequest.objects.get_or_create(
            number=row[NR].value,
            profile=profile,
            title=row[TITLE].value,
            subtitle=row[SUBTITLE].value,
            description=row[DESCRIPTION].value,
            further_persons=_get_further_persons(row[CAMERA], row[CUT]),
            duration=_get_duration(row),  # handle screen_boards
            category=category,
            confirmed=True,
            is_screen_board=_is_screen_board(row),
        )

        if not lr_created:
            logger.warn(f'License {lr} already exists.')

        contrib, contrib_created = Contribution.objects.get_or_create(
            license=lr,
            broadcast_date=_get_broadcast_date(row[DATE], row[TIME]),
            live=_get_bool(row[LIVE]),
        )

        if not lr_created and not contrib_created:
            logger.warn(f'Contribution {contrib} already exists.')
        elif lr_created and not contrib_created:
            logger.error(f'Only expected primary contributions. {contrib} is a'
                         'repetition.')
