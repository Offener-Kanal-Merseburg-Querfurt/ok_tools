from contributions.models import Contribution
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.utils import IntegrityError
from licenses.models import Category
from licenses.models import LicenseRequest
from openpyxl import load_workbook
from openpyxl.cell import cell as cell_meta
from openpyxl.cell.cell import Cell
from openpyxl.worksheet.worksheet import Worksheet
from projects.models import MediaEducationSupervisor
from projects.models import Project
from projects.models import ProjectCategory
from projects.models import ProjectLeader
from projects.models import TargetGroup
from registration.models import Profile
from zoneinfo import ZoneInfo
import datetime
import logging


EMPTY_VALUE = 'unbekannt'

User = get_user_model()
logger = logging.getLogger('console')


@transaction.atomic
def run():
    """Run the import."""
    wb = load_workbook(filename=settings.LEGACY_DATA)

    category_ids: IdNumberMap = import_categories(wb['categories'])

    user_ids = import_users(wb['users'])

    import_primary_contributions(wb['contributions'], user_ids, category_ids)

    import_projects(wb['projects'])

    import_repetitions(wb['repetitions'], user_ids, category_ids)


@transaction.atomic
class IdNumberMap:
    """
    Mapping between old numbers and new Ids.

    One number has only one Id.
    One Id can have multiple numbers.
    """

    # map one number to one id
    number_to_id: dict[int, int]
    # map on id to multiple numbers
    id_to_numbers: dict[int, set[int]]

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


@transaction.atomic
def import_users(ws: Worksheet) -> IdNumberMap:
    """
    Import users from xlsx.

    When two profiles where found for one user the newer one gets chosen.
    When there is no creation datetime given, the profile gets handled as the
    newest.
    Returns a IdNumberMap mapping the old user numbers to the new ids.
    """
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
    MEMBER = 19

    def _get_phone_number(cell: Cell) -> int:
        """Clean the phone number from non digit characters."""
        if number := cell.value:
            return "".join([n for n in number if n.isdigit()])
        else:
            return None

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
    assert header[MEMBER].value == 'Vereinsmitglied'

    for row in rows:
        switched = False

        if row[E_MAIL].value:
            user, user_created = User.objects.get_or_create(
                email=row[E_MAIL].value)

            if not user_created:
                # user with email already exists
                logger.info('Already found a user. I will take the newer one.')
                created_profile = user.profile

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
                            ZoneInfo(settings.TIME_ZONE))
                        ),
            member=_get_bool(row[MEMBER]) or False,
            verified=True,
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
            msg = f'Found two similar profiles for {list[0]}'
            logger.warn(msg)
            raise NotImplementedError(msg)

    return ids


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
def import_primary_contributions(
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

    def _get_further_persons(camera: Cell, cut: Cell) -> str:
        """Create a string for the 'further_persons' field."""
        further_persons = []

        if camera.value:
            further_persons.append(f'Kamera: {camera.value}')
        if cut.value:
            further_persons.append(f'Schnitt: {cut.value}')

        return '\n'.join(further_persons)

    def _get_duration(row) -> datetime.timedelta:
        """Return the duration and concern screen boards."""
        if _is_screen_board(row):
            return datetime.timedelta(seconds=settings.SCREEN_BOARD_DURATION)

        assert row[DURATION].data_type == cell_meta.TYPE_NUMERIC

        return datetime.timedelta(minutes=row[DURATION].value)

    def _is_screen_board(row) -> bool:
        """Determine wether the contribution is a screen board."""
        return row[TITLE] == SCREEN_BOARD_STR

    no_prof_cnt = 0
    no_cat_cnt = 0
    for row in rows:

        profile = _get_profile(row[USER_NR], user_ids)
        if not profile:
            no_prof_cnt += 1
            continue

        category, error = _get_category(row[CATEGORY_NR], category_ids)
        if error:
            no_cat_cnt += 1

        try:
            LicenseRequest.objects.get(number=row[NR].value)
            logger.warn('Number already taken.')
            continue
        except LicenseRequest.DoesNotExist:
            pass

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

    if no_prof_cnt:
        logger.critical(f'Could not find profile for {no_prof_cnt} primary'
                        ' contributions')
    if no_cat_cnt:
        logger.critical(f'Could not find category for {no_cat_cnt} primary'
                        ' contributions.')


@transaction.atomic
def import_projects(ws: Worksheet):
    """Import projects from xlsx."""
    DAY = 1
    DURATION = 2
    TITLE = 3
    TOPIC = 4
    LEADER = 5
    E_SUPERVISIOR = 6
    EXTERNAL_V = 7
    YOUTH_PROTECTION = 8
    U6 = 10
    U11 = 11
    U15 = 12
    U19 = 13
    U35 = 14
    U51 = 15
    U66 = 16
    O65 = 17
    NO_AGE = 18
    M = 19
    W = 20
    WITHOUT_GENDER = 21
    TARGET_GROUP = 22
    CATEGORY = 23

    def _get_me_supervisors(cell: Cell) -> list[MediaEducationSupervisor]:
        if cell.value is None:
            return []

        if cell.data_type != cell_meta.TYPE_STRING:
            logger.error(
                f'Unsupported cell type {cell.data_type} for supervisors')
            return []

        name_list = cell.value.split(',')
        s_list = []

        for n in name_list:
            s, s_created = MediaEducationSupervisor.objects.get_or_create(
                name=n
            )
            s_list.append(s)

        return s_list

    rows = ws.rows
    header = next(rows)

    assert header[DAY].value == 'Veranstaltungstag'
    assert header[DURATION].value == 'Veranstaltungsdauer'
    assert header[TITLE].value == 'Veranstaltung'
    assert header[TOPIC].value == 'Thema'
    assert header[LEADER].value == 'Veranstaltungsleiter'
    assert header[E_SUPERVISIOR].value == 'medienpädagogische Betreuer'
    assert header[EXTERNAL_V].value == 'externer V_ort'
    assert header[YOUTH_PROTECTION].value == 'Jugendmedienschutz'
    assert header[U6].value == 'unter 6'
    assert header[U11].value == '7 bis 10'
    assert header[U15].value == '11 bis 14'
    assert header[U19].value == '15 bis 18'
    assert header[U35].value == '19 bis 34'
    assert header[U51].value == '35 bis 50'
    assert header[U66].value == '51 bis 65'
    assert header[O65].value == 'älter 65'
    assert header[NO_AGE].value == 'ohne alter'
    assert header[M].value == 'männlich'
    assert header[W].value == 'weiblich'
    assert header[WITHOUT_GENDER].value == 'kein G'
    assert header[TARGET_GROUP].value == 'Zielgruppe'
    assert header[CATEGORY].value == 'Projektausrichtung'

    for row in rows:
        leader, leader_created = ProjectLeader.objects.get_or_create(
            name=row[LEADER].value or EMPTY_VALUE
        )

        me_supervisors = _get_me_supervisors(row[E_SUPERVISIOR])

        category, category_created = ProjectCategory.objects.get_or_create(
            name=row[CATEGORY].value or EMPTY_VALUE
        )

        target_gr, target_gr_created = TargetGroup.objects.get_or_create(
            name=row[TARGET_GROUP].value or EMPTY_VALUE
        )

        duration = _get_duration(row[DURATION])
        if not duration:
            logger.warn(f'Now duration for project "{row[TITLE].value}"')

        begin_date = _get_datetime(row[DAY])
        if not begin_date:
            logger.warn(f'No begin_date for project "{row[TITLE].value}')

        try:
            project, project_created = Project.objects.get_or_create(
                title=row[TITLE].value,
                topic=row[TOPIC].value,
                duration=duration,
                begin_date=begin_date,
                external_venue=_get_bool(row[EXTERNAL_V]),
                jugendmedienschutz=_get_bool(row[YOUTH_PROTECTION]),
                target_group=target_gr,
                project_category=category,
                project_leader=leader,
                tn_0_bis_6=_get_number(row[U6]),
                tn_7_bis_10=_get_number(row[U11]),
                tn_11_bis_14=_get_number(row[U15]),
                tn_15_bis_18=_get_number(row[U19]),
                tn_19_bis_34=_get_number(row[U35]),
                tn_35_bis_50=_get_number(row[U51]),
                tn_51_bis_65=_get_number(row[U66]),
                tn_ueber_65=_get_number(row[O65]),
                tn_age_not_given=_get_number(row[NO_AGE]),
                tn_female=_get_number(row[W]),
                tn_male=_get_number(row[M]),
                tn_gender_not_given=_get_number(row[WITHOUT_GENDER]),
            )
        except IntegrityError:
            raise

        if project_created:
            logger.warn(f'Project "{row[TITLE].value}" already exists.')
        else:
            for s in me_supervisors:
                project.media_education_supervisors.add(s.id)

            project.save()


def import_repetitions(
        ws: Worksheet, user_ids: IdNumberMap, category_ids: dict):
    """
    Import repetitions from xlsx.

    Assumes that every repetition has an existing primary contribution and
    an existing user.
    """
    NR = 0
    TITLE = 1
    SUBTITLE = 2
    OLD_DATE = 3
    OLD_TIME = 4
    NEW_DATE = 5
    NEW_TIME = 6
    USER_NR = 7
    DURATION = 8
    DESCRIPTION = 11
    CATEGORY = 12
    LIVE = 14

    rows = ws.rows
    header = next(rows)

    assert header[NR].value == 'lfd_nr'
    assert header[TITLE].value == 'titel'
    assert header[SUBTITLE].value == 'untertitel'
    assert header[OLD_DATE].value == 'altesDatum'
    assert header[OLD_TIME].value == 'alteSendezeit'
    assert header[NEW_DATE].value == 'Sendedatum'
    assert header[NEW_TIME].value == 'Sendezeit'
    assert header[USER_NR].value == 'Nutzer_Nr'
    assert header[DURATION].value == 'Länge'
    assert header[DESCRIPTION].value == 'Beschreibung'
    assert header[CATEGORY].value == 'Rubrik'
    assert header[LIVE].value == 'live'

    no_prim_found = 0
    no_clear_prim = 0
    for row in rows:

        old_broadcast_date = _get_broadcast_date(row[OLD_DATE], row[OLD_TIME])
        if old_broadcast_date is None:
            logger.error(f'No old broadcastdate found for {row[NR].value}.')
            continue

        # TODO nach altem Datum und alter Sendezeit
        contributions = Contribution.objects.filter(
            broadcast_date=old_broadcast_date,
        )

        broadcast_date = _get_broadcast_date(row[NEW_DATE], row[NEW_TIME])

        if not contributions:
            if broadcast_date.year == 2022:
                logger.critical('No primary contribution for repetition'
                                f' {row[NR].value} from 2022.')
            else:
                logger.error('No primary contribution found.')

            logger.warn(f'Creating a new License for {row[NR].value}.')

            profile = _get_profile(row[USER_NR], user_ids)
            if not profile:
                continue

            category, c_created = Category.objects.get_or_create(
                name=row[CATEGORY].value or EMPTY_VALUE
            )

            license, lr_created = LicenseRequest.objects.get_or_create(
                number=row[NR].value,
                profile=profile,
                title=row[TITLE].value,
                subtitle=row[SUBTITLE].value,
                description=row[DESCRIPTION].value,
                duration=_get_duration(row[DURATION]),
                category=category,
                confirmed=True,
            )

            if not lr_created:
                logger.warn(f'License {license} already exists.')

            no_prim_found += 1

            continue
        elif len(contributions) != 1:
            if broadcast_date.year == 2022:
                logger.critical('More than one primary contribution for'
                                f' repetition {row[NR].value} from 2022.')
            else:
                logger.error('More then one primary contribution'
                             f' ({row[NR].value}). Just taking the first one.')
            no_clear_prim += 1
            license = contributions[0].license
            continue
        else:
            license = contributions[0].license

        contr, contr_created = Contribution.objects.get_or_create(
            license=license,
            broadcast_date=_get_broadcast_date(row[NEW_DATE], row[NEW_TIME]),
            live=_get_bool(row[LIVE]),
        )

        if contr_created:
            logger.warn(f'Repetition {contr} already exists.')

    if no_prim_found:
        logger.critical('Could not find primary contribution'
                        f' for {no_prim_found} repetitions.')

    if no_clear_prim:
        logger.critical('Found more then one primary contribution for'
                        f' {no_clear_prim} repetitions.')


def _get_broadcast_date(
        date_c: Cell, time_c: Cell) -> datetime.datetime | None:
    """Return the broadcast_date or None if no broadcast date where found."""
    date = _get_datetime(date_c)

    time = _get_time(time_c)

    if not date:
        logger.error('No date for broadcast_date found.')
        return None

    if not time:
        logger.error('No time for broadcast_date found.')
        return date

    date = date.replace(
        hour=time.hour,
        minute=time.minute,
        second=time.second,
        microsecond=time.microsecond,
    )

    return date


def _get_category(cell: Cell, category_ids: dict) -> tuple[Category, bool]:
    """
    Determine the category from the given category number.

    Return the category and a boolean weather the category was found.
    """
    category_nr = _get_number(cell)
    DEFAULT_CATEGORY_NAME = f'unbekannt_{category_nr}'

    if not category_nr:
        logger.warn(f'Invalid category number {cell.value}')
        return (Category.objects.get_or_create(name=DEFAULT_CATEGORY_NAME)[0],
                True)

    id = category_ids.get(cell.value)
    if not id:
        logger.warn(f'Invalid category number {cell.value}.')
        return (Category.objects.get_or_create(name=DEFAULT_CATEGORY_NAME)[0],
                True)

    try:
        category = Category.objects.get(id=id)
    except Category.DoesNotExist:
        logger.error(f'Invalid id {id}.')
        return (Category.objects.get_or_create(name=DEFAULT_CATEGORY_NAME)[0],
                True)

    return category, False


def _get_time(time_c: Cell) -> datetime.time:
    """Return a datetime.time element and None if an error occurs."""
    if not time_c.value:
        logger.warn('No time found.')
        return None

    if not time_c.is_date:
        logger.error(f'Unsupported time format {time_c.value}')
        return None

    return time_c.value


def _get_duration(cell: Cell) -> datetime.timedelta:
    """Return a datetime.timedelta or None if not convertible."""
    if cell.data_type == cell_meta.TYPE_NUMERIC:
        return datetime.timedelta(minutes=cell.value)
    else:
        logger.error(f'Could not convert "{cell.data_type}" to timedelta.')
        return None


def _get_datetime(cell: Cell) -> datetime.datetime:
    """Return a Datetime or None if the cell is not a date."""
    if cell.is_date:
        aware_datetime = cell.value.replace(
            tzinfo=ZoneInfo(settings.TIME_ZONE))
        return aware_datetime
    else:
        if cell.value:
            logger.warn(f'Could not format date {cell.value}')

        return None


def _get_bool(cell: Cell) -> bool:
    """
    Try to convert the cell value to a boolean.

    If no conversion was possible None is returned.
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
                return None
        case _:
            logger.warn(f'Could not convert "{cell.value}" with type'
                        f'{cell.data_type} to bool ')
            return None


def _get_number(cell: Cell) -> int:
    """
    Convert the cell value to int if possible.

    Otherwise return 0.
    """
    if not cell.value:
        return 0

    match cell.data_type:
        case cell_meta.TYPE_NUMERIC:
            return cell.value
        case cell_meta.TYPE_STRING:
            if (v := cell.value).isdigit():
                return int(v)
            else:
                logger.error(f'Could not convert "{v}" to int.')
                return 0
        case _:
            logger.error(
                f'Could not convert type {type(cell.value)} to int.')
            return 0


def _get_profile(user_nr: Cell, user_ids: IdNumberMap) -> User | None:
    """Return the corresponding profile or None if an error occurs."""
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
