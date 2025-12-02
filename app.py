import os
import telebot
from telebot import types
import gspread
from datetime import datetime, timedelta
import time
from threading import Lock
from flask import Flask, request, jsonify
import json
from google.oauth2.service_account import Credentials
import logging

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# Инициализация Flask приложения
app = Flask(__name__)

# ============ НАСТРОЙКА БОТА ============

# Токен Telegram бота (обязательно установить в Render)
TELEGRAM_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
if not TELEGRAM_TOKEN:
    logger.error("❌ TELEGRAM_BOT_TOKEN не установлен в переменных окружения!")
    # Для локального тестирования можно использовать заглушку
    TELEGRAM_TOKEN = "YOUR_BOT_TOKEN_HERE"
    logger.warning("⚠️ Используется заглушка для локальной разработки")

bot = telebot.TeleBot(TELEGRAM_TOKEN)
logger.info("✅ Бот инициализирован")

# URL вашего приложения на Render
WEBHOOK_URL = os.getenv('RENDER_EXTERNAL_URL', 'https://telegram-bot-buryatia2.onrender.com')
WEBHOOK_PATH = '/webhook'

# ============ ПОДКЛЮЧЕНИЕ К GOOGLE SHEETS ============

def init_google_sheets():
    """Инициализирует подключение к Google Sheets"""
    try:
        google_creds_json = os.getenv('GOOGLE_CREDENTIALS')
        if google_creds_json:
            # Парсим JSON из переменной окружения
            credentials_dict = json.loads(google_creds_json)
            
            # Исправляем формат private_key
            if '\\n' in credentials_dict.get('private_key', ''):
                credentials_dict['private_key'] = credentials_dict['private_key'].replace('\\n', '\n')
            
            # Создаем credentials
            scopes = [
                'https://www.googleapis.com/auth/spreadsheets',
                'https://www.googleapis.com/auth/drive'
            ]
            credentials = Credentials.from_service_account_info(credentials_dict, scopes=scopes)
            gc = gspread.authorize(credentials)
            logger.info("✅ Google Sheets подключена через переменные окружения")
            
            # Открываем таблицу
            spreadsheet = gc.open("google-api-sheets-incident")
            logger.info("✅ Таблица 'google-api-sheets-incident' открыта")
            return spreadsheet
            
        else:
            # Для локальной разработки
            logger.info("⚠️ GOOGLE_CREDENTIALS не установлен, используется файл clever.json")
            gc = gspread.service_account(filename="clever.json")
            spreadsheet = gc.open("google-api-sheets-incident")
            logger.info("✅ Таблица открыта через файл clever.json")
            return spreadsheet
            
    except Exception as e:
        logger.error(f"❌ Ошибка подключения к Google Sheets: {e}")
        return None

# Инициализируем Google Sheets
spreadsheet = init_google_sheets()

# Хранилище для временных данных пользователей
user_data = {}
write_lock = Lock()

# ============ СПИСКИ ДЛЯ КЛАВИАТУР ============

# Список районов Бурятии
DISTRICTS = [
    "Кабанский", "Закаменский", "Бичурский",
    "Кяхтинский", "Муйский", "Курумканский",
    "Мухоршибирский", "Тарбагатайский", "Тункинский",
    "Окинский", "Селенгинский", "Джидинский",
    "Хоринский", "Кижингинский", "Иволгинский",
    "Заиграевский", "Прибайкальский", "Баргузинский",
    "Баунтовский", "Еравнинский", "г.Северобайкальск",
    "Северо-Байкальский", "НА ПЛАНЕРКУ ГЛАВЫ"
]

# Список категорий обращений
CATEGORIES = [
    "Дороги", "Транспорт", "Госуслуги",
    "Благоустройство", "Иное", "Здравоохранение",
    "Соц. защита", "Образование", "ЖКХ",
    "Энергетика", "СВО, мобилизация", "Мусор",
    "Безопасность", "С/х и охота", "Связь и информационные системы",
    "Культура", "Экономика", "Экология, недра, лесхоз",
    "Физ. культура и спорт", "Труд и занятость", "Строительство",
    "Общ- полит.вопросы", "Туризм"
]

# Обычные районы (без "НА ПЛАНЕРКУ ГЛАВЫ")
ORDINARY_DISTRICTS = [d for d in DISTRICTS if d != "НА ПЛАНЕРКУ ГЛАВЫ"]

# ============ ФУНКЦИИ ДЛЯ РАБОТЫ С GOOGLE SHEETS ============

def get_current_sheet():
    """Получает текущий месячный лист (создает если нужно)"""
    if not spreadsheet:
        logger.error("❌ Google Sheets не подключена")
        return None
    
    current_month = datetime.now().strftime("%Y-%m")
    
    try:
        # Пытаемся открыть существующий лист
        sheet = spreadsheet.worksheet(current_month)
        logger.info(f"📅 Лист {current_month} найден")
        return sheet
    except Exception:
        try:
            # Создаем новый лист
            logger.info(f"📅 Создаем новый лист: {current_month}")
            sheet = spreadsheet.add_worksheet(
                title=current_month,
                rows=1000,
                cols=20
            )
            
            # Добавляем заголовки
            headers = [
                "Дата и время",
                "Район",
                "Категория обращения",
                "Текст обращения"
            ]
            sheet.append_row(headers)
            
            logger.info(f"✅ Лист {current_month} создан")
            return sheet
        except Exception as e:
            logger.error(f"❌ Ошибка создания листа: {e}")
            return None

def save_to_google_sheets(user_id, district, category, text):
    """Сохраняет обращение в Google Sheets"""
    if not spreadsheet:
        logger.error("❌ Невозможно сохранить: Google Sheets не подключена")
        return False
    
    sheet = get_current_sheet()
    if not sheet:
        logger.error("❌ Невозможно сохранить: лист не доступен")
        return False
    
    try:
        # Подготовка данных
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        row_data = [timestamp, district, category, text]
        
        # Безопасная запись
        with write_lock:
            time.sleep(0.1)  # Небольшая задержка для избежания конфликтов
            sheet.append_row(row_data, value_input_option='USER_ENTERED')
        
        logger.info(f"✅ Данные сохранены: {district} - {category}")
        return True
        
    except Exception as e:
        logger.error(f"❌ Ошибка сохранения в Google Sheets: {e}")
        return False

# ============ ТЕЛЕГРАМ КЛАВИАТУРЫ ============

def create_district_keyboard():
    """Создает клавиатуру с районами (3 кнопки в ряд)"""
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=3)
    
    # Создаем кнопки для всех районов
    buttons = [types.KeyboardButton(district) for district in DISTRICTS]
    
    # Добавляем кнопки группами по 3
    for i in range(0, len(buttons), 3):
        markup.add(*buttons[i:i+3])
    
    return markup

def create_category_keyboard():
    """Создает клавиатуру с категориями (3 кнопки в ряд)"""
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=3)
    
    # Создаем кнопки для всех категорий
    buttons = [types.KeyboardButton(category) for category in CATEGORIES]
    
    # Добавляем кнопки группами по 3
    for i in range(0, len(buttons), 3):
        markup.add(*buttons[i:i+3])
    
    # Добавляем кнопку "Назад" в отдельный ряд
    back_button = types.KeyboardButton("↩️ Назад к выбору района")
    markup.add(back_button)
    
    return markup

# ============ FLASK МАРШРУТЫ ============

@app.route('/')
def index():
    """Главная страница веб-интерфейса"""
    return '''
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>🤖 Telegram Bot для Бурятии</title>
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
            <h1>🤖 Telegram Bot для Бурятии</h1>
            <p>Бот для сбора обращений граждан с автоматической записью в Google Таблицы</p>
            
            <div class="status">
                ✅ <strong>Статус:</strong> Система работает
            </div>
            
            <div class="section">
                <h3>⚙️ Управление ботом</h3>
                <a class="btn" href="/set_webhook">Установить вебхук</a>
                <a class="btn" href="/health">Проверить здоровье</a>
                <a class="btn" href="/bot_info">Информация о боте</a>
            </div>
            
            <div class="section">
                <h3>📊 Диагностика</h3>
                <a class="btn" href="/test_db">Тест базы данных</a>
                <a class="btn" href="/logs">Просмотр логов</a>
                <a class="btn" href="/test_message">Тест сообщения</a>
            </div>
            
            <div class="section">
                <h3>📋 Статистика</h3>
                <p><strong>Районов:</strong> 23 района Бурятии</p>
                <p><strong>Категорий:</strong> 23 категории обращений</p>
                <p><strong>Google Sheets:</strong> {} </p>
                <p><strong>Вебхук:</strong> <code>{}</code></p>
            </div>
            
            <div class="section">
                <h3>🔧 Команды бота</h3>
                <p><strong>/start</strong> - Начать работу с ботом</p>
                <p><strong>/help</strong> - Получить справку</p>
                <p><strong>/stats</strong> - Показать статистику</p>
            </div>
        </div>
    </body>
    </html>
    '''.format(
        "✅ Подключена" if spreadsheet else "❌ Не подключена",
        WEBHOOK_URL + WEBHOOK_PATH
    )

@app.route('/health')
def health_check():
    """Проверка здоровья приложения"""
    try:
        bot_info = bot.get_me()
        return jsonify({
            "status": "ok",
            "bot": bot_info.username,
            "google_sheets": "connected" if spreadsheet else "disconnected",
            "timestamp": datetime.now().isoformat(),
            "webhook_url": WEBHOOK_URL + WEBHOOK_PATH
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/set_webhook')
def set_webhook_route():
    """Устанавливает вебхук для Telegram бота"""
    try:
        # Удаляем старый вебхук
        bot.remove_webhook()
        time.sleep(1)
        
        # Устанавливаем новый вебхук
        webhook_url = f"{WEBHOOK_URL}{WEBHOOK_PATH}"
        logger.info(f"🌐 Устанавливаю вебхук на: {webhook_url}")
        
        result = bot.set_webhook(url=webhook_url)
        
        if result:
            # Получаем информацию о вебхуке
            webhook_info = bot.get_webhook_info()
            
            return f'''
            <h1>✅ Вебхук установлен</h1>
            <p><strong>URL:</strong> {webhook_url}</p>
            <p><strong>Ожидающие обновления:</strong> {webhook_info.pending_update_count}</p>
            <p><strong>Дата установки:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
            <p><a href="/">← Вернуться на главную</a></p>
            '''
        else:
            return "<h1>❌ Не удалось установить вебхук</h1>", 500
            
    except Exception as e:
        logger.error(f"❌ Ошибка установки вебхука: {e}")
        return f"<h1>❌ Ошибка: {str(e)}</h1>", 500

@app.route('/bot_info')
def bot_info():
    """Возвращает информацию о боте"""
    try:
        bot_user = bot.get_me()
        webhook_info = bot.get_webhook_info()
        
        return jsonify({
            "bot": {
                "id": bot_user.id,
                "username": bot_user.username,
                "first_name": bot_user.first_name,
                "is_bot": bot_user.is_bot
            },
            "webhook": {
                "url": webhook_info.url,
                "pending_updates": webhook_info.pending_update_count,
                "last_error_date": webhook_info.last_error_date,
                "last_error_message": webhook_info.last_error_message
            },
            "server": {
                "webhook_path": WEBHOOK_PATH,
                "webhook_url": f"{WEBHOOK_URL}{WEBHOOK_PATH}",
                "timestamp": datetime.now().isoformat()
            }
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/test_db')
def test_db():
    """Тест записи в Google Sheets"""
    try:
        if not spreadsheet:
            return "❌ Google Sheets не подключена"
        
        sheet = get_current_sheet()
        if not sheet:
            return "❌ Не удалось получить лист"
        
        # Тестовые данные
        test_data = [
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "Тестовый район",
            "Тестовая категория",
            f"Тестовое сообщение {datetime.now().strftime('%H:%M:%S')}"
        ]
        
        # Запись в таблицу
        with write_lock:
            sheet.append_row(test_data, value_input_option='USER_ENTERED')
        
        return '''
        <h1>✅ Тест базы данных</h1>
        <p>Тестовая запись успешно добавлена в Google Sheets</p>
        <p><strong>Данные:</strong> {}</p>
        <p><a href="/">← Вернуться на главную</a></p>
        '''.format(test_data)
        
    except Exception as e:
        return f"<h1>❌ Ошибка: {str(e)}</h1>", 500

@app.route('/logs')
def show_logs():
    """Страница просмотра логов"""
    return '''
    <h1>📋 Логи приложения</h1>
    <p>Логи отображаются в реальном времени в панели управления Render:</p>
    <ol>
        <li>Перейдите на <a href="https://dashboard.render.com">Render Dashboard</a></li>
        <li>Выберите сервис "telegram-bot-buryatia2"</li>
        <li>Нажмите вкладку "Logs" в верхнем меню</li>
        <li>Вы увидите все логи приложения в реальном времени</li>
    </ol>
    <p><strong>Последние записи:</strong></p>
    <div style="background: #f0f0f0; padding: 10px; border-radius: 5px; font-family: monospace;">
        Логи загружаются в Render Dashboard...
    </div>
    <p><a href="/">← Вернуться на главную</a></p>
    '''

@app.route('/test_message')
def test_message():
    """Отправка тестового сообщения"""
    try:
        # Проверяем, установлен ли TEST_CHAT_ID
        test_chat_id = os.getenv('TEST_CHAT_ID')
        if not test_chat_id:
            return '''
            <h1>⚠️ TEST_CHAT_ID не установлен</h1>
            <p>Для отправки тестового сообщения добавьте переменную окружения:</p>
            <p><code>TEST_CHAT_ID=ваш_chat_id_в_telegram</code></p>
            <p>Узнать chat_id можно через бота @userinfobot в Telegram</p>
            <p><a href="/">← Вернуться на главную</a></p>
            '''
        
        # Отправляем тестовое сообщение
        bot.send_message(
            test_chat_id,
            "✅ Тестовое сообщение от бота\n\n"
            "Бот работает корректно!\n"
            f"Время: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        
        return f'''
        <h1>✅ Тестовое сообщение отправлено</h1>
        <p>Сообщение успешно отправлено в chat_id: <code>{test_chat_id}</code></p>
        <p><a href="/">← Вернуться на главную</a></p>
        '''
        
    except Exception as e:
        return f"<h1>❌ Ошибка: {str(e)}</h1>", 500

# ============ ОСНОВНОЙ ВЕБХУК ============

@app.route(WEBHOOK_PATH, methods=['POST'])
def webhook():
    """Основной обработчик вебхука от Telegram"""
    if request.headers.get('content-type') == 'application/json':
        try:
            # Получаем и парсим данные от Telegram
            json_string = request.get_data().decode('utf-8')
            update = telebot.types.Update.de_json(json_string)
            
            # Логируем получение обновления
            logger.info(f"📩 Получено обновление #{update.update_id}")
            
            # Обрабатываем обновление
            bot.process_new_updates([update])
            
            return 'OK'
            
        except Exception as e:
            logger.error(f"❌ Ошибка обработки вебхука: {e}")
            return 'Error processing update', 500
    else:
        return 'Invalid content type', 403

# ============ ОБРАБОТЧИКИ ТЕЛЕГРАМ КОМАНД ============

@bot.message_handler(commands=['start', 'help'])
def handle_start(message):
    """Обработчик команд /start и /help"""
    user_id = message.chat.id
    
    # Инициализируем или очищаем данные пользователя
    user_data[user_id] = {}
    
    # Приветственное сообщение
    welcome_text = f"""
👋 {message.from_user.first_name}, добро пожаловать!

Вас приветствует форма обратной связи Бурятия-инфо.24/7.

<b>📋 Как пользоваться:</b>
1️⃣ Выберите район республики
2️⃣ Выберите категорию обращения
3️⃣ Опишите вашу проблему

Ваше обращение будет записано в Google Таблицы для дальнейшей обработки.

<b>📍 Выберите район:</b>
"""
    
    bot.send_message(
        user_id,
        welcome_text,
        parse_mode="HTML",
        reply_markup=create_district_keyboard()
    )

@bot.message_handler(func=lambda message: message.text in ORDINARY_DISTRICTS)
def handle_district(message):
    """Обработчик выбора обычного района"""
    user_id = message.chat.id
    district = message.text
    
    logger.info(f"📍 Пользователь {user_id} выбрал район: {district}")
    
    # Сохраняем район
    user_data[user_id] = {
        'district': district,
        'step': 'category'  # Следующий шаг - выбор категории
    }
    
    bot.send_message(
        user_id,
        f"📍 <b>Вы выбрали район:</b> {district}\n\n"
        f"Теперь выберите категорию обращения:",
        parse_mode="HTML",
        reply_markup=create_category_keyboard()
    )

@bot.message_handler(func=lambda message: message.text == "НА ПЛАНЕРКУ ГЛАВЫ")
def handle_plannerka(message):
    """Обработчик специального варианта 'НА ПЛАНЕРКУ ГЛАВЫ'"""
    user_id = message.chat.id
    
    logger.info(f"📋 Пользователь {user_id} выбрал: НА ПЛАНЕРКУ ГЛАВЫ")
    
    # Сразу устанавливаем категорию "Планерка"
    user_data[user_id] = {
        'district': "НА ПЛАНЕРКУ ГЛАВЫ",
        'category': "Планерка",
        'step': 'text'  # Следующий шаг - ввод текста
    }
    
    bot.send_message(
        user_id,
        f"📍 <b>Вы выбрали:</b> НА ПЛАНЕРКУ ГЛАВЫ\n\n"
        f"Пожалуйста, опишите ваше обращение:",
        parse_mode="HTML",
        reply_markup=types.ReplyKeyboardRemove()
    )

@bot.message_handler(func=lambda message: message.text in CATEGORIES)
def handle_category(message):
    """Обработчик выбора категории"""
    user_id = message.chat.id
    category = message.text
    
    logger.info(f"🏷️ Пользователь {user_id} выбрал категорию: {category}")
    
    # Проверяем, выбрал ли пользователь район
    if user_id not in user_data or 'district' not in user_data[user_id]:
        bot.send_message(
            user_id,
            "⚠️ Сначала выберите район!",
            reply_markup=create_district_keyboard()
        )
        return
    
    # Сохраняем категорию
    user_data[user_id]['category'] = category
    user_data[user_id]['step'] = 'text'  # Следующий шаг - ввод текста
    
    bot.send_message(
        user_id,
        f"🏷️ <b>Вы выбрали категорию:</b> {category}\n\n"
        f"Теперь подробно опишите вашу проблему или обращение:",
        parse_mode="HTML",
        reply_markup=types.ReplyKeyboardRemove()
    )

@bot.message_handler(func=lambda message: message.text == "↩️ Назад к выбору района")
def handle_back(message):
    """Обработчик кнопки 'Назад'"""
    user_id = message.chat.id
    
    logger.info(f"↩️ Пользователь {user_id} вернулся к выбору района")
    
    # Очищаем данные пользователя
    if user_id in user_data:
        user_data[user_id] = {}
    
    bot.send_message(
        user_id,
        "📍 Выберите район республики:",
        reply_markup=create_district_keyboard()
    )

@bot.message_handler(func=lambda message: True, content_types=['text'])
def handle_text(message):
    """Обработчик текстового обращения"""
    user_id = message.chat.id
    
    # Пропускаем команду "Назад"
    if message.text == "↩️ Назад к выбору района":
        return
    
    # Проверяем, ожидаем ли мы текст обращения
    if (user_id in user_data and 
        user_data[user_id].get('step') == 'text' and
        'district' in user_data[user_id] and
        'category' in user_data[user_id]):
        
        user_text = message.text
        district = user_data[user_id]['district']
        category = user_data[user_id]['category']
        
        logger.info(f"📝 Пользователь {user_id} отправил обращение")
        
        # Сохраняем в Google Sheets
        success = save_to_google_sheets(user_id, district, category, user_text)
        
        if success:
            # Успешное сохранение
            response_text = f"""
✅ <b>Спасибо! Ваше обращение записано.</b>

📍 <b>Район:</b> {district}
🏷️ <b>Категория:</b> {category}
📝 <b>Ваше обращение:</b> {user_text}
🕐 <b>Время:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

Для нового обращения выберите район:
"""
        else:
            # Ошибка сохранения
            response_text = """
❌ <b>Произошла ошибка при записи данных.</b>

Пожалуйста, попробуйте еще раз позже или свяжитесь с администратором.
"""
        
        # Отправляем ответ пользователю
        bot.send_message(
            user_id,
            response_text,
            parse_mode="HTML",
            reply_markup=create_district_keyboard() if success else None
        )
        
        # Очищаем данные пользователя
        if user_id in user_data:
            del user_data[user_id]
    
    else:
        # Если пользователь просто написал текст без выбора
        logger.info(f"⚠️ Пользователь {user_id} отправил текст без выбора")
        
        bot.send_message(
            user_id,
            "Пожалуйста, сначала выберите район и категорию обращения.\n\n"
            "Используйте кнопки на клавиатуре.",
            reply_markup=create_district_keyboard()
        )

@bot.message_handler(content_types=['photo', 'video', 'document', 'audio', 'sticker'])
def handle_media(message):
    """Обработчик медиа-сообщений"""
    bot.send_message(
        message.chat.id,
        "📎 Я могу обрабатывать только текстовые сообщения.\n\n"
        "Пожалуйста, выберите район и категорию обращения, "
        "а затем опишите вашу проблему текстом.",
        reply_markup=create_district_keyboard()
    )

# ============ НАСТРОЙКА ВЕБХУКА ПРИ ЗАПУСКЕ ============

def setup_webhook():
    """Автоматическая настройка вебхука при запуске приложения"""
    try:
        logger.info("🌐 Настраиваю вебхук...")
        
        # Удаляем старый вебхук
        bot.remove_webhook()
        time.sleep(2)
        
        # Устанавливаем новый вебхук
        webhook_url = f"{WEBHOOK_URL}{WEBHOOK_PATH}"
        logger.info(f"🌐 Устанавливаю вебхук на: {webhook_url}")
        
        success = bot.set_webhook(url=webhook_url)
        
        if success:
            logger.info("✅ Вебхук успешно установлен")
        else:
            logger.error("❌ Не удалось установить вебхук")
            
    except Exception as e:
        logger.error(f"❌ Ошибка при настройке вебхука: {e}")

# ============ ЗАПУСК ПРИЛОЖЕНИЯ ============

if __name__ == "__main__":
    # Настраиваем вебхук при запуске
    setup_webhook()
    
    # Запускаем Flask приложение
    port = int(os.getenv('PORT', 10000))
    logger.info(f"🚀 Запуск приложения на порту {port}")
    app.run(host='0.0.0.0', port=port, debug=False)
