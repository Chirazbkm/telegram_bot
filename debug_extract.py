from playwright.sync_api import sync_playwright
import re

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    page = browser.new_page()
    
    page.goto('https://trouverunlogement.lescrous.fr/tools/42/search')
    page.wait_for_timeout(5000)
    
    # Chercher tous les éléments qui contiennent "€" et "m²"
    elements = page.query_selector_all('*')
    found_elements = []
    
    for el in elements:
        try:
            text = el.inner_text()
            if '€' in text and 'm²' in text:
                # Vérifier si c'est un conteneur de logement
                if len(text) > 50 and len(text) < 500:
                    found_elements.append(el)
                    # Afficher un extrait
                    print(f"Élément trouvé: {text[:200]}...")
                    print("-" * 50)
        except:
            pass
    
    print(f"\nNombre total d'éléments avec € et m²: {len(found_elements)}")
    
    # Chercher les données JSON dans les scripts
    scripts = page.query_selector_all('script')
    for i, script in enumerate(scripts[:10]):
        try:
            content = script.inner_html()
            if 'accommodations' in content or '{"id"' in content:
                print(f"\nScript {i}: contient des données d'accommodations")
                print(f"Longueur: {len(content)} caractères")
                # Afficher les 200 premiers caractères
                print(content[:200])
                print("-" * 50)
        except:
            pass
    
    input("Appuyez sur Enter pour fermer...")
    browser.close()