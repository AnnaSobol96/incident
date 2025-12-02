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
        
        # Очищаем и подготавливаем JSON
        google_creds_json = google_creds_json.strip()
        
        # Убираем окружающие кавычки если они есть
        if google_creds_json.startswith('"') and google_creds_json.endswith('"'):
            google_creds_json = google_creds_json[1:-1]
        
        # Исправляем экранированные символы
        google_creds_json = google_creds_json.replace('\\n', '\n')
        google_creds_json = google_creds_json.replace('\\"', '"')
        google_creds_json = google_creds_json.replace('\\\\', '\\')
        
        # Убираем лишние пробелы в начале/конце строк
        lines = google_creds_json.split('\n')
        cleaned_lines = [line.strip() for line in lines]
        google_creds_json = '\n'.join(cleaned_lines)
        
        # Проверяем, что это валидный JSON
        try:
            credentials_dict = json.loads(google_creds_json)
            logger.info("✅ JSON успешно загружен и распарсен")
        except json.JSONDecodeError as e:
            logger.error(f"❌ Ошибка в JSON: {e}")
            logger.error(f"Первые 200 символов JSON: {google_creds_json[:200]}")
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
        
        logger.info(f"✅ Найден сервисный аккаунт: {credentials_dict['client_email']}")
        
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
        
        # Открываем таблицу
        try:
            spreadsheet = gc.open("google-api-sheets-incident")
            logger.info(f"✅ Таблица найдена: {spreadsheet.title}")
            logger.info(f"📊 ID таблицы: {spreadsheet.id}")
            
            # Проверяем доступ
            worksheets = spreadsheet.worksheets()
            logger.info(f"📄 Найдено листов: {len(worksheets)}")
            
            # Выводим названия листов
            for i, ws in enumerate(worksheets):
                logger.info(f"  {i+1}. {ws.title} ({ws.row_count} строк, {ws.col_count} колонок)")
            
            return spreadsheet
            
        except gspread.SpreadsheetNotFound:
            logger.error("❌ Таблица 'google-api-sheets-incident' не найдена!")
            logger.info("ℹ️ Что проверить:")
            logger.info("1. Таблица должна называться ТОЧНО 'google-api-sheets-incident'")
            logger.info("2. У сервисного аккаунта должен быть доступ к таблице")
            logger.info("3. Поделитесь таблицей с email: %s", credentials_dict['client_email'])
            return None
        except Exception as e:
            logger.error(f"❌ Ошибка при открытии таблицы: {e}")
            return None
            
    except Exception as e:
        logger.error(f"❌ Критическая ошибка инициализации: {str(e)}", exc_info=True)
        return None

# Инициализируем Google Sheets
spreadsheet = init_google_sheets()

def save_to_google_sheets(data):
    """Сохранение данных в Google Sheets"""
    logger.debug(f"📤 Получены данные для сохранения: {data}")
    
    # Если Google Sheets не инициализирована, используем заглушку
    if not spreadsheet:
        logger.warning("📝 Google Sheets не подключена, использую заглушку")
        try:
            # Сохраняем в текстовый файл для отладки
            with open('local_backup.txt', 'a', encoding='utf-8') as f:
                f.write(f"{datetime.now().isoformat()}: {json.dumps(data, ensure_ascii=False)}\n")
            logger.info("✅ Данные сохранены в локальный файл")
            return True
        except Exception as e:
            logger.error(f"❌ Ошибка локального сохранения: {e}")
            return False
    
    try:
        # Создаем название листа по месяцу
        current_month = datetime.now().strftime("%Y-%m")
        logger.debug(f"📅 Используем лист: {current_month}")
        
        # Пытаемся получить лист
        try:
            sheet = spreadsheet.worksheet(current_month)
            logger.info(f"✅ Лист '{current_month}' найден")
        except gspread.WorksheetNotFound:
            logger.info(f"🆕 Создаю новый лист: {current_month}")
            
            # Создаем новый лист
            sheet = spreadsheet.add_worksheet(
                title=current_month, 
                rows=1000, 
                cols=10
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
            sheet.insert_row(headers, index=1)
            logger.info("✅ Заголовки добавлены")
        
        # Подготавливаем данные для записи
        record = [
            data[0],  # timestamp
            data[1],  # district
            data[2],  # category
            data[3],  # text
            "",  # telegram_id (можно добавить позже)
            "",  # username
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "новое"
        ]
        
        logger.debug(f"📝 Записываю строку: {record}")
        
        # Безопасная запись с блокировкой
        with write_lock:
            # Находим первую пустую строку
            all_values = sheet.get_all_values()
            next_row = len(all_values) + 1
            logger.debug(f"📄 Текущее количество строк: {len(all_values)}, следующая строка: {next_row}")
            
            # Записываем данные
            sheet.append_row(record, value_input_option='USER_ENTERED')
            
            # Подтверждаем запись
            sheet.update(f'A{next_row}:H{next_row}', [record])
            logger.info(f"✅ Данные записаны в строку {next_row}")
        
        # Ссылка на таблицу для удобства
        sheet_url = f"https://docs.google.com/spreadsheets/d/{spreadsheet.id}/edit#gid={sheet.id}"
        logger.info(f"🔗 Таблица: {sheet_url}")
        
        return True
        
    except Exception as e:
        logger.error(f"❌ Ошибка записи в Google Sheets: {e}")
        logger.error(f"🔧 Детали ошибки:", exc_info=True)
        
        # Пробуем альтернативный метод
        try:
            logger.info("🔄 Пробую альтернативный метод записи...")
            return save_to_google_sheets_fallback(data)
        except Exception as e2:
            logger.error(f"❌ Альтернативный метод тоже не сработал: {e2}")
            return False

def save_to_google_sheets_fallback(data):
    """Альтернативный метод записи в Google Sheets"""
    try:
        current_month = datetime.now().strftime("%Y-%m")
        
        # Получаем все листы
        all_sheets = spreadsheet.worksheets()
        
        # Ищем нужный лист
        target_sheet = None
        for sheet in all_sheets:
            if sheet.title == current_month:
                target_sheet = sheet
                break
        
        # Если не нашли - создаем
        if not target_sheet:
            target_sheet = spreadsheet.add_worksheet(title=current_month, rows=1000, cols=10)
            
            # Добавляем заголовки
            headers = ["Дата", "Район", "Категория", "Текст"]
            target_sheet.append_row(headers)
        
        # Простая запись
        target_sheet.append_row(data)
        return True
        
    except Exception as e:
        logger.error(f"❌ Ошибка в альтернативном методе: {e}")
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
            .log {{
                background: #333;
                color: #0f0;
                padding: 10px;
                border-radius: 5px;
                font-family: monospace;
                max-height: 200px;
                overflow: auto;
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
            
            <div class="section">
                <h3>📝 Последние логи</h3>
                <div class="log">
                    <pre>Последние записи будут здесь...</pre>
                </div>
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
            "user_states_count": len(user_states),
            "memory_usage": "N/A"
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
            return jsonify({
                "status": "not_initialized", 
                "message": "Google Sheets не инициализирована",
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
            
            # Пробуем получить количество записей
            try:
                values = ws.get_all_values()
                sheet_info["record_count"] = len(values) - 1  # минус заголовок
            except:
                sheet_info["record_count"] = "unknown"
            
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
        <p>Последние записи из Google Sheets/локального бэкапа:</p>
        <pre style="background: #333; color: #0f0; padding: 20px; border-radius: 5px; overflow: auto;">
        {''.join(log_content) if log_content else 'Логи пока пусты'}
        </pre>
        <p><a href="/">← На главную</a></p>
        '''
    except Exception as e:
        return f'<h1>❌ Ошибка: {str(e)}</h1>'

# ============ ОБРАБОТЧИК ВЕБХУКА ============

@app.route(WEBHOOK_PATH, methods=['POST'])
def webhook():
    """Основной обработчик вебхука"""
    try:
        data = request.get_json()
        
        # Логируем получение данных
        logger.info(f"📩 Получены данные от Telegram")
        
        # Проверяем, что это сообщение
        if 'message' in data:
            message = data['message']
            chat_id = message['chat']['id']
            text = message.get('text', '')
            user_id = message['from']['id']
            first_name = message['from'].get('first_name', 'пользователь')
            
            logger.info(f"👤 {first_name} ({user_id}): {text}")
            
            # ============ ОБРАБОТКА КОМАНД ============
            
            # Команда /start или /help
            if text in ['/start', '/start@IncidentInfo_bot', '/help', '/help@IncidentInfo_bot']:
                welcome_text = f"""
👋 Здравствуйте, {first_name}!

Вас приветствует бот для сбора обращений граждан Бурятии.

📋 <b>Как это работает:</b>
1. Выберите район из списка
2. Выберите категорию обращения
3. Опишите вашу проблему

📊 <b>Все обращения записываются в Google Таблицы</b>

📍 <b>Выберите район:</b>
"""
                send_message(chat_id, welcome_text, get_district_keyboard())
                user_states[chat_id] = {
                    'step': 'district',
                    'user_id': user_id,
                    'first_name': first_name
                }
            
            # Команда /stats
            elif text in ['/stats', '/stats@IncidentInfo_bot']:
                stats_text = f"""
📊 <b>Статистика бота:</b>

📍 <b>Районы:</b> 23 района Бурятии
🏷️ <b>Категории:</b> 23 категории обращений
💾 <b>Хранение:</b> {'Google Sheets ✅' if spreadsheet else 'Локальное хранилище ⚠️'}
🤖 <b>Бот:</b> @IncidentInfo_bot
👥 <b>Активные пользователи:</b> {len(user_states)}

Для начала работы отправьте /start
"""
                send_message(chat_id, stats_text)
            
            # ============ ОБРАБОТКА ВЫБОРА РАЙОНА ============
            
            elif text in DISTRICTS:
                if text == "НА ПЛАНЕРКУ ГЛАВЫ":
                    # Особый случай - сразу запрашиваем текст
                    user_states[chat_id] = {
                        'district': text,
                        'category': 'Планерка',
                        'step': 'text',
                        'user_id': user_id,
                        'first_name': first_name
                    }
                    
                    send_message(
                        chat_id,
                        f"📍 <b>Вы выбрали:</b> {text}\n\n"
                        f"🏷️ <b>Категория:</b> Планерка\n\n"
                        f"📝 <b>Пожалуйста, опишите ваше обращение:</b>",
                        remove_keyboard=True
                    )
                else:
                    # Обычный район
                    user_states[chat_id] = {
                        'district': text,
                        'step': 'category',
                        'user_id': user_id,
                        'first_name': first_name
                    }
                    
                    send_message(
                        chat_id,
                        f"📍 <b>Вы выбрали район:</b> {text}\n\n"
                        f"🏷️ <b>Теперь выберите категорию обращения:</b>",
                        get_category_keyboard()
                    )
            
            # ============ ОБРАБОТКА ВЫБОРА КАТЕГОРИИ ============
            
            elif text in CATEGORIES:
                if chat_id not in user_states or user_states[chat_id].get('step') != 'category':
                    send_message(
                        chat_id,
                        "⚠️ <b>Сначала выберите район!</b>",
                        get_district_keyboard()
                    )
                else:
                    user_states[chat_id]['category'] = text
                    user_states[chat_id]['step'] = 'text'
                    
                    send_message(
                        chat_id,
                        f"🏷️ <b>Вы выбрали категорию:</b> {text}\n\n"
                        f"📝 <b>Теперь подробно опишите ваше обращение:</b>\n\n"
                        f"<i>Опишите проблему максимально подробно. Укажите адрес, если это возможно.</i>",
                        remove_keyboard=True
                    )
            
            # ============ КНОПКА "НАЗАД" ============
            
            elif text == '↩️ Назад к выбору района':
                user_states[chat_id] = {
                    'step': 'district',
                    'user_id': user_id,
                    'first_name': first_name
                }
                send_message(
                    chat_id,
                    "📍 <b>Выберите район:</b>",
                    get_district_keyboard()
                )
            
            # ============ ОБРАБОТКА ТЕКСТОВОГО ОБРАЩЕНИЯ ============
            
            elif chat_id in user_states and user_states[chat_id].get('step') == 'text':
                # Пользователь отправляет текст обращения
                district = user_states[chat_id].get('district', 'Не указан')
                category = user_states[chat_id].get('category', 'Не указана')
                user_text = text
                
                logger.info(f"💾 Сохраняю обращение: {district} | {category} | {user_text[:50]}...")
                
                # Сохраняем в Google Sheets
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                success = save_to_google_sheets([timestamp, district, category, user_text])
                
                if success:
                    response_text = f"""
✅ <b>Спасибо! Ваше обращение записано.</b>

📍 <b>Район:</b> {district}
🏷️ <b>Категория:</b> {category}
📝 <b>Ваше обращение:</b> {user_text}
🕐 <b>Время:</b> {datetime.now().strftime('%d.%m.%Y %H:%M')}

<i>Обращение будет рассмотрено в установленном порядке.</i>

Для нового обращения выберите район:
"""
                else:
                    response_text = """
⚠️ <b>Ваше обращение сохранено в локальной базе.</b>

<i>Google Sheets временно недоступна, но ваши данные не потеряны.
Администратор получит их при восстановлении связи.</i>

Для нового обращения выберите район:
"""
                
                send_message(chat_id, response_text, get_district_keyboard())
                
                # Очищаем состояние пользователя
                if chat_id in user_states:
                    del user_states[chat_id]
            
            # ============ ЛЮБОЕ ДРУГОЕ СООБЩЕНИЕ ============
            
            elif text:
                # Если пользователь просто написал текст без выбора
                send_message(
                    chat_id,
                    "Для начала работы выберите район и категорию.\n\n"
                    "Отправьте /start для начала работы.",
                    get_district_keyboard()
                )
        
        return jsonify({'ok': True})
        
    except Exception as e:
        logger.error(f"❌ Ошибка в вебхуке: {e}", exc_info=True)
        return jsonify({'ok': False, 'error': str(e)}), 500

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
