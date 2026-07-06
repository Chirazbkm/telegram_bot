# Copie ce fichier en config.py et remplis les valeurs

BOT_TOKEN = "8992663029:AAFLZ7VKkNaSWos-3MjI1zi7XLL0J3qfe9E"   # récupéré via @BotFather
CHAT_ID = 5239314344              # ton chat_id (via getUpdates)

CHECK_INTERVAL_SECONDS = 300             # 5 minutes

SEARCH_URL = "https://trouverunlogement.lescrous.fr/tools/42/search?bounds=-1.9550553_50.0758064_1.8028556_48.1793863&locationName=Normandie"

# Départements de Normandie : Calvados, Eure, Manche, Orne, Seine-Maritime
DEPARTMENTS = []

STATE_FILE = "seen_logements.json"

AUTHORIZED_USERS = [
    5239314344,  # Toi
    123456789,   # Pote 1 (à remplacer par son vrai chat_id)   # Pote 2 (à remplacer par son vrai chat_id)
]