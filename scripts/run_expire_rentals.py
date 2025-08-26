#!/usr/bin/env python
from django.core.management import execute_from_command_line
import django
import os
import sys


if __name__ == "__main__":
    # Настройка Django
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ok_tools.settings")
    django.setup()

    # Запуск команды
    sys.argv = ['manage.py', 'expire_room_rentals']
    execute_from_command_line(sys.argv)
