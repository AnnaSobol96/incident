import os
import telebot
from telebot import types
from flask import Flask, request, jsonify
import logging

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

app = Flask(__name__)

TELEGRAM_TOKEN = '8313418257:AAGEODG-XWrlq0X0ORc6xH0ggRjvB05WGqQ'
bot = telebot.TeleBot(TELEGRAM_TOKEN)

WEBHOOK_URL = 'https://incident-evai.onrender.com'
WEBHOOK_PATH = '/webhook'

@app.route(WEBHOOK_PATH, methods=['POST'])
def webhook():
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        update = telebot.types.Update.de_json(json_string)
        
        # Если есть сообщение с текстом
        if update.message and update.message.text:
            chat_id = update.message.chat.id
            text = update.message.text
            logger.info(f"Получено сообщение: {text} от {chat_id}")
            
            # Отвечаем
            try:
                bot.send_message(chat_id, f"Вы написали: {text}")
                logger.info(f"Ответ отправлен в {chat_id}")
            except Exception as e:
                logger.error(f"Ошибка при отправке сообщения: {e}")
        
        return ''
    else:
        return 'Invalid content type', 403

@app.route('/set_webhook', methods=['GET'])
def set_webhook():
    bot.remove_webhook()
    bot.set_webhook(url=WEBHOOK_URL + WEBHOOK_PATH)
    return 'Webhook set'

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)
