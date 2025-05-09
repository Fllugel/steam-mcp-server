import sys
from mcp.server.fastmcp import FastMCP
import requests
import os
from bs4 import BeautifulSoup
import re
import numpy as np
from sentence_transformers import SentenceTransformer

try:
    import faiss
except ImportError:
    faiss = None

from dotenv import load_dotenv
load_dotenv()

API_KEY = os.environ.get('API_KEY')
STEAM_ID = os.environ.get('STEAM_ID')

mcp = FastMCP("steam", port="8099")

@mcp.tool()
def get_owned_games() -> str:
    """
    Retrieve a formatted list of all games owned by a Steam user.

    Returns:
        str: A summary of owned games with their AppIDs and playtimes.
    """
    try:
        if not API_KEY or not STEAM_ID:
            return "Error: Missing environment variables API_KEY or STEAM_ID."

        url = 'https://api.steampowered.com/IPlayerService/GetOwnedGames/v1/'
        params = {
            'key': API_KEY,
            'steamid': STEAM_ID,
            'include_appinfo': True,
            'include_played_free_games': True
        }

        response = requests.get(url, params=params)
        response.raise_for_status()

        game_list = response.json().get('response', {}).get('games', [])
        header = f"Total games owned: {len(game_list)}"
        lines = [f"{game['name']} (AppID: {game['appid']}) - Playtime: {game['playtime_forever']} mins"
                 for game in game_list]
        return "\n".join([header] + lines)

    except Exception as e:
        print(f"Error in get_owned_games: {e}", file=sys.stderr)
        return f"Error fetching owned games: {e}"

@mcp.tool()
def get_recently_played_games() -> str:
    """
    Fetch the list of games a user has played in the past two weeks.

    Returns:
        str: A list of recently played games.
    """
    try:
        if not API_KEY or not STEAM_ID:
            return "Error: Missing environment variables API_KEY or STEAM_ID."

        url = 'https://api.steampowered.com/IPlayerService/GetRecentlyPlayedGames/v1/'
        params = {'key': API_KEY, 'steamid': STEAM_ID}

        response = requests.get(url, params=params)
        response.raise_for_status()

        data = response.json().get('response', {})
        recent_games = data.get('games', [])

        if not recent_games:
            return "No games played in the last two weeks."

        header = f"Recently played games ({len(recent_games)} found):"
        lines = [f"{game['name']} (AppID: {game['appid']}) - Played {game['playtime_2weeks']} mins in last 2 weeks"
                 for game in recent_games]
        return "\n".join([header] + lines)

    except Exception as e:
        print(f"Error in get_recently_played_games: {e}", file=sys.stderr)
        return f"Error fetching recent games: {e}"

@mcp.tool()
def get_game_achievements(app_id: int) -> str:
    """
    Retrieve achievement information for a specific Steam game, including user unlock status and global percentages.

    Args:
        app_id (int): The AppID of the game to fetch achievements for.

    Returns:
        str: A list of achievements with names, unlock status, and global unlock rates, or a message if unavailable.
    """

    if not API_KEY or not STEAM_ID:
        return "Error: Missing required environment variables (API_KEY or STEAM_ID)."

    try:
        # User achievement status
        player_url = 'https://api.steampowered.com/ISteamUserStats/GetPlayerAchievements/v1/'
        player_params = {'key': API_KEY, 'steamid': STEAM_ID, 'appid': app_id}
        player_resp = requests.get(player_url, params=player_params)
        player_resp.raise_for_status()

        player_data = player_resp.json().get('playerstats', {})
        user_achievements = player_data.get('achievements', [])
        if not user_achievements:
            return f"Info: No achievement data available for AppID {app_id}."

        unlocked = {ach['apiname']: ach['achieved'] == 1 for ach in user_achievements}

        # Game schema
        schema_url = 'https://api.steampowered.com/ISteamUserStats/GetSchemaForGame/v2/'
        schema_params = {'key': API_KEY, 'appid': app_id}
        schema_resp = requests.get(schema_url, params=schema_params)
        schema_resp.raise_for_status()

        schema = schema_resp.json().get('game', {}).get('availableGameStats', {}).get('achievements', [])
        if not schema:
            return f"Info: No achievement schema found for AppID {app_id}."

        # Global percentages
        global_url = 'https://api.steampowered.com/ISteamUserStats/GetGlobalAchievementPercentagesForApp/v0002/'
        global_params = {'gameid': app_id, 'format': 'json'}
        global_resp = requests.get(global_url, params=global_params)
        global_resp.raise_for_status()

        global_data = global_resp.json().get('achievementpercentages', {}).get('achievements', [])
        global_percent = {a['name']: float(a['percent']) for a in global_data}

        # Compile results
        lines = []
        for ach in schema:
            apiname = ach.get('name')
            lines.append(
                f"{ach.get('displayName', apiname)} | Unlocked: {'Yes' if unlocked.get(apiname, False) else 'No'}"
                f" | Global Unlock Rate: {global_percent.get(apiname, 0.0):.2f}%\n"
                f"Description: {ach.get('description', 'No description')}"
            )
        return f"Achievements for AppID {app_id}:\n\n" + "\n\n".join(lines)

    except requests.exceptions.HTTPError as http_err:
        return f"HTTP Error: {http_err}"
    except requests.exceptions.RequestException as req_err:
        return f"Network Error: {req_err}"
    except Exception as e:
        return f"Unexpected Error: {e}"

@mcp.tool()
def search_steam_guides(app_id: int, query: str) -> str:
    """
    Search top-rated Steam Community guides for a game.

    Args:
        app_id (int): The game's AppID.
        query (str): Keywords to filter guides.

    Returns:
        str: A list of up to 10 guides, each with a guide ID required for use with `fetch_steam_guide()`.
    """
    base_url = (
        f"https://steamcommunity.com/app/{app_id}/guides/?searchText={query.replace(' ', '+')}&browsefilter=toprated"
    )
    json_api = (
        f"https://steamcommunity.com/app/{app_id}/homecontent/"
        "?userreviewsoffset=0&p=1&communityhub=1"
        "&workshopitemspreview=0&readytouseitemspreview=0"
        "&mtxitemspreview=0&itemspreview=0&curations=0"
    )
    headers = {"User-Agent": "Mozilla/5.0"}
    session = requests.Session()
    session.cookies.set('wants_mature_content', '1', domain='steamcommunity.com', path='/')
    session.cookies.set('birthtime', '1', domain='steamcommunity.com', path='/')

    try:
        # First attempt: HTML scraping
        resp = session.get(base_url, headers=headers)
        if 'onclick="Proceed()"' in resp.text:
            redirect = re.search(r'document\\.location\\s*=\\s*"([^"]+)"', resp.text)
            if redirect:
                resp = session.get(redirect.group(1), headers=headers)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, 'html.parser')
        items = soup.select('div.workshopItemCollectionContainer')[:10]
        # Fallback: JSON API
        if not items:
            json_resp = session.get(json_api, headers=headers)
            json_resp.raise_for_status()
            data = json_resp.json()
            soup = BeautifulSoup(data.get('results_html', ''), 'html.parser')
            items = soup.select('a.workshopItemCollection')[:10]

        if not items:
            return f"No guides found for '{query}' (AppID {app_id})."

        # Build formatted output
        lines = [f"Top {len(items)} guides for '{query}':"]
        for idx, el in enumerate(items, start=1):
            link = el.select_one('a.workshopItemCollection')['href']
            match = re.search(r'id=(\d+)', link)
            guide_id = match.group(1) if match else link
            title = el.select_one('.workshopItemTitle').get_text(strip=True)
            desc = el.select_one('.workshopItemShortDesc').get_text(strip=True)
            lines.append(
                f"{idx}. ID: {guide_id}\n"
                f"   Name: {title}\n"
                f"   Description: {desc}"
            )
        return "\n".join(lines)

    except Exception as e:
        return f"Error searching guides for '{query}' (AppID {app_id}): {e}"

_embedding_model = SentenceTransformer('all-MiniLM-L6-v2')

@mcp.tool()
def fetch_steam_guide(guide_id: str, query: str) -> str:
    """
    Fetch the full content of a Steam Community guide. If the content length is below
    the threshold, return the entire guide. Otherwise, perform a vector search over
    guide sections for the provided query and return only the most relevant sections.

    Args:
        guide_id (str): The Steam guide ID.
        query (str): Search query to retrieve relevant content.

    Returns:
        str: Full guide text (if small) or top matching sections joined by separators.
    """
    # Configuration
    threshold_chars = 20000
    top_k = 5

    # Build URL and session
    url = f"https://steamcommunity.com/sharedfiles/filedetails/?id={guide_id}"
    headers = {"User-Agent": "Mozilla/5.0"}
    session = requests.Session()
    # Bypass age check
    for name, value in [('wants_mature_content', '1'), ('lastagecheckage', '1'), ('birthtime', '1')]:
        session.cookies.set(name, value, domain='steamcommunity.com', path='/')

    try:
        resp = session.get(url, headers=headers, allow_redirects=True)
        if '/agecheck/' in resp.url or 'onclick="Proceed()"' in resp.text:
            resp = session.get(url, headers=headers)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")
        container = soup.find("div", class_="guide subSections")
        if not container:
            return f"Info: No subsections found for guide ID {guide_id}."

        # Extract sections
        sections = []
        for box in container.find_all("div", class_="subSection detailBox"):
            title = box.find("div", class_="subSectionTitle")
            body = box.find("div", class_="subSectionDesc")
            if body:
                for br in body.find_all("br"):
                    br.replace_with("\n")
            text = (title.get_text(strip=True) + "\n") if title else ""
            text += (body.get_text("\n", strip=True) if body else '')
            sections.append(text)

        full_text = "\n\n".join(sections)

        # If small enough, return full text
        if len(full_text) <= threshold_chars:
            return full_text

        # Ensure FAISS is installed
        if faiss is None:
            return "Error: FAISS library is required for large-guide search but is not installed."

        # Compute embeddings locally
        embeddings = _embedding_model.encode(sections, convert_to_numpy=True)

        # Build FAISS index
        dim = embeddings.shape[1]
        index = faiss.IndexFlatL2(dim)
        index.add(np.array(embeddings, dtype='float32'))

        # Embed query locally
        q_emb = _embedding_model.encode([query], convert_to_numpy=True)[0].astype('float32')
        distances, indices = index.search(q_emb.reshape(1, -1), top_k)

        # Collect top sections
        results = []
        for dist, idx in zip(distances[0], indices[0]):
            results.append(f"[Score: {dist:.2f}]\n{sections[idx]}")

        # Return joined relevant sections
        return "\n\n---\n\n".join(results)

    except Exception as e:
        print(f"Error in fetch_steam_guide: {e}", file=sys.stderr)
        return f"Error fetching guide: {e}"


def main():
    mcp.run(transport="stdio")

if __name__ == "__main__":
    main()
