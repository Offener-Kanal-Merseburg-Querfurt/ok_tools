#!/usr/bin/env python
import os
import sys
import django
from django.core.management import execute_from_command_line

if __name__ == "__main__":
    # Настройка Django
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ok_tools.settings")
    django.setup()
    
    # Запуск команды
    sys.argv = ['manage.py', 'expire_room_rentals']
    execute_from_command_line(sys.argv)
