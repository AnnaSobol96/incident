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
logging.basicConfig(level=logging.INFO)
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
        if google_creds_json:
            # Обработка JSON из переменной окружения
            google_creds_json = google_creds_json.strip()
            if google_creds_json.startswith('"') and google_creds_json.endswith('"'):
                google_creds_json = google_creds_json[1:-1]
            
            google_creds_json = google_creds_json.replace('\\n', '\n').replace('\\"', '"')
            credentials_dict = json.loads(google_creds_json)
            
            scopes = ['https://www.googleapis.com/auth/spreadsheets']
            credentials = Credentials.from_service_account_info(credentials_dict, scopes=scopes)
            gc = gspread.authorize(credentials)
            
            spreadsheet = gc.open("google-api-sheets-incident")
            logger.info("✅ Google Sheets подключена")
            return spreadsheet
        else:
            logger.info("⚠️ GOOGLE_CREDENTIALS не установлен, используется заглушка")
            return None
    except Exception as e:
        logger.error(f"❌ Ошибка Google Sheets: {e}")
        return None

spreadsheet = init_google_sheets()

def save_to_google_sheets(data):
    """Сохранение данных в Google Sheets"""
    if not spreadsheet:
        logger.info(f"📝 Тестовая запись: {data}")
        return True
    
    try:
        # Получаем текущий месяц
        current_month = datetime.now().strftime("%Y-%m")
        
        try:
            sheet = spreadsheet.worksheet(current_month)
        except:
            sheet = spreadsheet.add_worksheet(title=current_month, rows=1000, cols=20)
            sheet.append_row(["Дата и время", "Район", "Категория обращения", "Текст обращения"])
        
        with write_lock:
            sheet.append_row(data, value_input_option='USER_ENTERED')
        
        logger.info(f"✅ Данные сохранены в Google Sheets")
        return True
    except Exception as e:
        logger.error(f"❌ Ошибка сохранения: {e}")
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
    
    # Разбиваем районы на группы по 3
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
    
    # Разбиваем категории на группы по 3
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
    return '''
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>🤖 Бот для обращений - Бурятия</title>
        <style>
            body {
                font-family: Arial, sans-serif;
                max-width: 800px;
                margin: 0 auto;
                padding: 20px;
                background-color: #f5f5f5;
            }
            .container {
                background: white;
                padding: 30px;
                border-radius: 10px;
                box-shadow: 0 2px 10px rgba(0,0,0,0.1);
            }
            h1 {
                color: #333;
                border-bottom: 2px solid #4CAF50;
                padding-bottom: 10px;
            }
            .status {
                background: #4CAF50;
                color: white;
                padding: 15px;
                border-radius: 5px;
                margin: 20px 0;
            }
            .btn {
                display: inline-block;
                background: #0088cc;
                color: white;
                padding: 12px 24px;
                text-decoration: none;
                border-radius: 5px;
                margin: 10px 5px;
                transition: background 0.3s;
            }
            .btn:hover {
                background: #006699;
            }
            .section {
                margin: 25px 0;
                padding: 20px;
                background: #f9f9f9;
                border-radius: 5px;
            }
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
            </div>
            
            <div class="section">
                <h3>📊 Статистика</h3>
                <p><strong>Районов:</strong> 23</p>
                <p><strong>Категорий:</strong> 23</p>
                <p><strong>Google Sheets:</strong> ''' + ("✅ Подключена" if spreadsheet else "⚠️ Заглушка") + '''</p>
                <p><strong>Бот:</strong> @IncidentInfo_bot</p>
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
            "timestamp": datetime.now().isoformat()
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
            }
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
            "Тестовое сообщение"
        ]
        
        success = save_to_google_sheets(test_data)
        
        if success:
            return '''
            <h1>✅ Тест базы данных</h1>
            <p>Тестовая запись успешно добавлена.</p>
            <p><a href="/">← На главную</a></p>
            '''
        else:
            return '''
            <h1>⚠️ Тест с заглушкой</h1>
            <p>Google Sheets не подключена, используется заглушка.</p>
            <p>Добавьте GOOGLE_CREDENTIALS для подключения к Google Sheets.</p>
            <p><a href="/">← На главную</a></p>
            '''
    except Exception as e:
        return f'<h1>❌ Ошибка: {str(e)}</h1>', 500

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
                user_states[chat_id] = {'step': 'district'}
            
            # Команда /stats
            elif text in ['/stats', '/stats@IncidentInfo_bot']:
                stats_text = """
📊 <b>Статистика бота:</b>

📍 <b>Районы:</b> 23 района Бурятии
🏷️ <b>Категории:</b> 23 категории обращений
💾 <b>Хранение:</b> Google Sheets
🤖 <b>Бот:</b> @IncidentInfo_bot

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
                        'step': 'text'
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
                        'step': 'category'
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
                user_states[chat_id] = {'step': 'district'}
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
❌ <b>Произошла ошибка при записи данных.</b>

Пожалуйста, попробуйте еще раз позже или свяжитесь с администратором.

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
    app.run(host='0.0.0.0', port=port)
