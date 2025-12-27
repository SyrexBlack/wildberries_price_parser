import pandas as pd
from curl_cffi import requests as crequests
from playwright.sync_api import sync_playwright
import time
import os

# --- 1. АВТО-ДОБЫЧА ТОКЕНОВ (РЕЖИМ НЕВИДИМКИ) ---
def get_fresh_credentials():
    # Путь к профилю
    user_data_dir = os.path.join(os.getcwd(), 'wb_browser_profile')
    
    print(f"🕵️‍♂️ Запускаем Edge в режиме НЕВИДИМКИ...")
    print("⚠️ ПЕРЕД ЗАПУСКОМ ЗАКРОЙ ВСЕ ОКНА EDGE!")

    with sync_playwright() as p:
        # Аргументы для скрытия автоматизации
        args = [
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-infobars",
            "--window-position=0,0",
            "--ignore-certificate-errors",
            "--disable-renderer-backgrounding",
            "--disable-background-timer-throttling",
            "--disable-backgrounding-occluded-windows",
            "--disable-breakpad",
            "--disable-component-extensions-with-background-pages",
            "--disable-extensions",
            "--disable-features=TranslateUI",
            "--disable-ipc-flooding-protection",
            "--disable-renderer-backgrounding",
            "--enable-features=NetworkService,NetworkServiceInProcess",
            "--force-color-profile=srgb",
            "--hide-scrollbars",
            "--metrics-recording-only",
            "--mute-audio"
        ]

        # Запускаем с твоим профилем
        context = p.chromium.launch_persistent_context(
            user_data_dir=user_data_dir,
            channel="msedge",
            headless=False, 
            args=args,
            viewport=None, # Используем реальное разрешение окна
            ignore_default_args=["--enable-automation"], # Убирает плашку "Управляется ПО"
        )
        
        page = context.pages[0]

        # --- СКРЫВАЕМ WEBDRAIVER (ГЛАВНАЯ ЗАЩИТА) ---
        page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
        """)

        captured_headers = {}
        captured_cookies = {}
        found_flag = False

        # Ловим заголовки
        def handle_request(request):
            nonlocal found_flag, captured_headers
            # Ловим ВООБЩЕ ВСЁ, где есть авторизация
            if "wb.ru" in request.url and not found_flag:
                headers = request.headers
                # Ищем Authorization
                if 'authorization' in headers and len(headers['authorization']) > 20:
                    captured_headers = headers
                    found_flag = True
                    print(f"\n🔓 ПОЙМАЛ! Токен из запроса: {request.url[:40]}...")

        page.on("request", handle_request)

        try:
            print("🌍 Открываем Wildberries...")
            page.goto("https://www.wildberries.ru", timeout=90000)
            
            print("\n" + "="*50)
            print("👉 ИНСТРУКЦИЯ:")
            print("1. Если товары не грузятся -> НАЖМИ F5 (Обновить страницу)!")
            print("2. Если не вошел -> Войди в аккаунт.")
            print("3. Сделай любое действие: кликни на 'Каталог' или в поиск.")
            print("="*50 + "\n")

            # Ждем токенов
            for i in range(120):
                if found_flag:
                    print("✅ Токены успешно перехвачены! Закрываю браузер...")
                    time.sleep(2)
                    break
                
                # Если 10 секунд нет токенов - пробуем сами перейти в каталог
                if i == 10 and not found_flag:
                    print("🤖 Скрипт пробует сам кликнуть 'Хиты продаж'...")
                    try: page.click("text=Хиты продаж", timeout=2000)
                    except: pass
                
                time.sleep(1)
                print(f"⏳ Жду активности сети... {120-i} сек", end='\r')

            # Сохраняем куки
            cookies_list = context.cookies()
            captured_cookies = {cookie['name']: cookie['value'] for cookie in cookies_list}

        except Exception as e:
            print(f"⚠️ Ошибка: {e}")
        
        finally:
            context.close()

        if not captured_headers:
            print("\n❌ Не удалось поймать токен. Попробуй обновить страницу вручную во время работы.")
            return {}, {}

        clean_headers = {
            'Accept': '*/*',
            'Accept-Language': 'ru,en;q=0.9',
            'Origin': 'https://www.wildberries.ru',
            'Authorization': captured_headers.get('authorization', ''),
            'x-userid': captured_headers.get('x-userid', ''), # Если его нет, не страшно
            'User-Agent': captured_headers.get('user-agent', 'Mozilla/5.0')
        }

        return captured_cookies, clean_headers

# --- 2. ПАРСЕР (ПРОДАВЕЦ) ---
def parse_seller(seller_id, cookies, headers):
    url = 'https://www.wildberries.ru/__internal/catalog/sellers/v4/catalog'
    headers['Referer'] = f'https://www.wildberries.ru/seller/{seller_id}'

    params = {
        'ab_testing': ['false', 'false'],
        'appType': '1', 
        'curr': 'rub',
        'dest': '-1257786',
        'lang': 'ru',
        'sort': 'rate',
        'spp': '30',
        'supplier': str(seller_id),
        'uclusters': '2',
    }

    seller_products = []
    page = 1
    
    print(f"\n🚀 Парсим продавца {seller_id}...")

    while True:
        current_params = params.copy()
        current_params['page'] = str(page)
        
        try:
            response = crequests.get(
                url, 
                params=current_params, 
                cookies=cookies, 
                headers=headers,
                impersonate="chrome120",
                timeout=15
            )

            if response.status_code == 200:
                data = response.json()
                products = data.get('data', {}).get('products')
                if not products: products = data.get('products', [])

                if not products: break 
                
                print(f"  -> Страница {page}: +{len(products)} товаров")

                for p in products:
                    price = p.get('salePriceU', 0) / 100
                    if price == 0: price = p.get('priceU', 0) / 100
                    if price == 0 and 'sizes' in p and len(p['sizes']) > 0:
                        try: price = p['sizes'][0]['price']['product'] / 100
                        except: pass

                    seller_products.append({
                        'Seller ID': seller_id,
                        'ID': p.get('id'),
                        'Бренд': p.get('brand'),
                        'Название': p.get('name'),
                        'Цена': price,
                        'Рейтинг': p.get('rating'),
                        'Ссылка': f"https://www.wildberries.ru/catalog/{p.get('id')}/detail.aspx",
                    })
                
                if len(products) < 100: break
                page += 1
                time.sleep(1) 
            else:
                print(f"❌ Ошибка API: {response.status_code}")
                break

        except Exception as e:
            print(f"Сбой: {e}")
            break
            
    return seller_products

# --- 3. АНАЛИТИКА ---
def analyze_deals(products_list):
    if not products_list: return None
    df = pd.DataFrame(products_list)
    df['Медиана (расч.)'] = (df['Цена'] * 1.15).astype(int)
    df['Отклонение %'] = ((df['Медиана (расч.)'] - df['Цена']) / df['Медиана (расч.)'] * 100).round(1)
    
    def discount_group(val):
        if val >= 30: return "🔥 30%+"
        elif val >= 20: return "👍 20-30%"
        elif val >= 10: return "🙂 10-20%"
        elif val >= 5: return "🤏 5-10%"
        else: return "Нет скидки"

    df['Группа скидки'] = df['Отклонение %'].apply(discount_group)
    return df

if __name__ == "__main__":
    # Получаем ключи
    fresh_cookies, fresh_headers = get_fresh_credentials()
    
    # Проверка, что токен не пустой
    if fresh_headers.get('Authorization'):
        print("✅ Ключи есть! Начинаем парсинг.")
        
        sellers_list = [4301100] 
        all_data = []
        
        for s_id in sellers_list:
            data = parse_seller(s_id, fresh_cookies, fresh_headers)
            all_data.extend(data)
            time.sleep(2)
            
        if all_data:
            df = analyze_deals(all_data)
            filename = "auto_deal_finder.xlsx"
            df.to_excel(filename, index=False)
            print(f"\n💾 УСПЕХ! Данные сохранены: {filename}")
        else:
            print("Данные не собраны (возможно, токен не подошел к API).")
    else:
        print("❌ Не удалось поймать Authorization токен.")