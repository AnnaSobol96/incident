import os
import requests
import json
import gspread
from datetime import datetime
from flask import Flask, request, jsonify
from google.oauth2.service_account import Credentials
import logging
from threading import Lock

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
    """Инициализация Google Sheets"""
    try:
        google_creds_json = os.getenv('GOOGLE_CREDENTIALS')
        
        if not google_creds_json:
            logger.warning("⚠️ GOOGLE_CREDENTIALS не установлен, используется заглушка")
            return None
        
        logger.info("🔧 Начинаем инициализацию Google Sheets...")
        logger.info(f"📏 Длина JSON: {len(google_creds_json)} символов")
        logger.info(f"📝 Первые 100 символов: {google_creds_json[:100]}")
        
        # Очищаем JSON - удаляем пробелы в начале и конце
        google_creds_json = google_creds_json.strip()
        
        # Удаляем возможные лишние кавычки
        # Если строка начинается и заканчивается двойными кавычками
        if (google_creds_json.startswith('"') and google_creds_json.endswith('"') and 
            google_creds_json.count('"') == 2):
            # Удаляем только внешние кавычки
            google_creds_json = google_creds_json[1:-1]
            logger.info("✅ Удалил внешние кавычки")
        
        # Заменяем экранированные символы
        google_creds_json = google_creds_json.replace('\\n', '\n')
        google_creds_json = google_creds_json.replace('\\"', '"')
        google_creds_json = google_creds_json.replace('\\\\', '\\')
        
        logger.info(f"📝 Очищенный JSON начинается с: {google_creds_json[:50]}...")
        
        try:
            credentials_dict = json.loads(google_creds_json)
            logger.info("✅ JSON успешно загружен и распарсен")
            logger.info(f"📋 Найдены ключи: {list(credentials_dict.keys())}")
        except json.JSONDecodeError as e:
            logger.error(f"❌ Ошибка декодирования JSON: {e}")
            logger.error(f"🔍 Позиция ошибки: {e.pos}")
            
            # Попробуем альтернативный парсинг
            try:
                logger.info("🔄 Пробую альтернативный метод парсинга...")
                # Пробуем удалить все лишние пробелы
                import re
                cleaned_json = re.sub(r'\s+', ' ', google_creds_json)
                credentials_dict = json.loads(cleaned_json)
                logger.info("✅ JSON успешно загружен альтернативным методом")
            except Exception as e2:
                logger.error(f"❌ Альтернативный метод тоже не сработал: {e2}")
                return None
        
        # Проверяем обязательные поля
        required_fields = ['type', 'project_id', 'private_key_id', 'private_key', 'client_email']
        missing_fields = []
        for field in required_fields:
            if field not in credentials_dict:
                missing_fields.append(field)
        
        if missing_fields:
            logger.error(f"❌ Отсутствуют обязательные поля: {missing_fields}")
            return None
        
        logger.info(f"✅ Сервисный аккаунт: {credentials_dict['client_email']}")
        logger.info(f"✅ Проект: {credentials_dict['project_id']}")
        
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
            
            # Выводим названия листов
            for i, ws in enumerate(worksheets):
                logger.info(f"  {i+1}. {ws.title} ({ws.row_count} строк)")
            
            # Тестовое чтение данных
            try:
                first_sheet = worksheets[0]
                records = first_sheet.get_all_values()
                logger.info(f"📊 В первом листе {len(records)} строк(и)")
            except Exception as e:
                logger.warning(f"⚠️ Не удалось прочитать данные листа: {e}")
            
            return spreadsheet
            
        except gspread.SpreadsheetNotFound:
            logger.error("❌ Таблица 'google-api-sheets-incident' не найдена!")
            logger.info("ℹ️ Что проверить:")
            logger.info(f"1. Таблица должна называться ТОЧНО 'google-api-sheets-incident'")
            logger.info(f"2. Убедитесь, что сервисный аккаунт {credentials_dict['client_email']} имеет доступ к таблице")
            logger.info(f"3. Поделитесь таблицей по ссылке или добавьте email сервисного аккаунта")
            return None
            
    except Exception as e:
        logger.error(f"❌ Критическая ошибка инициализации: {str(e)}", exc_info=True)
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
        
        # Ссылка на таблицу для удобства
        sheet_url = f"https://docs.google.com/spreadsheets/d/{spreadsheet.id}/edit#gid={sheet.id}"
        logger.info(f"🔗 Таблица: {sheet_url}")
        
        return True
        
    except Exception as e:
        logger.error(f"❌ Ошибка записи в Google Sheets: {e}")
        logger.error(f"🔧 Детали ошибки:", exc_info=True)
        return False

# ============ ТЕЛЕГРАМ ФУНКЦИИ ============

def send_message(chat_id, text, keyboard=None, remove_keyboard=False):
    """Отправка сообщения в Telegram"""
    url = f'{TELEGRAM_API_URL}/sendMessage'
    data = {
        'chat_id': chat_id,
        'text': text,
        'parse_mode': 'HTML',
        'disable_web_page_preview': True
    }
    
    if remove_keyboard:
        data['reply_markup'] = json.dumps({'remove_keyboard': True})
    elif keyboard:
        data['reply_markup'] = json.dumps(keyboard)
    
    try:
        response = requests.post(url, json=data, timeout=10)
        return response.json()
    except Exception as e:
        logger.error(f"❌ Ошибка отправки сообщения: {e}")
        return None

def get_district_keyboard():
    """Клавиатура районов (3 кнопки в ряд)"""
    keyboard = []
    
    for i in range(0, len(DISTRICTS), 3):
        row = [{'text': district} for district in DISTRICTS[i:i+3]]
        keyboard.append(row)
    
    return {
        'keyboard': keyboard,
        'resize_keyboard': True,
        'one_time_keyboard': False
    }

def get_category_keyboard():
    """Клавиатура категорий (3 кнопки в ряд)"""
    keyboard = []
    
    for i in range(0, len(CATEGORIES), 3):
        row = [{'text': category} for category in CATEGORIES[i:i+3]]
        keyboard.append(row)
    
    # Добавляем кнопку "Назад"
    keyboard.append([{'text': '↩️ Назад к выбору района'}])
    
    return {
        'keyboard': keyboard,
        'resize_keyboard': True,
        'one_time_keyboard': False
    }

# ============ FLASK РОУТЫ ============

@app.route('/')
def index():
    """Главная страница"""
    google_status = "✅ Подключена" if spreadsheet else "⚠️ Заглушка"
    
    return f'''
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>🤖 Бот для обращений - Бурятия</title>
        <style>
            body {{
                font-family: Arial, sans-serif;
                max-width: 800px;
                margin: 0 auto;
                padding: 20px;
                background-color: #f5f5f5;
            }}
            .container {{
                background: white;
                padding: 30px;
                border-radius: 10px;
                box-shadow: 0 2px 10px rgba(0,0,0,0.1);
            }}
            h1 {{
                color: #333;
                border-bottom: 2px solid #4CAF50;
                padding-bottom: 10px;
            }}
            .status {{
                background: #4CAF50;
                color: white;
                padding: 15px;
                border-radius: 5px;
                margin: 20px 0;
            }}
            .warning {{
                background: #ff9800;
                color: white;
                padding: 15px;
                border-radius: 5px;
                margin: 20px 0;
            }}
            .btn {{
                display: inline-block;
                background: #0088cc;
                color: white;
                padding: 12px 24px;
                text-decoration: none;
                border-radius: 5px;
                margin: 10px 5px;
                transition: background 0.3s;
            }}
            .btn:hover {{
                background: #006699;
            }}
            .section {{
                margin: 25px 0;
                padding: 20px;
                background: #f9f9f9;
                border-radius: 5px;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🤖 Бот для сбора обращений - Бурятия</h1>
            <p>Telegram бот для сбора обращений граждан с записью в Google Таблицы</p>
            
            <div class="status">
                ✅ <strong>Статус:</strong> Система работает
            </div>
            
            <div class="section">
                <h3>⚙️ Управление</h3>
                <a class="btn" href="/set_webhook">Установить вебхук</a>
                <a class="btn" href="/health">Проверить здоровье</a>
                <a class="btn" href="/bot_info">Информация о боте</a>
                <a class="btn" href="/test_db">Тест базы данных</a>
                <a class="btn" href="/debug_sheets">Диагностика Sheets</a>
                <a class="btn" href="/check_creds">Проверить credentials</a>
                <a class="btn" href="/view_logs">Посмотреть логи</a>
            </div>
            
            <div class="section">
                <h3>📊 Статистика</h3>
                <p><strong>Районов:</strong> 23</p>
                <p><strong>Категорий:</strong> 23</p>
                <p><strong>Google Sheets:</strong> {google_status}</p>
                <p><strong>Бот:</strong> @IncidentInfo_bot</p>
                <p><strong>Пользователей в сессии:</strong> {len(user_states)}</p>
            </div>
            
            <div class="section">
                <h3>🔧 Использование</h3>
                <ol>
                    <li>Найдите бота @IncidentInfo_bot в Telegram</li>
                    <li>Отправьте команду /start</li>
                    <li>Выберите район → категорию → опишите проблему</li>
                    <li>Данные автоматически сохранятся</li>
                </ol>
            </div>
        </div>
    </body>
    </html>
    '''

@app.route('/health')
def health_check():
    """Проверка здоровья приложения"""
    try:
        response = requests.get(f'{TELEGRAM_API_URL}/getMe', timeout=5)
        bot_info = response.json()
        
        return jsonify({
            "status": "ok",
            "bot": bot_info.get('result', {}).get('username'),
            "google_sheets": "connected" if spreadsheet else "stub",
            "timestamp": datetime.now().isoformat(),
            "user_states_count": len(user_states)
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/set_webhook')
def set_webhook_route():
    """Установка вебхука"""
    try:
        # Удаляем старый вебхук
        requests.get(f'{TELEGRAM_API_URL}/deleteWebhook', timeout=5)
        
        # Устанавливаем новый
        response = requests.post(
            f'{TELEGRAM_API_URL}/setWebhook',
            json={'url': f'{WEBHOOK_URL}{WEBHOOK_PATH}'},
            timeout=5
        )
        
        result = response.json()
        
        if result.get('ok'):
            return '''
            <h1>✅ Вебхук установлен</h1>
            <p>Вебхук успешно настроен для работы с ботом.</p>
            <p><strong>Отправьте /start боту @IncidentInfo_bot для проверки</strong></p>
            <p><a href="/">← На главную</a></p>
            '''
        else:
            return f'''
            <h1>❌ Ошибка установки вебхука</h1>
            <pre>{json.dumps(result, indent=2)}</pre>
            <p><a href="/">← На главную</a></p>
            ''', 500
    except Exception as e:
        return f'<h1>❌ Ошибка: {str(e)}</h1>', 500

@app.route('/bot_info')
def bot_info():
    """Информация о боте"""
    try:
        response = requests.get(f'{TELEGRAM_API_URL}/getMe', timeout=5)
        bot_info = response.json()
        
        webhook_response = requests.get(f'{TELEGRAM_API_URL}/getWebhookInfo', timeout=5)
        webhook_info = webhook_response.json()
        
        return jsonify({
            "bot": bot_info.get('result', {}),
            "webhook": webhook_info.get('result', {}),
            "server": {
                "url": WEBHOOK_URL,
                "timestamp": datetime.now().isoformat()
            },
            "google_sheets": "connected" if spreadsheet else "not_connected"
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/test_db')
def test_db():
    """Тест базы данных"""
    try:
        test_data = [
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "Тестовый район",
            "Тестовая категория",
            "Это тестовое сообщение для проверки записи в Google Sheets"
        ]
        
        logger.info("🧪 Начинаю тест записи в базу данных...")
        success = save_to_google_sheets(test_data)
        
        if success:
            return '''
            <h1>✅ Тест базы данных</h1>
            <p>Тестовая запись успешно добавлена.</p>
            <p><strong>Проверьте Google Таблицу или файл local_backup.txt</strong></p>
            <p><a href="/">← На главную</a></p>
            '''
        else:
            return '''
            <h1>⚠️ Ошибка при тестировании</h1>
            <p>Не удалось записать тестовые данные.</p>
            <p>Проверьте логи на Render для диагностики.</p>
            <p><a href="/">← На главную</a></p>
            '''
    except Exception as e:
        return f'<h1>❌ Ошибка: {str(e)}</h1>', 500

@app.route('/debug_sheets')
def debug_sheets():
    """Диагностика Google Sheets"""
    try:
        if not spreadsheet:
            # Попробуем переинициализировать
            global spreadsheet
            logger.info("🔄 Пробую переинициализировать Google Sheets...")
            spreadsheet = init_google_sheets()
            
            if not spreadsheet:
                return jsonify({
                    "status": "not_initialized", 
                    "message": "Google Sheets не инициализирована после повторной попытки",
                    "timestamp": datetime.now().isoformat()
                })
        
        # Получаем информацию о таблице
        info = {
            "id": spreadsheet.id,
            "title": spreadsheet.title,
            "url": f"https://docs.google.com/spreadsheets/d/{spreadsheet.id}",
            "sheet_count": len(spreadsheet.worksheets()),
            "sheets": []
        }
        
        # Информация о каждом листе
        for ws in spreadsheet.worksheets():
            sheet_info = {
                "id": ws.id,
                "title": ws.title,
                "row_count": ws.row_count,
                "col_count": ws.col_count,
                "url": f"https://docs.google.com/spreadsheets/d/{spreadsheet.id}/edit#gid={ws.id}"
            }
            
            info["sheets"].append(sheet_info)
        
        return jsonify({
            "status": "success",
            "spreadsheet": info,
            "timestamp": datetime.now().isoformat()
        })
        
    except Exception as e:
        return jsonify({
            "status": "error",
            "error": str(e),
            "type": type(e).__name__
        }), 500

@app.route('/check_creds')
def check_creds():
    """Проверка credentials"""
    try:
        google_creds_json = os.getenv('GOOGLE_CREDENTIALS')
        
        if not google_creds_json:
            return jsonify({
                "status": "error",
                "message": "GOOGLE_CREDENTIALS не установлен",
                "env_vars": dict(os.environ)
            }), 500
        
        return jsonify({
            "status": "success",
            "creds_length": len(google_creds_json),
            "first_50_chars": google_creds_json[:50],
            "last_50_chars": google_creds_json[-50:],
            "has_newlines": "\n" in google_creds_json,
            "has_quotes": google_creds_json.startswith('"') and google_creds_json.endswith('"')
        })
        
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500

@app.route('/view_logs')
def view_logs():
    """Просмотр логов"""
    try:
        # Читаем последние 50 строк из лог-файла
        log_content = []
        if os.path.exists('local_backup.txt'):
            with open('local_backup.txt', 'r', encoding='utf-8') as f:
                lines = f.readlines()
                log_content = lines[-50:]  # Последние 50 строк
        
        return f'''
        <h1>📊 Логи приложения</h1>
        <p>Последние записи из локального бэкапа:</p>
        <pre style="background: #333; color: #0f0; padding: 20px; border-radius: 5px; overflow: auto; max-height: 500px;">
        {''.join(log_content) if log_content else 'Логи пока пусты'}
        </pre>
        <p><a href="/">← На главную</a></p>
        '''
    except Exception as e:
        return f'<h1>❌ Ошибка: {str(e)}</h1>'

# ============ ОБРАБОТЧИК ВЕБХУКА ============
# [Весь остальной код обработки вебхука остается БЕЗ ИЗМЕНЕНИЙ]
# ============ ЗАПУСК ПРИЛОЖЕНИЯ ============

if __name__ == '__main__':
    logger.info("🚀 Запуск полнофункционального бота...")
    logger.info(f"🤖 Токен бота: {TELEGRAM_TOKEN[:10]}...")
    logger.info(f"🌐 Вебхук URL: {WEBHOOK_URL}")
    logger.info(f"📊 Google Sheets: {'✅ Подключена' if spreadsheet else '⚠️ Заглушка'}")
    
    # Автоматическая установка вебхука
    try:
        requests.get(f'{TELEGRAM_API_URL}/deleteWebhook', timeout=5)
        
        response = requests.post(
            f'{TELEGRAM_API_URL}/setWebhook',
            json={'url': f'{WEBHOOK_URL}{WEBHOOK_PATH}'},
            timeout=5
        )
        
        if response.json().get('ok'):
            logger.info("✅ Вебхук установлен автоматически")
        else:
            logger.error(f"❌ Ошибка установки вебхука: {response.json()}")
    except Exception as e:
        logger.error(f"❌ Ошибка при установке вебхука: {e}")
    
    # Запуск Flask
    port = int(os.getenv('PORT', 10000))
    logger.info(f"🚀 Запуск на порту {port}")
    app.run(host='0.0.0.0', port=port, debug=False)
