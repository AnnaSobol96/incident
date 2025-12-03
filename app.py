import os
import requests
import json
import gspread
from datetime import datetime
from flask import Flask, request, jsonify
from google.oauth2.service_account import Credentials
import logging
from threading import Lock
import re

# Настройка логирования
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# ============ КОНФИГУРАЦИЯ ============

TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN', '8590157858:AAGVPYg1DHXNQaSbrdce7lfxq-RyMtufi5Y')
TELEGRAM_API_URL = f'https://api.telegram.org/bot{TELEGRAM_TOKEN}'
WEBHOOK_URL = 'https://incident-evai.onrender.com'
WEBHOOK_PATH = '/webhook'

# ============ ДАННЫЕ БОТА ============

DISTRICTS = [
    "Кабанский", "Закаменский", "Бичурский", "Кяхтинский", 
    "Муйский", "Курумканский", "Мухоршибирский", "Тарбагатайский", 
    "Тункинский", "Окинский", "Селенгинский", "Джидинский", 
    "Хоринский", "Кижингинский", "Иволгинский", "Заиграевский", 
    "Прибайкальский", "Баргузинский", "Баунтовский", "Еравнинский", 
    "г.Северобайкальск", "Северо-Байкальский", "НА ПЛАНЕРКУ ГЛАВЫ"
]

CATEGORIES = [
    "Дороги", "Транспорт", "Госуслуги", "Благоустройство", 
    "Иное", "Здравоохранение", "Соц. защита", "Образование", 
    "ЖКХ", "Энергетика", "СВО, мобилизация", "Мусор", 
    "Безопасность", "С/х и охота", "Связь и информационные системы", 
    "Культура", "Экономика", "Экология, недра, лесхоз", 
    "Физ. культура и спорт", "Труд и занятость", "Строительство", 
    "Общ- полит.вопросы", "Туризм", "Планерка"
]

# Хранилище состояний пользователей
user_states = {}
write_lock = Lock()

# ============ GOOGLE SHEETS ============

def init_google_sheets():
    """Инициализация Google Sheets с исправленной обработкой JSON"""
    try:
        google_creds_json = os.getenv('GOOGLE_CREDENTIALS')
        
        if not google_creds_json:
            logger.warning("⚠️ GOOGLE_CREDENTIALS не установлен, используется заглушка")
            return None
        
        logger.info("🔧 Начинаем инициализацию Google Sheets...")
        logger.info(f"📏 Длина JSON: {len(google_creds_json)} символов")
        
        # Выводим первые 200 символов для диагностики
        logger.info(f"📝 Первые 200 символов: {google_creds_json[:200]}")
        
        # Простая очистка - удаляем пробелы в начале и конце
        google_creds_json = google_creds_json.strip()
        
        # Если JSON начинается и заканчивается кавычками - удаляем их
        if google_creds_json.startswith('"') and google_creds_json.endswith('"'):
            google_creds_json = google_creds_json[1:-1]
            logger.info("✅ Удалил внешние кавычки")
        
        # Удаляем все непечатаемые символы, кроме \n
        # Эта очистка исправляет проблему с недопустимыми управляющими символами
        google_creds_json = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', google_creds_json)
        
        # Исправляем экранированные символы
        google_creds_json = google_creds_json.replace('\\"', '"')
        google_creds_json = google_creds_json.replace('\\\\', '\\')
        
        # Заменяем \n на настоящие переносы строк (это важно для private key)
        google_creds_json = google_creds_json.replace('\\n', '\n')
        
        # Теперь пробуем загрузить JSON
        try:
            logger.info("🔄 Пробую загрузить JSON...")
            credentials_dict = json.loads(google_creds_json)
            logger.info("✅ JSON успешно загружен и распарсен")
        except json.JSONDecodeError as e:
            logger.error(f"❌ Ошибка декодирования JSON: {e}")
            logger.error(f"🔍 Позиция ошибки: {e.pos}")
            
            # Показываем контекст ошибки
            start = max(0, e.pos - 50)
            end = min(len(google_creds_json), e.pos + 50)
            error_context = google_creds_json[start:end]
            logger.error(f"📜 Контекст ошибки: ...{error_context}...")
            
            # Пробуем исправить JSON, удаляя все нестандартные символы
            logger.info("🔄 Пробую исправить JSON...")
            
            # Создаем "чистый" JSON, оставляя только безопасные символы
            safe_json = re.sub(r'[^\x20-\x7E\n\r\t]', '', google_creds_json)
            
            try:
                credentials_dict = json.loads(safe_json)
                logger.info("✅ JSON исправлен и успешно загружен")
            except Exception as e2:
                logger.error(f"❌ Не удалось исправить JSON: {e2}")
                return None
        
        # Проверяем обязательные поля
        required_fields = ['type', 'project_id', 'private_key_id', 'private_key', 'client_email']
        missing_fields = []
        for field in required_fields:
            if field not in credentials_dict:
                missing_fields.append(field)
        
        if missing_fields:
            logger.error(f"❌ Отсутствуют обязательные поля: {missing_fields}")
            logger.error(f"📋 Найденные поля: {list(credentials_dict.keys())}")
            return None
        
        logger.info(f"✅ Сервисный аккаунт: {credentials_dict['client_email']}")
        
        # Настраиваем scope
        scopes = [
            'https://www.googleapis.com/auth/spreadsheets',
            'https://www.googleapis.com/auth/drive'
        ]
        
        # Создаем credentials
        credentials = Credentials.from_service_account_info(
            credentials_dict, 
            scopes=scopes
        )
        
        # Авторизуемся
        gc = gspread.authorize(credentials)
        logger.info("✅ Авторизация в Google API успешна")
        
        # Пробуем открыть таблицу
        try:
            spreadsheet = gc.open("google-api-sheets-incident")
            logger.info(f"✅ Таблица найдена: {spreadsheet.title}")
            logger.info(f"📊 ID таблицы: {spreadsheet.id}")
            
            # Проверяем доступ к таблице
            worksheets = spreadsheet.worksheets()
            logger.info(f"📄 Найдено листов: {len(worksheets)}")
            
            return spreadsheet
            
        except gspread.SpreadsheetNotFound:
            logger.error("❌ Таблица 'google-api-sheets-incident' не найдена!")
            logger.info("ℹ️ Что проверить:")
            logger.info(f"1. Таблица должна называться ТОЧНО 'google-api-sheets-incident'")
            logger.info(f"2. Убедитесь, что сервисный аккаунт {credentials_dict['client_email']} имеет доступ к таблице")
            return None
            
    except Exception as e:
        logger.error(f"❌ Критическая ошибка инициализации: {str(e)}")
        import traceback
        logger.error(f"🔧 Трассировка: {traceback.format_exc()}")
        return None

# Инициализируем Google Sheets
logger.info("🔄 Инициализирую Google Sheets...")
spreadsheet = init_google_sheets()

def save_to_google_sheets(data):
    """Сохранение данных в Google Sheets"""
    logger.debug(f"📤 Получены данные для сохранения: {data}")
    
    # Если Google Sheets не инициализирована, используем заглушку
    if not spreadsheet:
        logger.warning("📝 Google Sheets не подключена, использую заглушку")
        try:
            # Сохраняем в текстовый файл для отладки
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            log_entry = f"[{timestamp}] {data[1]} | {data[2]} | {data[3]}\n"
            
            with open('local_backup.txt', 'a', encoding='utf-8') as f:
                f.write(log_entry)
            
            logger.info("✅ Данные сохранены в локальный файл local_backup.txt")
            return True
        except Exception as e:
            logger.error(f"❌ Ошибка локального сохранения: {e}")
            return False
    
    try:
        # Создаем название листа по месяцу
        current_month = datetime.now().strftime("%Y-%m")
        logger.info(f"📅 Используем лист: {current_month}")
        
        try:
            # Пытаемся получить существующий лист
            sheet = spreadsheet.worksheet(current_month)
            logger.info(f"✅ Лист '{current_month}' найден")
        except gspread.WorksheetNotFound:
            logger.info(f"🆕 Создаю новый лист: {current_month}")
            
            # Создаем новый лист
            sheet = spreadsheet.add_worksheet(
                title=current_month, 
                rows=1000, 
                cols=8
            )
            
            # Добавляем заголовки
            headers = [
                "Дата и время", 
                "Район", 
                "Категория обращения", 
                "Текст обращения",
                "Telegram ID",
                "Имя пользователя",
                "Дата создания",
                "Статус"
            ]
            
            # Вставляем заголовки
            sheet.append_row(headers)
            logger.info("✅ Заголовки добавлены")
        
        # Подготавливаем данные для записи
        record = [
            data[0],  # timestamp
            data[1],  # district
            data[2],  # category
            data[3],  # text
            "",  # telegram_id
            "",  # username
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "новое"
        ]
        
        logger.debug(f"📝 Записываю строку: {record}")
        
        # Находим первую пустую строку
        all_values = sheet.get_all_values()
        next_row = len(all_values) + 1
        logger.info(f"📄 Текущее количество строк: {len(all_values)}, следующая строка: {next_row}")
        
        # Записываем данные
        with write_lock:
            sheet.append_row(record, value_input_option='USER_ENTERED')
            logger.info(f"✅ Данные записаны в строку {next_row}")
        
        return True
        
    except Exception as e:
        logger.error(f"❌ Ошибка записи в Google Sheets: {e}")
        return False

# ============ ТЕЛЕГРАМ ФУНКЦИИ ============
# [Остальной код остается без изменений]
# ============ FLASK РОУТЫ ============
# [Остальной код остается без изменений]
# ============ ОБРАБОТЧИК ВЕБХУКА ============
# [Остальной код остается без изменений]
# ============ ЗАПУСК ПРИЛОЖЕНИЯ ============
# [Остальной код остается без изменений]
