import os
import telebot
from telebot import types
from flask import Flask, request
import logging
import json

# Настройка подробного логирования
logging.basicConfig(
    level=logging.DEBUG,  # Изменено на DEBUG для подробных логов
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# ============ КОНФИГУРАЦИЯ ============

TELEGRAM_TOKEN = '8313418257:AAGEODG-XWrlq0X0ORc6xH0ggRjvB05WGqQ'
bot = telebot.TeleBot(TELEGRAM_TOKEN)
logger.info("✅ Бот инициализирован")

WEBHOOK_URL = 'https://incident-evai.onrender.com'
WEBHOOK_PATH = '/webhook'

# ============ FLASK РОУТЫ ============

@app.route('/')
def index():
    return '''
    <h1>🤖 Telegram Bot</h1>
    <p><a href="/set_webhook">Установить вебхук</a></p>
    <p><a href="/test">Проверить бота</a></p>
    <p><a href="/debug">Debug лог</a></p>
    '''

@app.route('/set_webhook')
def set_webhook_route():
    try:
        bot.remove_webhook()
        webhook_url = f"{WEBHOOK_URL}{WEBHOOK_PATH}"
        result = bot.set_webhook(url=webhook_url)
        return f'<h1>✅ Вебхук установлен: {webhook_url}</h1>'
    except Exception as e:
        return f'<h1>❌ Ошибка: {str(e)}</h1>', 500

@app.route('/test')
def test():
    try:
        bot_info = bot.get_me()
        webhook_info = bot.get_webhook_info()
        return f'''
        <h1>🤖 Информация о боте</h1>
        <p>Имя: {bot_info.first_name}</p>
        <p>Username: @{bot_info.username}</p>
        <p>Вебхук: {webhook_info.url}</p>
        <p>Ожидающие: {webhook_info.pending_update_count}</p>
        '''
    except Exception as e:
        return f'<h1>❌ Ошибка: {str(e)}</h1>', 500

@app.route('/debug')
def debug():
    """Показать последние логовые записи"""
    return '''
    <h1>🐛 Debug информация</h1>
    <p>Логи отображаются в Render Dashboard</p>
    <p>Проверьте вкладку Logs в панели управления Render</p>
    <p><a href="/">← На главную</a></p>
    '''

# ============ ВЕБХУК С ДЕТАЛЬНЫМ ЛОГИРОВАНИЕМ ============

@app.route(WEBHOOK_PATH, methods=['POST'])
def webhook():
    """Основной обработчик вебхука"""
    if request.headers.get('content-type') == 'application/json':
        try:
            # Получаем сырые данные
            raw_data = request.get_data().decode('utf-8')
            logger.debug(f"📨 Сырые данные от Telegram: {raw_data[:500]}...")
            
            # Парсим JSON
            update_data = json.loads(raw_data)
            logger.info(f"📩 Получено обновление #{update_data.get('update_id')}")
            
            # Логируем тип обновления
            if 'message' in update_data:
                message = update_data['message']
                chat_id = message.get('chat', {}).get('id')
                text = message.get('text', '')
                logger.info(f"💬 Сообщение от chat_id={chat_id}: {text}")
                
                # Если это команда
                if text and text.startswith('/'):
                    logger.info(f"🚀 Команда обнаружена: {text}")
            
            # Создаем объект Update и обрабатываем
            update = telebot.types.Update.de_json(raw_data)
            logger.debug(f"🔄 Обрабатываю обновление через telebot...")
            
            # Обрабатываем обновление
            bot.process_new_updates([update])
            logger.debug("✅ Обновление обработано")
            
            return 'OK'
            
        except json.JSONDecodeError as e:
            logger.error(f"❌ Ошибка парсинга JSON: {e}")
            logger.error(f"Полученные данные: {raw_data[:500]}")
            return 'JSON Error', 400
        except Exception as e:
            logger.error(f"❌ Ошибка в вебхуке: {e}", exc_info=True)
            return 'Error', 500
    else:
        logger.warning("⚠️ Неверный content-type")
        return 'Invalid content type', 403

# ============ ОБРАБОТЧИКИ С ДЕТАЛЬНЫМ ЛОГИРОВАНИЕМ ============

@bot.message_handler(commands=['start', 'help'])
def handle_start(message):
    """Обработчик /start и /help"""
    try:
        logger.info(f"🎯 Обработчик /start вызван для chat_id={message.chat.id}")
        logger.info(f"👤 Пользователь: {message.from_user.first_name} ({message.from_user.id})")
        
        response_text = f"""
👋 Привет, {message.from_user.first_name}!

Я бот для сбора обращений по Бурятии.

📋 Доступные команды:
/start - Начать работу
/help - Помощь
/test - Тестовая команда

Просто отправьте мне сообщение, и я отвечу!
"""
        
        logger.debug(f"📤 Отправляю ответ в chat_id={message.chat.id}")
        bot.reply_to(message, response_text)
        logger.info(f"✅ Ответ отправлен в chat_id={message.chat.id}")
        
    except Exception as e:
        logger.error(f"❌ Ошибка в обработчике /start: {e}", exc_info=True)

@bot.message_handler(commands=['test'])
def handle_test(message):
    """Обработчик /test"""
    try:
        logger.info(f"🧪 Команда /test от chat_id={message.chat.id}")
        bot.reply_to(message, "✅ Тест пройден! Бот работает корректно.")
        logger.info(f"✅ Ответ на /test отправлен")
    except Exception as e:
        logger.error(f"❌ Ошибка в обработчике /test: {e}")

@bot.message_handler(func=lambda message: True)
def handle_all_messages(message):
    """Обработчик всех сообщений"""
    try:
        logger.info(f"📝 Текстовое сообщение от chat_id={message.chat.id}: {message.text}")
        
        response = f"""
📝 Вы написали: {message.text}

✅ Бот получил ваше сообщение!

Если вы хотите отправить обращение:
1. Используйте команду /start
2. Следуйте инструкциям бота

Для помощи используйте /help
"""
        
        logger.debug(f"📤 Отправляю ответ на сообщение в chat_id={message.chat.id}")
        bot.reply_to(message, response)
        logger.info(f"✅ Ответ на сообщение отправлен в chat_id={message.chat.id}")
        
    except Exception as e:
        logger.error(f"❌ Ошибка в обработчике сообщений: {e}", exc_info=True)

# ============ ОБРАБОТЧИК ДЛЯ ЛЮБЫХ ОШИБОК В БОТЕ ============

@bot.message_handler(content_types=['text', 'photo', 'document', 'audio', 'video', 'voice', 'sticker', 'location', 'contact'])
def handle_all_content(message):
    """Резервный обработчик для всего"""
    try:
        if message.content_type != 'text':
            logger.info(f"📎 {message.content_type} от chat_id={message.chat.id}")
            bot.reply_to(message, f"📎 Я получил ваш {message.content_type}. Для работы используйте текстовые сообщения.")
    except Exception as e:
        logger.error(f"❌ Ошибка в резервном обработчике: {e}")

# ============ ЗАПУСК ============

def setup_bot():
    """Настройка бота при запуске"""
    try:
        logger.info("🚀 Настройка бота...")
        
        # Получаем информацию о боте
        bot_info = bot.get_me()
        logger.info(f"🤖 Бот: @{bot_info.username} ({bot_info.first_name})")
        
        # Устанавливаем вебхук
        bot.remove_webhook()
        import time
        time.sleep(1)
        
        webhook_url = f"{WEBHOOK_URL}{WEBHOOK_PATH}"
        success = bot.set_webhook(url=webhook_url)
        
        if success:
            logger.info(f"🌐 Вебхук установлен: {webhook_url}")
            
            # Проверяем вебхук
            webhook_info = bot.get_webhook_info()
            logger.info(f"📊 Статус вебхука: {webhook_info.pending_update_count} ожидающих обновлений")
        else:
            logger.error("❌ Не удалось установить вебхук")
            
    except Exception as e:
        logger.error(f"❌ Ошибка при настройке бота: {e}", exc_info=True)

if __name__ == "__main__":
    # Настраиваем бота при запуске
    setup_bot()
    
    # Запускаем Flask
    port = int(os.getenv('PORT', 10000))
    logger.info(f"🚀 Запуск Flask на порту {port}")
    app.run(host='0.0.0.0', port=port)
