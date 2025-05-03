import sys
from mcp.server.fastmcp import FastMCP
import requests
import os
from bs4 import BeautifulSoup
import re

API_KEY = os.environ.get('API_KEY')
STEAM_ID = os.environ.get('STEAM_ID')

mcp = FastMCP("steam", port="8099")

@mcp.tool()
def get_owned_games() -> str:
    """
    Retrieve a formatted list of all games owned by a Steam user.
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
    Retrieve achievement information for a specific Steam game. Returns a list of achievements, their unlock status and global unlock rates.

    Args:
        app_id: The AppID of the game to fetch achievements for.
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
    Search top-rated Steam Community guides for a game and keyword.

    Args:
        app_id: The AppID of the game to search guides for.
        query: Search keywords to filter guide titles and descriptions.
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
        resp = session.get(base_url, headers=headers)
        # Handle Proceed() redirect if present
        if 'onclick="Proceed()"' in resp.text:
            redirect = re.search(r'document\.location\s*=\s*"([^"]+)"', resp.text)
            if redirect:
                resp = session.get(redirect.group(1), headers=headers)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, 'html.parser')
        guides = soup.select('div.workshopItemCollectionContainer')[:5]
        if guides:
            header = [f"Top {len(guides)} guides for '{query}':"]
            entries = []
            for i, g in enumerate(guides, 1):
                a = g.select_one('a.workshopItemCollection')
                title = a.select_one('.workshopItemTitle').get_text(strip=True)
                desc = a.select_one('.workshopItemShortDesc').get_text(strip=True)
                link = a['href']
                entries.append(f"{i}. {title}\n   {link}\n   Description: {desc}")
            return "\n".join(header + entries)

        # Fallback to JSON API
        json_resp = session.get(json_api, headers=headers)
        json_resp.raise_for_status()
        data = json_resp.json()
        html_frag = data.get('results_html', '')
        soup = BeautifulSoup(html_frag, 'html.parser')
        items = soup.select('a.workshopItemCollection')[:5]
        if not items:
            return f"No guides found for '{query}'. Check manually: {base_url}"
        header = [f"Top {len(items)} guides (via JSON API) for '{query}':"]
        entries = []
        for i, a in enumerate(items, 1):
            title = a.select_one('.workshopItemTitle').get_text(strip=True)
            desc = a.select_one('.workshopItemShortDesc').get_text(strip=True)
            link = a['href']
            entries.append(f"{i}. {title}\n   {link}\n   Description: {desc}")
        return "\n".join(header + entries)

    except Exception as e:
        print(f"Error in search_steam_guides: {e}", file=sys.stderr)
        return f"Error searching guides: {e}\nURL: {base_url}"

@mcp.tool()
def fetch_steam_guide(guide_id: str) -> str:
    """
    Fetch the full content of a Steam Community guide by its ID.

    Args:
        guide_id: The unique Steam guide ID.
    """
    url = f"https://steamcommunity.com/sharedfiles/filedetails/?id={guide_id}"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    session = requests.Session()
    session.cookies.set('wants_mature_content', '1', domain='steamcommunity.com', path='/')
    session.cookies.set('lastagecheckage', '1', domain='steamcommunity.com', path='/')
    session.cookies.set('birthtime', '1', domain='steamcommunity.com', path='/')

    try:
        resp = session.get(url, headers=headers, allow_redirects=True)
        if '/agecheck/' in resp.url or 'onclick="Proceed()"' in resp.text:
            resp = session.get(url, headers=headers)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")
        container = soup.find("div", class_="guide subSections")
        if not container:
            return "Info: No subsections found for guide ID {guide_id}."

        sections = []
        for box in container.find_all("div", class_="subSection detailBox"):
            title = box.find("div", class_="subSectionTitle")
            body = box.find("div", class_="subSectionDesc")
            if body:
                for br in body.find_all("br"):
                    br.replace_with("\n")
            sections.append(f"{title.get_text(strip=True) if title else 'Untitled'}\n{body.get_text('\n', strip=True) if body else ''}")

        return "\n\n".join(sections)

    except Exception as e:
        print(f"Error in fetch_steam_guide: {e}", file=sys.stderr)
        return f"Error fetching guide: {e}"

if __name__ == "__main__":
    mcp.run(transport="sse")
