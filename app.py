import os
import telebot
from telebot import types
import gspread
from datetime import datetime, timedelta
import time
from threading import Lock
from flask import Flask, request
import json
from google.oauth2.service_account import Credentials
import logging
from dotenv import load_dotenv

# Загружаем переменные окружения из .env файла (для локальной разработки)
load_dotenv()

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

# ТОКЕН БЕРЕТСЯ ИЗ ПЕРЕМЕННЫХ ОКРУЖЕНИЯ
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
if not TELEGRAM_TOKEN:
    logger.error("❌ TELEGRAM_TOKEN не установлен в переменных окружения!")
    logger.error("Добавьте TELEGRAM_TOKEN в Render Environment Variables")
    # Для локальной разработки можно раскомментировать строку ниже:
    # TELEGRAM_TOKEN = "ваш_токен_для_локальной_разработки"
    # Но не коммитьте этот токен в репозиторий!

if TELEGRAM_TOKEN:
    bot = telebot.TeleBot(TELEGRAM_TOKEN)
    logger.info("✅ Бот инициализирован с токеном из переменных окружения")
else:
    # Создаем заглушку бота для тестирования без токена
    logger.warning("⚠️ Бот не инициализирован - отсутствует TELEGRAM_TOKEN")
    bot = None

# URL вашего Render приложения
WEBHOOK_URL = os.getenv('RENDER_EXTERNAL_URL', 'https://incident-evai.onrender.com')
WEBHOOK_PATH = '/webhook'

# ============ ПОДКЛЮЧЕНИЕ К GOOGLE SHEETS ============

def init_google_sheets():
    """Инициализация подключения к Google Sheets"""
    try:
        google_creds_json = os.getenv('GOOGLE_CREDENTIALS')
        if google_creds_json:
            # Убираем экранирование
            google_creds_json = google_creds_json.strip().replace('\\n', '\n')
            
            # Если есть внешние кавычки, убираем их
            if google_creds_json.startswith('"') and google_creds_json.endswith('"'):
                google_creds_json = google_creds_json[1:-1]
            
            credentials_dict = json.loads(google_creds_json)
            
            scopes = ['https://www.googleapis.com/auth/spreadsheets']
            credentials = Credentials.from_service_account_info(credentials_dict, scopes=scopes)
            gc = gspread.authorize(credentials)
            logger.info("✅ Google Sheets подключена через переменные окружения")
            
            spreadsheet = gc.open("google-api-sheets-incident")
            logger.info("✅ Таблица открыта")
            return spreadsheet
            
        else:
            # Для локальной разработки
            try:
                gc = gspread.service_account(filename="clever.json")
                spreadsheet = gc.open("google-api-sheets-incident")
                logger.info("✅ Google Sheets подключена через файл clever.json")
                return spreadsheet
            except:
                logger.info("⚠️ GOOGLE_CREDENTIALS не установлен и файл clever.json не найден")
                return None
            
    except Exception as e:
        logger.error(f"❌ Ошибка подключения к Google Sheets: {e}")
        return None

# Инициализируем Google Sheets
spreadsheet = init_google_sheets()

# Хранилище данных пользователей
user_data = {}
write_lock = Lock()

# ============ СПИСКИ ДЛЯ КЛАВИАТУР ============

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
    "Общ- полит.вопросы", "Туризм"
]

ORDINARY_DISTRICTS = [d for d in DISTRICTS if d != "НА ПЛАНЕРКУ ГЛАВЫ"]

# ============ ФУНКЦИИ GOOGLE SHEETS ============

def get_current_sheet():
    """Получает текущий месячный лист"""
    if not spreadsheet:
        logger.info("📝 Используется заглушка Google Sheets")
        return None
    
    current_month = datetime.now().strftime("%Y-%m")
    
    try:
        sheet = spreadsheet.worksheet(current_month)
        return sheet
    except Exception:
        try:
            sheet = spreadsheet.add_worksheet(title=current_month, rows=1000, cols=20)
            sheet.append_row(["Дата и время", "Район", "Категория обращения", "Текст обращения"])
            return sheet
        except Exception as e:
            logger.error(f"Ошибка создания листа: {e}")
            return None

def save_to_sheets(district, category, text):
    """Сохраняет обращение в Google Sheets"""
    try:
        if not spreadsheet:
            # Заглушка для тестирования
            logger.info(f"📝 Тестовая запись: {district}, {category}, {text}")
            return True
        
        sheet = get_current_sheet()
        if not sheet:
            return False
        
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        row_data = [timestamp, district, category, text]
        
        with write_lock:
            sheet.append_row(row_data, value_input_option='USER_ENTERED')
        
        logger.info(f"✅ Данные сохранены в Google Sheets: {district} - {category}")
        return True
    except Exception as e:
        logger.error(f"❌ Ошибка сохранения: {e}")
        return False

# ============ КЛАВИАТУРЫ ============

def create_district_keyboard():
    """Создает клавиатуру с районами"""
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=3)
    
    buttons = []
    for district in DISTRICTS:
        buttons.append(types.KeyboardButton(district))
    
    for i in range(0, len(buttons), 3):
        markup.add(*buttons[i:i+3])
    
    return markup

def create_category_keyboard():
    """Создает клавиатуру с категориями"""
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=3)
    
    buttons = []
    for category in CATEGORIES:
        buttons.append(types.KeyboardButton(category))
    
    for i in range(0, len(buttons), 3):
        markup.add(*buttons[i:i+3])
    
    markup.add(types.KeyboardButton("↩️ Назад к выбору района"))
    
    return markup

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
            .warning {
                background: #ff9800;
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
            
            ''' + (f'''
            <div class="status">
                ✅ <strong>Статус:</strong> Система работает
            </div>
            ''' if bot else '''
            <div class="warning">
                ⚠️ <strong>Статус:</strong> Бот не инициализирован
            </div>
            ''') + '''
            
            <div class="section">
                <h3>⚙️ Управление</h3>
                ''' + ('''
                <a class="btn" href="/set_webhook">Установить вебхук</a>
                <a class="btn" href="/health">Проверить здоровье</a>
                <a class="btn" href="/bot_info">Информация о боте</a>
                ''' if bot else '''
                <p><strong>Для работы бота необходимо:</strong></p>
                <ol>
                    <li>Добавить переменную окружения TELEGRAM_TOKEN в Render</li>
                    <li>Перезапустить приложение</li>
                </ol>
                ''') + '''
            </div>
            
            <div class="section">
                <h3>📊 Статистика</h3>
                <p><strong>Районов:</strong> ''' + str(len(DISTRICTS)) + '''</p>
                <p><strong>Категорий:</strong> ''' + str(len(CATEGORIES)) + '''</p>
                <p><strong>Google Sheets:</strong> ''' + ("✅ Подключена" if spreadsheet else "⚠️ Заглушка") + '''</p>
                <p><strong>Вебхук:</strong> ''' + f'{WEBHOOK_URL}{WEBHOOK_PATH}' + '''</p>
                <p><strong>Токен бота:</strong> ''' + ("✅ Установлен" if TELEGRAM_TOKEN else "❌ Отсутствует") + '''</p>
            </div>
            
            ''' + ('''
            <div class="section">
                <h3>🔧 Использование</h3>
                <ol>
                    <li>Найдите бота @IncidentInfo_bot в Telegram</li>
                    <li>Отправьте команду /start</li>
                    <li>Выберите район → категорию → опишите проблему</li>
                    <li>Данные автоматически сохранятся в Google Таблицы</li>
                </ol>
            </div>
            ''' if bot else '') + '''
        </div>
    </body>
    </html>
    '''

@app.route('/health')
def health_check():
    """Проверка здоровья приложения"""
    return {
        "status": "ok" if bot else "error",
        "bot_initialized": bool(bot),
        "google_sheets": bool(spreadsheet),
        "timestamp": datetime.now().isoformat(),
        "webhook_url": f"{WEBHOOK_URL}{WEBHOOK_PATH}"
    }

@app.route('/set_webhook')
def set_webhook_route():
    """Установка вебхука"""
    if not bot:
        return "<h1>❌ Бот не инициализирован</h1><p>Установите TELEGRAM_TOKEN в переменных окружения</p>", 500
    
    try:
        bot.remove_webhook()
        time.sleep(1)
        
        webhook_url = f"{WEBHOOK_URL}{WEBHOOK_PATH}"
        logger.info(f"🌐 Устанавливаю вебхук на: {webhook_url}")
        
        result = bot.set_webhook(url=webhook_url)
        
        if result:
            webhook_info = bot.get_webhook_info()
            return f'''
            <h1>✅ Вебхук установлен</h1>
            <p><strong>URL:</strong> {webhook_url}</p>
            <p><strong>Статус:</strong> {webhook_info.pending_update_count} ожидающих обновлений</p>
            <p><strong>Для проверки:</strong> Отправьте /start боту @IncidentInfo_bot</p>
            <p><a href="/">← На главную</a></p>
            '''
        else:
            return "<h1>❌ Не удалось установить вебхук</h1>", 500
    except Exception as e:
        logger.error(f"Ошибка установки вебхука: {e}")
        return f"<h1>❌ Ошибка: {str(e)}</h1>", 500

# ============ ВЕБХУК ============

@app.route(WEBHOOK_PATH, methods=['POST'])
def webhook():
    """Обработчик вебхука от Telegram"""
    if not bot:
        return "Bot not initialized", 500
    
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        update = telebot.types.Update.de_json(json_string)
        
        logger.info(f"📩 Получено обновление #{update.update_id}")
        
        bot.process_new_updates([update])
        return ''
    else:
        return 'Invalid content type', 403

# ============ ОБРАБОТЧИКИ ТЕЛЕГРАМ БОТА ============

if bot:
    @bot.message_handler(commands=['start', 'help'])
    def handle_start(message):
        """Обработчик команд /start и /help"""
        logger.info(f"👤 Пользователь {message.chat.id} начал работу")
        
        user_data[message.chat.id] = {}
        
        bot.send_message(
            message.chat.id,
            f"👋 Здравствуйте, {message.from_user.first_name}!\n\n"
            f"Вас приветствует бот для сбора обращений граждан Бурятии.\n\n"
            f"📋 <b>Как это работает:</b>\n"
            f"1. Выберите район из списка\n"
            f"2. Выберите категорию обращения\n"
            f"3. Опишите вашу проблему\n\n"
            f"📊 <b>Все обращения записываются в Google Таблицы</b>\n\n"
            f"📍 <b>Выберите район:</b>",
            parse_mode="HTML",
            reply_markup=create_district_keyboard()
        )
    
    @bot.message_handler(func=lambda message: message.text in DISTRICTS)
    def handle_district(message):
        """Обработчик выбора района"""
        user_id = message.chat.id
        district = message.text
        
        logger.info(f"📍 Пользователь {user_id} выбрал район: {district}")
        
        user_data[user_id] = {'district': district}
        
        bot.send_message(
            user_id,
            f"📍 <b>Вы выбрали район:</b> {district}\n\n"
            f"🏷️ <b>Теперь выберите категорию обращения:</b>",
            parse_mode="HTML",
            reply_markup=create_category_keyboard()
        )
    
    @bot.message_handler(func=lambda message: message.text in CATEGORIES)
    def handle_category(message):
        """Обработчик выбора категории"""
        user_id = message.chat.id
        category = message.text
        
        logger.info(f"🏷️ Пользователь {user_id} выбрал категорию: {category}")
        
        if user_id not in user_data or 'district' not in user_data[user_id]:
            bot.send_message(
                user_id,
                "⚠️ Пожалуйста, сначала выберите район!",
                reply_markup=create_district_keyboard()
            )
            return
        
        user_data[user_id]['category'] = category
        user_data[user_id]['waiting_for_text'] = True
        
        bot.send_message(
            user_id,
            f"🏷️ <b>Вы выбрали категорию:</b> {category}\n\n"
            f"📝 <b>Теперь подробно опишите ваше обращение:</b>\n\n"
            f"<i>Опишите проблему максимально подробно, укажите адрес, если это возможно</i>",
            parse_mode="HTML",
            reply_markup=types.ReplyKeyboardRemove()
        )
    
    @bot.message_handler(func=lambda message: message.text == "↩️ Назад к выбору района")
    def handle_back(message):
        """Обработчик кнопки 'Назад'"""
        user_id = message.chat.id
        
        logger.info(f"↩️ Пользователь {user_id} вернулся к выбору района")
        
        if user_id in user_data:
            user_data[user_id] = {}
        
        bot.send_message(
            user_id,
            "📍 Выберите район:",
            reply_markup=create_district_keyboard()
        )
    
    @bot.message_handler(func=lambda message: True, content_types=['text'])
    def handle_text(message):
        """Обработчик текстового обращения"""
        user_id = message.chat.id
        
        # Пропускаем команду "Назад"
        if message.text == "↩️ Назад к выбору района":
            return
        
        if user_id in user_data and user_data[user_id].get('waiting_for_text'):
            user_text = message.text
            
            logger.info(f"📝 Пользователь {user_id} отправил обращение")
            
            # Сохраняем данные
            district = user_data[user_id]['district']
            category = user_data[user_id]['category']
            
            # Сохраняем в Google Sheets
            success = save_to_sheets(district, category, user_text)
            
            if success:
                response = f"""
✅ <b>Ваше обращение принято и сохранено!</b>

📍 <b>Район:</b> {district}
🏷️ <b>Категория:</b> {category}
📝 <b>Обращение:</b> {user_text}
🕐 <b>Время:</b> {datetime.now().strftime('%d.%m.%Y %H:%M')}

<i>Спасибо за ваше обращение! Оно будет рассмотрено в установленном порядке.</i>

Для нового обращения выберите район:
"""
            else:
                response = """
❌ <b>Произошла ошибка при сохранении обращения.</b>

Пожалуйста, попробуйте еще раз позже или свяжитесь с администратором.

Выберите район для нового обращения:
"""
            
            bot.send_message(
                user_id,
                response,
                parse_mode="HTML",
                reply_markup=create_district_keyboard()
            )
            
            # Очищаем данные пользователя
            if user_id in user_data:
                del user_data[user_id]
        else:
            # Если пользователь просто написал текст
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
            "Пожалуйста, выберите район и категорию, затем опишите ваше обращение текстом.",
            reply_markup=create_district_keyboard()
        )

# ============ ЗАПУСК ============

if __name__ == "__main__":
    if not bot:
        logger.error("❌ Приложение запущено без токена бота!")
        logger.error("Установите переменную окружения TELEGRAM_TOKEN")
    
    # Автоматическая установка вебхука при запуске (только если есть бот)
    if bot:
        try:
            bot.remove_webhook()
            time.sleep(1)
            webhook_url = f"{WEBHOOK_URL}{WEBHOOK_PATH}"
            bot.set_webhook(url=webhook_url)
            logger.info(f"🌐 Вебхук установлен на: {webhook_url}")
        except Exception as e:
            logger.error(f"❌ Ошибка установки вебхука: {e}")
    
    # Запуск Flask приложения
    port = int(os.getenv('PORT', 10000))
    logger.info(f"🚀 Запуск на порту {port}")
    app.run(host='0.0.0.0', port=port)
