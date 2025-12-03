def init_google_sheets():
    """Инициализация Google Sheets"""
    try:
        google_creds_json = os.getenv('GOOGLE_CREDENTIALS')
        
        if not google_creds_json:
            logger.warning("⚠️ GOOGLE_CREDENTIALS не установлен, используется заглушка")
            return None
        
        logger.info("🔧 Начинаем инициализацию Google Sheets...")
        
        # Очищаем JSON - удаляем пробелы в начале и конце
        google_creds_json = google_creds_json.strip()
        
        # Удаляем возможные лишние кавычки (если вся строка в кавычках)
        if google_creds_json.startswith('"') and google_creds_json.endswith('"'):
            google_creds_json = google_creds_json[1:-1]
            logger.info("✅ Удалил внешние кавычки")
        
        # Пробуем загрузить JSON
        try:
            credentials_dict = json.loads(google_creds_json)
            logger.info("✅ JSON успешно загружен и распарсен")
        except json.JSONDecodeError as e:
            logger.error(f"❌ Ошибка декодирования JSON: {e}")
            logger.error(f"🔍 Позиция ошибки: {e.pos}")
            # Выводим контекст вокруг ошибки
            start = max(0, e.pos - 50)
            end = min(len(google_creds_json), e.pos + 50)
            logger.error(f"📜 Текст вокруг ошибки (позиция {e.pos}): ...{google_creds_json[start:end]}...")
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
        return None
