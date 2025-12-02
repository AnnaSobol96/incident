import os
import requests
from flask import Flask, request, jsonify
import logging
import json

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# ============ КОНФИГУРАЦИЯ ============

# Токен вашего бота
TELEGRAM_TOKEN = '8590157858:AAGVPYg1DHXNQaSbrdce7lfxq-RyMtufi5Y'
TELEGRAM_API_URL = f'https://api.telegram.org/bot{TELEGRAM_TOKEN}'

# URL вашего приложения
WEBHOOK_URL = 'https://incident-evai.onrender.com'
WEBHOOK_PATH = '/webhook'

# ============ ФУНКЦИИ ДЛЯ РАБОТЫ С TELEGRAM API ============

def send_message(chat_id, text, reply_markup=None):
    """Отправка сообщения через Telegram API"""
    url = f'{TELEGRAM_API_URL}/sendMessage'
    data = {
        'chat_id': chat_id,
        'text': text,
        'parse_mode': 'HTML'
    }
    
    if reply_markup:
        data['reply_markup'] = json.dumps(reply_markup)
    
    try:
        response = requests.post(url, json=data)
        logger.info(f"📤 Отправлено сообщение в {chat_id}: {response.status_code}")
        return response.json()
    except Exception as e:
        logger.error(f"❌ Ошибка отправки: {e}")
        return None

def get_district_keyboard():
    """Клавиатура с районами"""
    return {
        'keyboard': [
            [
                {'text': 'Кабанский'}, {'text': 'Закаменский'}, {'text': 'Бичурский'}
            ],
            [
                {'text': 'Кяхтинский'}, {'text': 'Муйский'}, {'text': 'Курумканский'}
            ],
            [
                {'text': 'Мухоршибирский'}, {'text': 'Тарбагатайский'}, {'text': 'Тункинский'}
            ],
            [
                {'text': 'НА ПЛАНЕРКУ ГЛАВЫ'}
            ]
        ],
        'resize_keyboard': True,
        'one_time_keyboard': False
    }

def get_category_keyboard():
    """Клавиатура с категориями"""
    return {
        'keyboard': [
            [
                {'text': 'Дороги'}, {'text': 'Транспорт'}, {'text': 'Госуслуги'}
            ],
            [
                {'text': 'Благоустройство'}, {'text': 'Иное'}, {'text': 'Здравоохранение'}
            ],
            [
                {'text': '↩️ Назад к выбору района'}
            ]
        ],
        'resize_keyboard': True,
        'one_time_keyboard': False
    }

# Хранилище состояния пользователей
user_data = {}

# ============ FLASK РОУТЫ ============

@app.route('/')
def index():
    return '''
    <h1>🤖 Бот для обращений Бурятия</h1>
    <p>Бот использует прямое Telegram API</p>
    <p><a href="/set_webhook">Установить вебхук через API</a></p>
    <p><a href="/check_bot">Проверить бота</a></p>
    <p><strong>Статус:</strong> ✅ Работает через прямое API</p>
    '''

@app.route('/set_webhook')
def set_webhook():
    """Установка вебхука через прямое API"""
    try:
        # Удаляем старый вебхук
        requests.get(f'{TELEGRAM_API_URL}/deleteWebhook')
        
        # Устанавливаем новый
        response = requests.post(
            f'{TELEGRAM_API_URL}/setWebhook',
            json={'url': f'{WEBHOOK_URL}{WEBHOOK_PATH}'}
        )
        
        result = response.json()
        
        return f'''
        <h1>✅ Вебхук установлен через API</h1>
        <p>Результат: {result}</p>
        <p><a href="/check_webhook">Проверить вебхук</a></p>
        <p>Теперь отправьте /start боту @IncidentInfo_bot</p>
        '''
    except Exception as e:
        return f'<h1>❌ Ошибка: {str(e)}</h1>', 500

@app.route('/check_bot')
def check_bot():
    """Проверка информации о боте"""
    try:
        response = requests.get(f'{TELEGRAM_API_URL}/getMe')
        bot_info = response.json()
        
        return f'''
        <h1>🤖 Информация о боте</h1>
        <pre>{json.dumps(bot_info, indent=2, ensure_ascii=False)}</pre>
        <p><a href="/">← На главную</a></p>
        '''
    except Exception as e:
        return f'<h1>❌ Ошибка: {str(e)}</h1>', 500

@app.route('/check_webhook')
def check_webhook():
    """Проверка статуса вебхука"""
    try:
        response = requests.get(f'{TELEGRAM_API_URL}/getWebhookInfo')
        webhook_info = response.json()
        
        return f'''
        <h1>🌐 Статус вебхука</h1>
        <pre>{json.dumps(webhook_info, indent=2, ensure_ascii=False)}</pre>
        <p><a href="/">← На главную</a></p>
        '''
    except Exception as e:
        return f'<h1>❌ Ошибка: {str(e)}</h1>', 500

# ============ ОСНОВНОЙ ВЕБХУК ============

@app.route(WEBHOOK_PATH, methods=['POST'])
def webhook():
    """Основной обработчик вебхука через прямое API"""
    try:
        # Получаем данные от Telegram
        data = request.get_json()
        logger.info(f"📩 Получены данные: {json.dumps(data, indent=2)[:500]}...")
        
        # Проверяем, что это сообщение
        if 'message' in data:
            message = data['message']
            chat_id = message['chat']['id']
            text = message.get('text', '')
            user_id = message['from']['id']
            
            logger.info(f"💬 Сообщение от {user_id} (chat_id: {chat_id}): {text}")
            
            # Обработка команды /start
            if text == '/start' or text == '/start@IncidentInfo_bot':
                # Приветственное сообщение
                welcome_text = f"""
👋 Здравствуйте, {message['from'].get('first_name', 'пользователь')}!

Я бот для сбора обращений по Бурятии.

📍 <b>Выберите район:</b>
"""
                send_message(chat_id, welcome_text, get_district_keyboard())
                
                # Сбрасываем состояние пользователя
                user_data[chat_id] = {'step': 'district'}
            
            # Обработка кнопки "НА ПЛАНЕРКУ ГЛАВЫ"
            elif text == 'НА ПЛАНЕРКУ ГЛАВЫ':
                user_data[chat_id] = {
                    'district': 'НА ПЛАНЕРКУ ГЛАВЫ',
                    'category': 'Планерка',
                    'step': 'text'
                }
                
                send_message(
                    chat_id,
                    "📍 <b>Вы выбрали: НА ПЛАНЕРКУ ГЛАВЫ</b>\n\n"
                    "📝 <b>Пожалуйста, опишите ваше обращение:</b>",
                    {'remove_keyboard': True}
                )
            
            # Обработка выбора обычного района
            elif text in ['Кабанский', 'Закаменский', 'Бичурский', 'Кяхтинский', 
                          'Муйский', 'Курумканский', 'Мухоршибирский', 
                          'Тарбагатайский', 'Тункинский']:
                
                user_data[chat_id] = {
                    'district': text,
                    'step': 'category'
                }
                
                send_message(
                    chat_id,
                    f"📍 <b>Вы выбрали район:</b> {text}\n\n"
                    "🏷️ <b>Теперь выберите категорию обращения:</b>",
                    get_category_keyboard()
                )
            
            # Обработка выбора категории
            elif text in ['Дороги', 'Транспорт', 'Госуслуги', 'Благоустройство', 
                          'Иное', 'Здравоохранение']:
                
                if chat_id in user_data and user_data[chat_id].get('step') == 'category':
                    user_data[chat_id]['category'] = text
                    user_data[chat_id]['step'] = 'text'
                    
                    send_message(
                        chat_id,
                        f"🏷️ <b>Вы выбрали категорию:</b> {text}\n\n"
                        "📝 <b>Теперь подробно опишите ваше обращение:</b>",
                        {'remove_keyboard': True}
                    )
                else:
                    send_message(
                        chat_id,
                        "⚠️ Сначала выберите район!",
                        get_district_keyboard()
                    )
            
            # Обработка кнопки "Назад"
            elif text == '↩️ Назад к выбору района':
                user_data[chat_id] = {'step': 'district'}
                send_message(
                    chat_id,
                    "📍 <b>Выберите район:</b>",
                    get_district_keyboard()
                )
            
            # Обработка текстового обращения
            elif chat_id in user_data and user_data[chat_id].get('step') == 'text':
                district = user_data[chat_id].get('district', 'Не указан')
                category = user_data[chat_id].get('category', 'Не указана')
                
                # Формируем ответ
                response_text = f"""
✅ <b>Ваше обращение принято!</b>

📍 <b>Район:</b> {district}
🏷️ <b>Категория:</b> {category}
📝 <b>Ваш текст:</b> {text}

<i>Спасибо за обращение! Оно будет рассмотрено.</i>

Для нового обращения отправьте /start
"""
                
                send_message(
                    chat_id,
                    response_text,
                    {'remove_keyboard': True}
                )
                
                # Очищаем данные пользователя
                if chat_id in user_data:
                    del user_data[chat_id]
            
            # Обработка любого другого текста
            elif text and not text.startswith('/'):
                send_message(
                    chat_id,
                    "Для начала работы отправьте /start",
                    get_district_keyboard()
                )
        
        return jsonify({'ok': True})
        
    except Exception as e:
        logger.error(f"❌ Ошибка в вебхуке: {e}", exc_info=True)
        return jsonify({'ok': False, 'error': str(e)}), 500

# ============ ЗАПУСК ============

if __name__ == '__main__':
    logger.info("🚀 Запуск приложения с прямым Telegram API...")
    
    # Автоматически устанавливаем вебхук при запуске
    try:
        # Удаляем старый вебхук
        requests.get(f'{TELEGRAM_API_URL}/deleteWebhook')
        
        # Устанавливаем новый
        response = requests.post(
            f'{TELEGRAM_API_URL}/setWebhook',
            json={'url': f'{WEBHOOK_URL}{WEBHOOK_PATH}'}
        )
        
        if response.json().get('ok'):
            logger.info("✅ Вебхук установлен автоматически")
        else:
            logger.error(f"❌ Ошибка установки вебхука: {response.json()}")
    except Exception as e:
        logger.error(f"❌ Ошибка при установке вебхука: {e}")
    
    # Запускаем Flask
    port = int(os.getenv('PORT', 10000))
    logger.info(f"🚀 Запуск на порту {port}")
    app.run(host='0.0.0.0', port=port)
