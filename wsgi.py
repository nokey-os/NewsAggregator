"""
WSGI-конфигурация для PythonAnywhere.
Разместите в: /var/www/nokey_pythonanywhere_com_wsgi.py
Настроить: Web → WSGI configuration file
"""

import sys
import os

# Путь к проекту — замените 'nokey' на ваш логин
project_home = '/home/nokey/NewsAggregator'

if project_home not in sys.path:
    sys.path.insert(0, project_home)

os.chdir(project_home)

# Импортируем Flask-приложение
from app import app as application

# Отключаем debug для production
application.debug = False
