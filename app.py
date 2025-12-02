import os
import telebot
from telebot import types
from flask import Flask, request
import logging
import time

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# ============ НАСТРОЙКА БОТА ============

# Токен из переменных окружения
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN', '8590157858:AAGVPYg1DHXNQaSbrdce7lfxq-RyMtufi5Y')
bot = telebot.TeleBot(TELEGRAM_TOKEN)
logger.info("✅ Бот инициализирован")

# URL вашего приложения
WEBHOOK_URL = 'https://incident-evai.onrender.com'
WEBHOOK_PATH = '/webhook'

# ============ ПРОСТЫЕ КЛАВИАТУРЫ ============

def get_district_keyboard():
    """Простая клавиатура с районами"""
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=3)
    
    # Несколько тестовых районов
    districts = [
        "Кабанский", "Закаменский", "Бичурский",
        "Кяхтинский", "Муйский", "Курумканский"
    ]
    
    for district in districts:
        keyboard.add(types.KeyboardButton(district))
    
    return keyboard

def get_category_keyboard():
    """Простая клавиатура с категориями"""
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=3)
    
    categories = [
        "Дороги", "Транспорт", "Госуслуги",
        "Благоустройство", "Иное", "Здравоохранение"
    ]
    
    for category in categories:
        keyboard.add(types.KeyboardButton(category))
    
    keyboard.add(types.KeyboardButton("↩️ Назад"))
    
    return keyboard

# ============ ПРОСТЫЕ FLASK РОУТЫ ============

@app.route('/')
def index():
    return '''
    <h1>🤖 Тестовый бот Бурятия</h1>
    <p>Бот в тестовом режиме</p>
    <p><a href="/set_webhook">Установить вебхук</a></p>
    <p><a href="/test">Проверить бота</a></p>
    <p><strong>Токен:</strong> Установлен</p>
    '''

@app.route('/set_webhook')
def set_webhook():
    try:
        # Удаляем старый вебхук
        bot.remove_webhook()
        time.sleep(1)
        
        # Устанавливаем новый
        webhook_url = f"{WEBHOOK_URL}{WEBHOOK_PATH}"
        result = bot.set_webhook(url=webhook_url)
        
        if result:
            # Проверяем установку
            webhook_info = bot.get_webhook_info()
            return f'''
            <h1>✅ Вебхук установлен!</h1>
            <p>URL: {webhook_url}</p>
            <p>Ожидающие обновления: {webhook_info.pending_update_count}</p>
            <p><strong>Теперь отправьте /start боту @IncidentInfo_bot</strong></p>
            '''
        else:
            return "<h1>❌ Не удалось установить вебхук</h1>"
            
    except Exception as e:
        return f"<h1>❌ Ошибка: {str(e)}</h1>"

@app.route('/test')
def test_bot():
    """Проверка работы бота"""
    try:
        bot_info = bot.get_me()
        webhook_info = bot.get_webhook_info()
        
        return f'''
        <h1>🤖 Проверка бота</h1>
        <p>Имя бота: {bot_info.first_name}</p>
        <p>Username: @{bot_info.username}</p>
        <p>ID: {bot_info.id}</p>
        <p>Вебхук: {webhook_info.url}</p>
        <p>Статус вебхука: {webhook_info.pending_update_count} ожидающих</p>
        <p><strong>Если вебхук не установлен - перейдите на /set_webhook</strong></p>
        '''
    except Exception as e:
        return f"<h1>❌ Ошибка: {str(e)}</h1>"

# ============ ОСНОВНОЙ ВЕБХУК ============

@app.route(WEBHOOK_PATH, methods=['POST'])
def webhook():
    """Обработчик вебхука"""
    if request.headers.get('content-type') == 'application/json':
        try:
            # Получаем данные
            json_string = request.get_data().decode('utf-8')
            logger.info("📩 Получено сообщение от Telegram")
            
            # Обрабатываем через telebot
            update = telebot.types.Update.de_json(json_string)
            bot.process_new_updates([update])
            
            return 'OK'
        except Exception as e:
            logger.error(f"Ошибка в вебхуке: {e}")
            return 'Error', 500
    return 'Invalid content type', 403

# ============ ПРОСТЫЕ ОБРАБОТЧИКИ БОТА ============

# Словарь для хранения состояния пользователей
user_states = {}

@bot.message_handler(commands=['start', 'help'])
def handle_start(message):
    """Обработчик /start"""
    logger.info(f"Пользователь {message.chat.id} начал работу")
    
    # Сохраняем начальное состояние
    user_states[message.chat.id] = {'step': 'district'}
    
    bot.send_message(
        message.chat.id,
        f"👋 Привет, {message.from_user.first_name}!\n\n"
        "Я бот для сбора обращений по Бурятии.\n\n"
        "📍 <b>Выберите район:</b>",
        parse_mode="HTML",
        reply_markup=get_district_keyboard()
    )

@bot.message_handler(func=lambda message: True)
def handle_all_messages(message):
    """Обработчик всех сообщений"""
    chat_id = message.chat.id
    text = message.text
    
    logger.info(f"Сообщение от {chat_id}: {text}")
    
    # Если это районы
    districts = ["Кабанский", "Закаменский", "Бичурский", 
                 "Кяхтинский", "Муйский", "Курумканский"]
    
    categories = ["Дороги", "Транспорт", "Госуслуги", 
                  "Благоустройство", "Иное", "Здравоохранение"]
    
    if text in districts:
        # Пользователь выбрал район
        user_states[chat_id] = {
            'step': 'category',
            'district': text
        }
        
        bot.send_message(
            chat_id,
            f"📍 <b>Район:</b> {text}\n\n"
            "🏷️ <b>Выберите категорию:</b>",
            parse_mode="HTML",
            reply_markup=get_category_keyboard()
        )
    
    elif text in categories:
        # Пользователь выбрал категорию
        if chat_id in user_states and 'district' in user_states[chat_id]:
            district = user_states[chat_id]['district']
            user_states[chat_id]['category'] = text
            user_states[chat_id]['step'] = 'text'
            
            bot.send_message(
                chat_id,
                f"🏷️ <b>Категория:</b> {text}\n\n"
                "📝 <b>Опишите ваше обращение:</b>",
                parse_mode="HTML",
                reply_markup=types.ReplyKeyboardRemove()
            )
        else:
            bot.send_message(
                chat_id,
                "Сначала выберите район!",
                reply_markup=get_district_keyboard()
            )
    
    elif text == "↩️ Назад":
        # Возврат к выбору района
        user_states[chat_id] = {'step': 'district'}
        bot.send_message(
            chat_id,
            "📍 Выберите район:",
            reply_markup=get_district_keyboard()
        )
    
    else:
        # Текстовое обращение или неизвестная команда
        if chat_id in user_states and user_states[chat_id].get('step') == 'text':
            # Пользователь отправляет текст обращения
            if 'district' in user_states[chat_id] and 'category' in user_states[chat_id]:
                district = user_states[chat_id]['district']
                category = user_states[chat_id]['category']
                
                bot.send_message(
                    chat_id,
                    f"✅ <b>Спасибо! Ваше обращение получено:</b>\n\n"
                    f"📍 Район: {district}\n"
                    f"🏷️ Категория: {category}\n"
                    f"📝 Текст: {text}\n\n"
                    "Для нового обращения отправьте /start",
                    parse_mode="HTML",
                    reply_markup=types.ReplyKeyboardRemove()
                )
                
                # Очищаем состояние
                user_states.pop(chat_id, None)
            else:
                bot.send_message(
                    chat_id,
                    "Что-то пошло не так. Отправьте /start",
                    reply_markup=types.ReplyKeyboardRemove()
                )
        else:
            # Простое сообщение
            bot.send_message(
                chat_id,
                "Для начала работы отправьте /start",
                reply_markup=get_district_keyboard()
            )

# ============ ЗАПУСК ============

if __name__ == "__main__":
    logger.info("🚀 Запуск бота...")
    
    # Пытаемся установить вебхук при запуске
    try:
        bot.remove_webhook()
        time.sleep(2)
        
        webhook_url = f"{WEBHOOK_URL}{WEBHOOK_PATH}"
        logger.info(f"Устанавливаю вебхук: {webhook_url}")
        
        success = bot.set_webhook(url=webhook_url)
        
        if success:
            logger.info("✅ Вебхук установлен")
        else:
            logger.error("❌ Не удалось установить вебхук")
            
    except Exception as e:
        logger.error(f"Ошибка установки вебхука: {e}")
    
    # Запускаем Flask
    port = int(os.getenv('PORT', 10000))
    logger.info(f"Запуск на порту {port}")
    app.run(host='0.0.0.0', port=port)
