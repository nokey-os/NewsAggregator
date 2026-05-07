# -*- coding: utf-8 -*-
"""
WSGI-конфигурация для PythonAnywhere.
Этот файл размещается в /var/www/nokey_pythonanywhere_com_wsgi.py
Настроить через: PythonAnywhere Dashboard → Web → WSGI configuration file
"""

import sys
import os

# ===== НАСТРОЙКИ =====
# Путь к папке с проектом на PythonAnywhere
# Замените 'nokey' на ваш логин, если отличается
PROJECT_PATH = '/home/nokey/NewsAggregator'

# Добавляем путь проекта в sys.path
if PROJECT_PATH not in sys.path:
    sys.path.insert(0, PROJECT_PATH)

# Устанавливаем рабочую директорию
os.chdir(PROJECT_PATH)

# Импортируем Flask-приложение
# 'app' — это имя файла app.py
from app import app as application

# Отключаем debug для production
application.debug = False
