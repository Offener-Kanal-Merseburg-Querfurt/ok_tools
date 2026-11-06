"""
Dump the legacy OK Stendal MySQL database ("okdb") into one JSON file.

The JSON file is what ``manage.py import_okdb_stendal`` reads, so the
ok_tools server does not need MySQL access.

The old DB only exists as raw MyISAM files (*.frm/*.MYD/*.MYI). To read them,
start a throw-away MariaDB on a COPY of the folder::

    mkdir -p /tmp/okdb_data/okdb && cp okdb/* /tmp/okdb_data/okdb/
    docker run -d --name okdb_old -p 33306:3306 \\
        -e MARIADB_ROOT_PASSWORD=root \\
        -v /tmp/okdb_data:/var/lib/mysql mariadb:10.6

Then (needs ``pip install pymysql``)::

    python deployment/scripts/okdb_dump.py --port 33306 --out okdb_stendal.json
"""
from datetime import date
from datetime import datetime
from datetime import timedelta
from decimal import Decimal
import argparse
import json


def _jsonable(value):
    if isinstance(value, timedelta):
        total = int(value.total_seconds())
        sign = '-' if total < 0 else ''
        total = abs(total)
        return f'{sign}{total // 3600:02d}:{total % 3600 // 60:02d}:{total % 60:02d}'
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, bytes):
        return value.decode('utf-8', errors='replace')
    return value


def main():
    """Read every non-empty table and write {table: [rows]} as JSON."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=3306)
    parser.add_argument('--user', default='root')
    parser.add_argument('--password', default='root')
    parser.add_argument('--database', default='okdb')
    parser.add_argument('--out', required=True)
    args = parser.parse_args()

    import pymysql  # dev-only dependency, imported lazily

    conn = pymysql.connect(
        host=args.host, port=args.port, user=args.user,
        password=args.password, database=args.database, charset='utf8mb4',
        cursorclass=pymysql.cursors.DictCursor,
    )
    tables = {}
    with conn.cursor() as cur:
        cur.execute('SHOW TABLES')
        names = [next(iter(row.values())) for row in cur.fetchall()]
        for name in names:
            # Zero dates (0000-00-00) are returned as strings by pymysql;
            # the importer treats them as missing.
            cur.execute(f'SELECT * FROM `{name}`')
            rows = cur.fetchall()
            if rows:
                tables[name] = [
                    {k: _jsonable(v) for k, v in row.items()} for row in rows
                ]
            print(f'{name}: {len(rows)}')
    conn.close()

    with open(args.out, 'w', encoding='utf-8') as fh:
        json.dump({'source': 'okdb-stendal', 'tables': tables}, fh,
                  ensure_ascii=False)
    print(f'written {args.out}')


if __name__ == '__main__':
    main()
