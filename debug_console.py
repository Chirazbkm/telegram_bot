from playwright.sync_api import sync_playwright
import json

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    page = browser.new_page()
    
    page.goto('https://trouverunlogement.lescrous.fr/tools/42/search')
    page.wait_for_timeout(5000)
    
    # Exécuter du JavaScript pour trouver les données
    result = page.evaluate("""
        () => {
            // Chercher dans window
            const data = {};
            
            // Vérifier si les données sont dans window.__INITIAL_STATE__
            if (window.__INITIAL_STATE__) {
                data.initial_state = window.__INITIAL_STATE__;
            }
            
            // Chercher dans les variables globales
            for (let key in window) {
                if (key.includes('accommodation') || key.includes('listing')) {
                    try {
                        data[key] = window[key];
                    } catch(e) {}
                }
            }
            
            // Chercher dans les éléments DOM
            const elements = document.querySelectorAll('[data-cy*="accommodation"], [class*="accommodation"], [class*="listing"]');
            data.element_count = elements.length;
            
            return data;
        }
    """)
    
    print("Données trouvées dans la console:")
    print(json.dumps(result, indent=2, default=str)[:1000])
    
    # Afficher tous les noms de classes possibles
    classes = page.evaluate("""
        () => {
            const allClasses = new Set();
            document.querySelectorAll('*').forEach(el => {
                if (el.className) {
                    if (typeof el.className === 'string') {
                        el.className.split(' ').forEach(c => allClasses.add(c));
                    }
                }
            });
            return Array.from(allClasses).filter(c => c.includes('accommodation') || c.includes('listing') || c.includes('card'));
        }
    """)
    
    print("\nClasses CSS pertinentes:")
    for cls in classes:
        print(f"  .{cls}")
    
    input("Appuyez sur Enter pour fermer...")
    browser.close()