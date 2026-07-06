from playwright.sync_api import sync_playwright

def debug_page():
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,  # Mode visible pour voir ce qui se passe
            args=['--no-sandbox']
        )
        context = browser.new_context(
            viewport={'width': 1280, 'height': 800}
        )
        page = context.new_page()
        
        # Aller sur le site
        page.goto('https://trouverunlogement.lescrous.fr/tools/42/search')
        
        # Attendre que la page se charge
        page.wait_for_timeout(5000)
        
        # Sauvegarder le HTML
        with open('debug_visible.html', 'w', encoding='utf-8') as f:
            f.write(page.content())
        
        # Chercher tous les liens
        links = page.query_selector_all('a')
        print(f"Nombre de liens: {len(links)}")
        
        for link in links[:10]:
            href = link.get_attribute('href')
            text = link.inner_text()
            print(f"Lien: {href} - Texte: {text[:100]}")
        
        # Chercher des éléments qui contiennent des prix
        elements_with_price = page.query_selector_all('*')
        price_elements = []
        for el in elements_with_price:
            try:
                text = el.inner_text()
                if '€' in text and 'm²' in text:
                    price_elements.append(el)
            except:
                pass
        
        print(f"Éléments avec prix et surface: {len(price_elements)}")
        
        input("Appuyez sur Enter pour fermer...")
        browser.close()

if __name__ == "__main__":
    debug_page()