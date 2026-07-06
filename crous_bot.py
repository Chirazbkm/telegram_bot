# bot.py
import asyncio
import json
import logging
import re
import time
from pathlib import Path
from typing import List, Dict, Optional, Set
from datetime import datetime

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

import config

def is_authorized(update: Update) -> bool:
    """Vérifie si l'utilisateur est autorisé."""
    user_id = update.effective_chat.id
    return user_id in config.AUTHORIZED_USERS
    
# Configure logging
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("crous_bot")

STATE_PATH = Path(config.STATE_FILE)
BROWSER_HEADLESS = True
BROWSER_TIMEOUT = 30000
PAGE_LOAD_TIMEOUT = 15000
NAVIGATION_RETRIES = 3


def load_seen() -> Set[str]:
    """Load already notified accommodation IDs from state file."""
    if STATE_PATH.exists():
        try:
            return set(json.loads(STATE_PATH.read_text()))
        except (json.JSONDecodeError, ValueError) as e:
            log.warning(f"Error reading state file: {e}. Starting fresh.")
            return set()
    return set()


def save_seen(seen: Set[str]) -> None:
    """Save notified accommodation IDs to state file."""
    STATE_PATH.write_text(json.dumps(sorted(seen), indent=2))


def extract_postal_code(text: str) -> Optional[str]:
    """Extract French postal code (5 digits) from text."""
    match = re.search(r'\b(\d{5})\b', text)
    return match.group(1) if match else None


def parse_accommodation(element) -> Optional[Dict]:
    """
    Parse an accommodation from a Playwright element using fr-card structure.
    """
    try:
        # Extract the link with accommodation ID
        link = element.query_selector('a[href*="/accommodations/"]')
        if not link:
            # Try to find any link containing accommodations
            all_links = element.query_selector_all('a')
            for l in all_links:
                href = l.get_attribute('href')
                if href and '/accommodations/' in href:
                    link = l
                    break
        
        if not link:
            log.warning("No accommodation link found")
            return None
        
        href = link.get_attribute('href')
        if not href:
            return None
        
        # Extract ID from URL (format: /tools/42/accommodations/XXX)
        id_match = re.search(r'/accommodations/(\d+)', href)
        listing_id = id_match.group(1) if id_match else None
        
        if not listing_id:
            log.warning(f"Could not extract ID from href: {href}")
            return None
        
        # Get the card text content
        text = element.inner_text()
        
        # Extract title (from the link or h3)
        title = link.inner_text().strip()
        if not title:
            title_elem = element.query_selector('h1, h2, h3, h4, .fr-card__title')
            if title_elem:
                title = title_elem.inner_text().strip()
        
        # Extract price
        price_match = re.search(r'(\d[\d\s]*[\.,]?\d*)\s?[€]', text)
        if price_match:
            price = price_match.group(1).strip().replace(' ', '')
            # Format price properly
            try:
                price_float = float(price.replace(',', '.'))
                price = f"{price_float:.2f} €" if price_float % 1 != 0 else f"{int(price_float)} €"
            except:
                price = f"{price} €"
        else:
            price = "Prix non disponible"
        
        # Extract surface
        surface_match = re.search(r'(\d+[\.,]?\d*)\s*m²', text)
        if surface_match:
            surface = surface_match.group(1).strip().replace(',', '.')
            try:
                surface_float = float(surface)
                surface = f"{surface_float:.1f} m²" if surface_float % 1 != 0 else f"{int(surface_float)} m²"
            except:
                surface = f"{surface} m²"
        else:
            surface = "Surface non précisée"
        
        # Extract address - usually on a line with postal code
        lines = [l.strip() for l in text.split('\n') if l.strip()]
        address = ""
        
        # Find the line that contains a postal code (5 digits)
        for line in lines:
            if re.search(r'\b\d{5}\b', line):
                address = line
                break
        
        # If no address found, try to find it in the card
        if not address:
            address_elem = element.query_selector('.fr-card__desc, [class*="address"]')
            if address_elem:
                address = address_elem.inner_text().strip()
            else:
                # Try to get address from lines (the one with numbers)
                for line in lines:
                    if re.search(r'\d+', line) and len(line) > 10:
                        address = line
                        break
        
        # Clean address
        if address:
            # Remove extra spaces
            address = re.sub(r'\s+', ' ', address).strip()
        
        # Extract postal code from address
        postal_code = extract_postal_code(address) if address else None
        
        # Build full URL
        if href.startswith('/'):
            url = f"https://trouverunlogement.lescrous.fr{href}"
        else:
            url = href
        
        # Try to get department from postal code or address
        department = None
        if postal_code:
            department = postal_code[:2]
        elif address:
            # Try to find department in address
            dept_match = re.search(r'(\d{2})\s*$', address)
            if dept_match:
                department = dept_match.group(1)
        
        return {
            "id": listing_id,
            "name": title,
            "url": url,
            "address": address if address else "Adresse non disponible",
            "postal_code": postal_code,
            "department": department,
            "price": price,
            "surface": surface,
        }
        
    except Exception as e:
        log.error(f"Error parsing accommodation: {e}")
        return None


def fetch_normandie_listings() -> List[Dict]:
    """
    Fetch accommodations using Playwright with fr-card structure.
    """
    listings = []
    seen_elements = set()  # To avoid duplicates
    
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=BROWSER_HEADLESS,
            args=['--no-sandbox', '--disable-setuid-sandbox']
        )
        
        try:
            context = browser.new_context(
                viewport={'width': 1280, 'height': 800},
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            )
            page = context.new_page()
            
            log.info(f"Navigating to {config.SEARCH_URL}")
            
            for attempt in range(NAVIGATION_RETRIES):
                try:
                    response = page.goto(
                        config.SEARCH_URL, 
                        wait_until='networkidle',
                        timeout=PAGE_LOAD_TIMEOUT
                    )
                    if response and response.status == 200:
                        break
                except Exception as e:
                    log.warning(f"Navigation attempt {attempt + 1} failed: {e}")
                    if attempt == NAVIGATION_RETRIES - 1:
                        raise
                    time.sleep(2)
            
            # Wait for accommodations to load
            log.info("Waiting for accommodations to load...")
            page.wait_for_timeout(3000)
            
            # Scroll to load all content
            log.info("Scrolling to load all content...")
            for _ in range(3):
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                page.wait_for_timeout(1000)
            
            # Find all fr-card elements or accommodation cards
            card_selectors = [
                '.fr-card',
                '[class*="accommodation"]',
                '[class*="listing"]',
                '[class*="card"]',
            ]
            
            cards = []
            for selector in card_selectors:
                found = page.query_selector_all(selector)
                if found:
                    log.info(f"Found {len(found)} cards with selector: {selector}")
                    cards = found
                    break
            
            if not cards:
                log.warning("No card elements found")
                # Debug: save HTML
                html_content = page.content()
                debug_file = Path("debug_page.html")
                debug_file.write_text(html_content)
                log.info(f"Saved page HTML to {debug_file} for debugging")
                return []
            
            log.info(f"Processing {len(cards)} accommodation cards...")
            
            for card in cards:
                # Check if this card actually has an accommodation link
                has_link = card.query_selector('a[href*="/accommodations/"]')
                if not has_link:
                    continue
                
                listing = parse_accommodation(card)
                if not listing:
                    continue
                
                # Avoid duplicates
                if listing["id"] in seen_elements:
                    continue
                seen_elements.add(listing["id"])
                
                listings.append(listing)
                log.debug(f"Found: {listing['name']} (ID: {listing['id']})")
            
            log.info(f"Total listings extracted: {len(listings)}")
            
            # Filter by department if departments are configured
            if listings and config.DEPARTMENTS:
                filtered = []
                for listing in listings:
                    postal_code = listing.get('postal_code')
                    department = listing.get('department')
                    
                    # Check if postal code or department matches
                    if postal_code and postal_code[:2] in config.DEPARTMENTS:
                        filtered.append(listing)
                    elif department and department in config.DEPARTMENTS:
                        filtered.append(listing)
                    else:
                        # If no postal code, we keep the listing but log it
                        if not postal_code:
                            log.debug(f"Listing {listing['id']} has no postal code")
                
                log.info(f"Filtered to {len(filtered)} listings in departments {config.DEPARTMENTS}")
                listings = filtered
            
        except Exception as e:
            log.error(f"Error in fetch_normandie_listings: {e}", exc_info=True)
            raise
        finally:
            browser.close()
    
    return listings


async def send_listing(application, listing: Dict) -> None:
    """Send a single accommodation notification to Telegram."""
    text = (
        f"🏠 <b>{listing['name']}</b>\n"
        f"📍 {listing['address']}\n"
        f"💶 {listing['price']}\n"
        f"📐 {listing['surface']}\n"
        f"🔗 {listing['url']}"
    )
    try:
        await application.bot.send_message(
            chat_id=config.CHAT_ID,
            text=text,
            parse_mode="HTML"
        )
    except Exception as e:
        log.error(f"Error sending message: {e}")


async def check_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Job that runs periodically to check for new accommodations."""
    log.info("Starting automatic check for CROUS accommodations...")
    
    try:
        loop = asyncio.get_event_loop()
        listings = await loop.run_in_executor(None, fetch_normandie_listings)
        
        if not listings:
            log.info("No listings found in the configured departments")
            return
        
        seen = load_seen()
        new_listings = [l for l in listings if l["id"] not in seen]
        
        log.info(f"Found {len(listings)} total listings, {len(new_listings)} new")
        
        if not new_listings:
            log.info("No new accommodations to notify")
            return
        
        for listing in new_listings:
            await send_listing(context.application, listing)
            seen.add(listing["id"])
            time.sleep(0.5)
        
        save_seen(seen)
        log.info(f"Notified {len(new_listings)} new accommodations")
        
    except Exception as e:
        log.error(f"Error in check_job: {e}", exc_info=True)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start command."""
    if not is_authorized(update):
        await update.message.reply_text("❌ Désolé, vous n'êtes pas autorisé à utiliser ce bot.")
        return
    await update.message.reply_text(
        f"🏠 Salut ! Je surveille le CROUS de Normandie toutes les "
        f"{config.CHECK_INTERVAL_SECONDS // 60} minutes.\n\n"
        f"Commandes disponibles :\n"
        f"/check - vérifier maintenant\n"
        f"/status - voir combien de logements sont déjà connus\n\n"
        f"/all - voir tous les logements normands\n\n"
        f"Configuration:\n"
        f"• Départements: {', '.join(config.DEPARTMENTS)}\n"
        f"• Intervalle: {config.CHECK_INTERVAL_SECONDS // 60} min"
    )


async def cmd_check(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /check command - manual check."""
    if not is_authorized(update):
        await update.message.reply_text("❌ Vous n'êtes pas autorisé à utiliser cette commande.")
        return
    
    await update.message.reply_text("🔎 Vérification en cours...")
    
    try:
        loop = asyncio.get_event_loop()
        listings = await loop.run_in_executor(None, fetch_normandie_listings)
        
        if not listings:
            await update.message.reply_text("Aucun logement trouvé en Normandie pour le moment.")
            return
        
        seen = load_seen()
        new_listings = [l for l in listings if l["id"] not in seen]
        
        if not new_listings:
            await update.message.reply_text(
                f"📊 Pas de nouveauté : {len(listings)} logement(s) en Normandie, déjà tous connus."
            )
            return
        
        for listing in new_listings:
            await send_listing(context.application, listing)
            seen.add(listing["id"])
            time.sleep(0.5)
        
        save_seen(seen)
        
        await update.message.reply_text(
            f"✅ {len(new_listings)} nouveau(x) logement(s) notifié(s) !"
        )
        
    except Exception as e:
        await update.message.reply_text(f"❌ Erreur pendant la vérification : {str(e)}")
        log.error(f"Error in cmd_check: {e}", exc_info=True)


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /status command."""
    if not is_authorized(update):
        await update.message.reply_text("❌ Vous n'êtes pas autorisé à utiliser cette commande.")
        return
    
    seen = load_seen()
    await update.message.reply_text(
        f"📊 Statistiques:\n"
        f"• {len(seen)} logement(s) déjà notifié(s)\n"
        f"• Dernière vérification: à l'instant\n"
        f"• Intervalle: {config.CHECK_INTERVAL_SECONDS // 60} minutes\n"
        f"• Départements surveillés: {', '.join(config.DEPARTMENTS)}"
    )

async def cmd_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /list command - show all accommodations (old + new)."""
    if not is_authorized(update):
        await update.message.reply_text("❌ Vous n'êtes pas autorisé à utiliser cette commande.")
        return
    
    await update.message.reply_text("🔎 Récupération de tous les logements...")
    
    try:
        loop = asyncio.get_event_loop()
        listings = await loop.run_in_executor(None, fetch_normandie_listings)
        
        if not listings:
            await update.message.reply_text("Aucun logement trouvé en Normandie.")
            return
        
        seen = load_seen()
        
        # Compter
        total = len(listings)
        nouveaux = len([l for l in listings if l["id"] not in seen])
        anciens = len([l for l in listings if l["id"] in seen])
        
        message = f"🏠 <b>{total} logements en Normandie</b>\n"
        message += f"🆕 Nouveaux : {nouveaux}\n"
        message += f"📌 Déjà notifiés : {anciens}\n\n"
        
        # Afficher les 20 premiers
        for listing in listings[:20]:
            status = "✅" if listing["id"] in seen else "🆕"
            message += f"{status} {listing['name']}\n"
            message += f"   💶 {listing['price']} | 📐 {listing['surface']}\n\n"
        
        if total > 20:
            message += f"... et {total - 20} autres logements."
        
        await update.message.reply_text(message, parse_mode="HTML")
        
    except Exception as e:
        await update.message.reply_text(f"❌ Erreur: {str(e)}")
async def cmd_debugfilter(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /debugfilter command - show filtering details for each listing."""
    if update.effective_chat.id != config.CHAT_ID:
        await update.message.reply_text("❌ Non autorisé.")
        return
    
    await update.message.reply_text("🔎 Analyse du filtrage...")
    
    try:
        loop = asyncio.get_event_loop()
        all_listings = await loop.run_in_executor(None, fetch_normandie_listings)
        
        if not all_listings:
            await update.message.reply_text("Aucun logement trouvé.")
            return
        
        seen = load_seen()
        
        message = f"🔍 <b>Détail du filtrage</b>\n"
        message += f"📊 {len(all_listings)} logements trouvés\n"
        message += f"📌 Départements configurés: {', '.join(config.DEPARTMENTS)}\n\n"
        
        for listing in all_listings:
            postal = listing.get('postal_code')
            dept = listing.get('department')
            listing_id = listing.get('id')
            
            # Vérifier si le logement passe le filtre
            passes_filter = False
            reason = ""
            
            if postal and postal[:2] in config.DEPARTMENTS:
                passes_filter = True
                reason = f"CP {postal} (département {postal[:2]})"
            elif dept and dept in config.DEPARTMENTS:
                passes_filter = True
                reason = f"Département {dept}"
            else:
                if not postal:
                    reason = "⚠️ PAS DE CODE POSTAL !"
                else:
                    reason = f"❌ CP {postal} (département {postal[:2]}) non surveillé"
            
            status = "✅" if listing_id in seen else "🆕"
            filter_status = "✅ ACCEPTÉ" if passes_filter else "❌ FILTRÉ"
            
            message += f"{status} {filter_status} | {listing['name'][:30]}\n"
            message += f"   ID: {listing_id} | CP: {postal or 'NON TROUVÉ'} | {reason}\n"
            message += f"   Prix: {listing['price']} | Surface: {listing['surface']}\n\n"
            
            if len(message) > 4000:
                message += "... (suite tronquée)\n"
                break
        
        await update.message.reply_text(message, parse_mode="HTML")
        
    except Exception as e:
        await update.message.reply_text(f"❌ Erreur: {str(e)}")
async def cmd_raw(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /raw command - show raw text of ALL listings without any filter."""
    if update.effective_chat.id != config.CHAT_ID:
        await update.message.reply_text("❌ Non autorisé.")
        return
    
    await update.message.reply_text("🔎 Récupération des données brutes...")
    
    try:
        # Désactiver temporairement le filtre
        original_departments = config.DEPARTMENTS
        config.DEPARTMENTS = []
        
        loop = asyncio.get_event_loop()
        all_listings = await loop.run_in_executor(None, fetch_normandie_listings)
        
        config.DEPARTMENTS = original_departments
        
        if not all_listings:
            await update.message.reply_text("Aucun logement trouvé.")
            return
        
        message = f"📄 <b>Données brutes des {len(all_listings)} logements</b>\n\n"
        
        for listing in all_listings[:10]:  # Limite à 10
            message += f"🏠 <b>{listing['name']}</b> (ID: {listing['id']})\n"
            message += f"📍 Adresse brute: {listing['address']}\n"
            message += f"📮 Code postal extrait: {listing.get('postal_code', 'NON TROUVÉ')}\n"
            message += f"💶 Prix: {listing['price']}\n"
            message += f"📐 Surface: {listing['surface']}\n"
            message += f"🔗 {listing['url']}\n\n"
        
        await update.message.reply_text(message, parse_mode="HTML")
        
    except Exception as e:
        await update.message.reply_text(f"❌ Erreur: {str(e)}")
async def cmd_all(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /all command - show ALL Normandy listings with their status."""
    if not is_authorized(update):
        await update.message.reply_text("❌ Vous n'êtes pas autorisé à utiliser cette commande.")
        return
    
    await update.message.reply_text("🔎 Récupération de tous les logements normands...")
    
    try:
        loop = asyncio.get_event_loop()
        all_listings = await loop.run_in_executor(None, fetch_normandie_listings)
        
        if not all_listings:
            await update.message.reply_text("Aucun logement trouvé en Normandie.")
            return
        
        seen = load_seen()
        
        # Trier par ID (du plus ancien au plus récent)
        sorted_listings = sorted(all_listings, key=lambda x: int(x["id"]))
        
        total = len(sorted_listings)
        nouveaux = len([l for l in sorted_listings if l["id"] not in seen])
        anciens = len([l for l in sorted_listings if l["id"] in seen])
        
        # Construire le message
        message = f"🏠 <b>LISTE COMPLÈTE - {total} logements en Normandie</b>\n"
        message += f"🆕 Nouveaux : {nouveaux}\n"
        message += f"📌 Déjà notifiés : {anciens}\n"
        message += f"{'═' * 30}\n\n"
        
        for i, listing in enumerate(sorted_listings, 1):
            is_seen = listing["id"] in seen
            status = "✅" if is_seen else "🆕"
            status_text = "Déjà notifié" if is_seen else "NOUVEAU !"
            
            message += f"{i}. {status} <b>{listing['name']}</b>\n"
            message += f"   📍 {listing['address']}\n"
            message += f"   💶 {listing['price']} | 📐 {listing['surface']}\n"
            message += f"   🆔 ID: {listing['id']} | 📮 CP: {listing.get('postal_code', 'N/A')}\n"
            message += f"   📌 Statut: {status_text}\n"
            message += f"   🔗 {listing['url']}\n\n"
        
        await update.message.reply_text(message, parse_mode="HTML")
        
    except Exception as e:
        await update.message.reply_text(f"❌ Erreur: {str(e)}")

def main() -> None:
    """Main entry point for the bot."""
    import asyncio
    
    application = Application.builder().token(config.BOT_TOKEN).build()
    
    application.add_handler(CommandHandler("start", cmd_start))
    application.add_handler(CommandHandler("check", cmd_check))
    application.add_handler(CommandHandler("status", cmd_status))
    application.add_handler(CommandHandler("list", cmd_list))
    application.add_handler(CommandHandler("debugfilter", cmd_debugfilter))
    application.add_handler(CommandHandler("raw", cmd_raw))
    application.add_handler(CommandHandler("all", cmd_all))
    job_queue = application.job_queue
    if job_queue:
        job_queue.run_repeating(
            check_job,
            interval=config.CHECK_INTERVAL_SECONDS,
            first=10
        )
        log.info(f"Scheduled checks every {config.CHECK_INTERVAL_SECONDS} seconds")
    else:
        log.warning("Job queue not available, checks will not run automatically")
    
    log.info("Starting CROUS Normandie bot...")
    application.run_polling(
        allowed_updates=["message", "callback_query"],
        drop_pending_updates=True
    )


if __name__ == "__main__":
    main()