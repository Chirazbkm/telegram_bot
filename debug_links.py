from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    page = browser.new_page()
    
    page.goto('https://trouverunlogement.lescrous.fr/tools/42/search')
    page.wait_for_timeout(5000)
    
    # Trouver TOUS les liens qui contiennent /accommodations/
    links = page.query_selector_all('a[href*="/accommodations/"]')
    print(f"Liens /accommodations/ trouvés: {len(links)}")
    
    for i, link in enumerate(links[:10]):
        href = link.get_attribute('href')
        text = link.inner_text()
        print(f"{i+1}. {href}")
        print(f"   Texte: {text[:100]}")
        print()
    
    # Aussi chercher les liens qui contiennent /accommodations sans le /
    all_links = page.query_selector_all('a')
    accommodation_links = []
    for link in all_links:
        href = link.get_attribute('href')
        if href and 'accommodations' in href:
            accommodation_links.append(link)
    
    print(f"Tous les liens contenant 'accommodations': {len(accommodation_links)}")
    
    input("Appuyez sur Enter pour fermer...")
    browser.close()