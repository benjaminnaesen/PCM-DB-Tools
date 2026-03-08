"""
Startlist generation from HTML sources.

Parses cycling race startlists from FirstCycling and ProCyclingStats HTML
files, matches team/rider names against the open PCM database, and writes
PCM-compatible XML output.
"""

import csv
import os
import re
import shutil
import sqlite3
import tempfile
import unicodedata

from bs4 import BeautifulSoup

from core.constants import DB_CHUNK_SIZE


# ---------------------------------------------------------------------------
# Text normalisation helpers
# ---------------------------------------------------------------------------

def _normalize(text):
    """Lowercase, strip accents, and remove non-alphanumeric characters."""
    text = unicodedata.normalize('NFD', text)
    text = ''.join(c for c in text if unicodedata.category(c) != 'Mn')
    text = re.sub(r'[^a-z0-9 ]', ' ', text.lower())
    return ' '.join(text.split())


def _name_similarity(a, b):
    """Score similarity between two normalised name strings (0.0 to 1.0).

    Uses a combination of token overlap and containment checks to handle
    cases like "Team TotalEnergies" vs "TotalEnergies".
    """
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0

    # Containment: one name fully inside the other
    if a in b or b in a:
        return 0.9

    # Token-based Jaccard with min denominator (more forgiving)
    sa, sb = set(a.split()), set(b.split())
    if not sa or not sb:
        return 0.0
    filler = {'team', 'pro', 'cycling'}
    sa_clean = sa - filler or sa
    sb_clean = sb - filler or sb
    overlap = len(sa_clean & sb_clean)
    return overlap / max(len(sa_clean), len(sb_clean))


# ===========================================================================
# Database lookup (reads from the open SQLite database)
# ===========================================================================

class StartlistDatabase:
    """Loads team and cyclist data for ID lookups.

    Supports two data sources:
        - SQLite database (from a converted CDB file)
        - CSV files (``DYN_team.csv`` and ``DYN_cyclist.csv`` in a folder)

    All matching is accent-insensitive and tolerant of minor name differences.
    """

    def __init__(self, teams=None, cyclists=None, races=None):
        """Initialize with optional pre-loaded data and build lookup indexes."""
        self.teams = teams or []
        self.cyclists = cyclists or []
        self.races = races or []
        self._team_index = {}
        self._cyclist_by_last = {}
        self._build_indexes()

    def _build_indexes(self):
        """Pre-build normalised lookup indexes."""
        self._team_index = {}
        self._cyclist_by_last = {}

        for t in self.teams:
            tid = t.get('IDteam')
            for key in ('gene_sz_name', 'gene_sz_shortname'):
                val = t.get(key, '')
                if val:
                    norm = _normalize(str(val))
                    if norm:
                        self._team_index[norm] = tid

        for c in self.cyclists:
            last = c.get('gene_sz_lastname', '')
            if last:
                norm = _normalize(str(last))
                self._cyclist_by_last.setdefault(norm, []).append(c)

    @classmethod
    def from_sqlite(cls, db_path):
        """Load from a SQLite database (converted CDB)."""
        teams, cyclists, races = [], [], []
        try:
            with sqlite3.connect(db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()

                cursor.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' "
                    "AND name IN ('DYN_team', 'DYN_cyclist', 'STA_race')"
                )
                existing = {row[0] for row in cursor.fetchall()}

                if 'DYN_team' in existing:
                    cursor.execute("SELECT * FROM [DYN_team]")
                    teams = [dict(row) for row in cursor.fetchall()]

                if 'DYN_cyclist' in existing:
                    cursor.execute("SELECT * FROM [DYN_cyclist]")
                    cyclists = [dict(row) for row in cursor.fetchall()]

                if 'STA_race' in existing:
                    cursor.execute("SELECT * FROM [STA_race]")
                    races = [dict(row) for row in cursor.fetchall()]
        except Exception:
            pass
        return cls(teams, cyclists, races)

    @classmethod
    def from_csv_folder(cls, folder):
        """Load from a folder containing DYN_team.csv, DYN_cyclist.csv, etc."""
        teams = cls._load_csv(os.path.join(folder, 'DYN_team.csv'))
        cyclists = cls._load_csv(os.path.join(folder, 'DYN_cyclist.csv'))
        races = cls._load_csv(os.path.join(folder, 'STA_race.csv'))
        return cls(teams, cyclists, races)

    @staticmethod
    def _load_csv(path):
        """Read a CSV file into a list of dicts, or return [] if missing."""
        if not os.path.isfile(path):
            return []
        with open(path, 'r', encoding='utf-8') as f:
            return list(csv.DictReader(f))

    @property
    def loaded(self):
        """True if both tables were loaded successfully."""
        return bool(self.teams and self.cyclists)

    # -- Team matching -------------------------------------------------------

    def match_team(self, name):
        """Find the PCM team ID for a team name.

        Returns:
            (IDteam, matched_name) tuple, or (None, None) if no match.
        """
        norm = _normalize(name)

        if norm in self._team_index:
            return self._team_index[norm], name

        best_score, best_id = 0.0, None
        for t in self.teams:
            for key in ('gene_sz_name', 'gene_sz_shortname'):
                val = t.get(key, '')
                if val:
                    score = _name_similarity(norm, _normalize(str(val)))
                    if score > best_score:
                        best_score = score
                        best_id = t.get('IDteam')

        if best_score >= 0.5:
            return best_id, name
        return None, None

    # -- Rider matching ------------------------------------------------------

    def match_rider(self, full_name, team_id=None):
        """Find the PCM cyclist ID for a rider name.

        Returns:
            (IDcyclist, matched_display) tuple, or (None, None) if no match.
        """
        parts = full_name.strip().split()
        if len(parts) < 2:
            return None, None

        first_norm = _normalize(parts[0])
        last_norm = _normalize(' '.join(parts[1:]))

        # Also try the reverse (some sites show "Lastname Firstname")
        last_norm_alt = _normalize(parts[-1])
        first_norm_alt = _normalize(' '.join(parts[:-1]))

        candidates = list(self._cyclist_by_last.get(last_norm, []))
        if not candidates:
            candidates = list(self._cyclist_by_last.get(last_norm_alt, []))
            if candidates:
                first_norm = first_norm_alt

        # Also include partial last name matches (handles hyphenated /
        # double-barrelled surnames like "Martin-Guyonnet" vs "Martin")
        seen = {id(c) for c in candidates}
        for db_last, cyclists in self._cyclist_by_last.items():
            if db_last != last_norm and (last_norm in db_last or db_last in last_norm):
                for c in cyclists:
                    if id(c) not in seen:
                        candidates.append(c)
                        seen.add(id(c))

        if not candidates:
            return None, None

        def score(c):
            c_first = _normalize(str(c.get('gene_sz_firstname', '')))
            if c_first == first_norm:
                s = 100
            elif first_norm in c_first or c_first in first_norm:
                s = 60
            else:
                s = 0
            if team_id and str(c.get('fkIDteam', '')) == str(team_id):
                s += 20
            return s

        best = max(candidates, key=score)
        if score(best) > 0:
            display = f"{best.get('gene_sz_firstname', '')} {best.get('gene_sz_lastname', '')}"
            return best.get('IDcyclist'), display

        return None, None


# ===========================================================================
# HTML Parsing
# ===========================================================================

class StartlistParser:
    """Parses cycling startlists from various website HTML formats.

    Supports FirstCycling and ProCyclingStats with several fallback
    strategies for generic table/list/div layouts.
    """

    def parse_file(self, filepath):
        """Read a saved HTML file and return parsed startlist data.

        Returns:
            dict mapping team names to lists of rider names, or None.
        """
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                return self._parse_html(f.read())
        except Exception as e:
            print(f"Error reading file: {e}")
            return None

    def _parse_html(self, html_content):
        """Route HTML to the correct site-specific or generic parser."""
        soup = BeautifulSoup(html_content, 'html.parser')

        if self._is_firstcycling(soup):
            result = self._parse_firstcycling(soup)
            if result:
                return result

        if self._is_procyclingstats(soup):
            result = self._parse_procyclingstats(soup)
            if result:
                return result

        for strategy in [
            self._parse_startlist_lists,
            self._parse_tables,
            self._parse_team_divs,
        ]:
            result = strategy(soup)
            if result:
                return result

        return None

    # -- FirstCycling --------------------------------------------------------

    @staticmethod
    def _is_firstcycling(soup):
        """Check if HTML is from FirstCycling."""
        return bool(soup.find('a', href=lambda x: x and 'firstcycling.com' in x))

    @staticmethod
    def _parse_firstcycling(soup):
        """Parse a FirstCycling startlist page (tablesorter tables with rider.php links)."""
        startlist = {}

        for table in soup.find_all('table', class_='tablesorter'):
            thead = table.find('thead')
            if not thead:
                continue
            th = thead.find('th')
            if not th:
                continue

            team_link = th.find('a')
            team_name = team_link.get_text(strip=True) if team_link else th.get_text(strip=True)
            if not team_name:
                continue

            riders = []
            for row in table.find_all('tr'):
                link = row.find('a', href=lambda x: x and 'rider.php' in x)
                if link:
                    name = link.get('title', '').strip() or link.get_text(strip=True)
                    if name:
                        riders.append(name)

            if riders:
                startlist[team_name] = riders

        return startlist or None

    # -- ProCyclingStats -----------------------------------------------------

    @staticmethod
    def _is_procyclingstats(soup):
        """Check if HTML is from ProCyclingStats."""
        return bool(soup.select_one('ul.startlist_v4'))

    @staticmethod
    def _parse_procyclingstats(soup):
        """Parse a ProCyclingStats startlist page.

        PCS structure::

            ul.startlist_v4 > li            (one per team)
                div.ridersCont
                    a.team                  → team name
                    ul > li                 → riders
                        a[href*=/rider/]    → "LASTNAME Firstname"
        """
        startlist = {}

        for team_li in soup.select('ul.startlist_v4 > li'):
            team_link = team_li.select_one('a.team')
            if not team_link:
                continue
            team_name = team_link.get_text(strip=True)
            # Strip category suffix: (WT), (PRT), (CT), etc.
            team_name = re.sub(r'\s*\([^)]*\)\s*$', '', team_name).strip()
            if not team_name:
                continue

            riders = []
            for rider_link in team_li.select('ul > li a[href*="/rider/"]'):
                raw = rider_link.get_text(strip=True)
                if not raw:
                    continue
                name = StartlistParser._pcs_name_to_first_last(raw)
                riders.append(name)

            if riders:
                startlist[team_name] = riders

        return startlist or None

    @staticmethod
    def _pcs_name_to_first_last(pcs_name):
        """Convert PCS 'LASTNAME Firstname' to 'Firstname LASTNAME'.

        PCS displays names with the surname in ALL CAPS followed by the
        given name in normal case.  Detects the boundary by finding the
        first word that is not fully uppercase.
        """
        parts = pcs_name.strip().split()
        if len(parts) < 2:
            return pcs_name

        # Find the first non-uppercase word (= start of first name)
        first_idx = len(parts)
        for i, word in enumerate(parts):
            has_alpha = any(c.isalpha() for c in word)
            if has_alpha and not word.isupper():
                first_idx = i
                break

        if first_idx == 0 or first_idx >= len(parts):
            # Can't determine split; return as-is
            return pcs_name

        firstname = ' '.join(parts[first_idx:])
        lastname = ' '.join(parts[:first_idx])
        return f"{firstname} {lastname}"

    # -- Generic strategies --------------------------------------------------

    @staticmethod
    def _parse_startlist_lists(soup):
        """Fallback parser: extract teams from <ul> elements with 'startlist' class."""
        teams = soup.find_all('ul', class_=lambda x: x and 'startlist' in x.lower())
        if not teams:
            return None

        startlist = {}
        for team_ul in teams:
            prev = team_ul.find_previous(['h3', 'h4', 'h5', 'div'])
            team_name = "Unknown Team"
            if prev:
                text = prev.get_text(strip=True)
                if 3 < len(text) < 100:
                    team_name = text

            riders = []
            for li in team_ul.find_all('li'):
                name = re.sub(r'^\d+\s*', '', li.get_text(strip=True))
                name = re.sub(r'\s+', ' ', name)
                if len(name) > 2:
                    riders.append(name)

            if riders:
                startlist[team_name] = riders

        return startlist or None

    @staticmethod
    def _parse_tables(soup):
        """Fallback parser: extract teams/riders from generic HTML tables."""
        startlist = {}

        for table in soup.find_all('table'):
            current_team = None
            current_riders = []

            for row in table.find_all('tr'):
                cells = row.find_all(['td', 'th'])
                if not cells:
                    continue

                if 'team' in str(row).lower() or len(cells) == 1:
                    if current_team and current_riders:
                        startlist[current_team] = current_riders
                    current_team = cells[0].get_text(strip=True)
                    current_riders = []
                else:
                    for cell in cells:
                        name = cell.get_text(strip=True)
                        if name and len(name) > 2:
                            current_riders.append(re.sub(r'^\d+\s*', '', name))
                            break

            if current_team and current_riders:
                startlist[current_team] = current_riders

        return startlist or None

    @staticmethod
    def _parse_team_divs(soup):
        """Fallback parser: extract teams from <div> elements with 'team' class."""
        startlist = {}

        for div in soup.find_all('div', class_=lambda x: x and 'team' in x.lower()):
            header = div.find(['h3', 'h4', 'h5', 'strong'])
            if not header:
                continue
            team_name = header.get_text(strip=True)

            riders = [
                a.get_text(strip=True)
                for a in div.find_all('a', href=lambda x: x and 'rider' in x)
            ]

            if riders:
                startlist[team_name] = riders

        return startlist or None


# ===========================================================================
# XML Writer
# ===========================================================================

class PCMXmlWriter:
    """Writes parsed startlist data to PCM-compatible XML."""

    @staticmethod
    def write(startlist_data, output_file, db=None, log=None, on_progress=None):
        """Write startlist data to an XML file.

        Args:
            startlist_data: dict mapping team names to rider name lists.
            output_file:    Destination file path.
            db:             Optional StartlistDatabase for real ID lookups.
            log:            Optional callable for status messages.
            on_progress:    Optional callback(current, total) for progress.

        Returns:
            True on success, False if no data was provided.
        """
        if not startlist_data:
            return False

        if log is None:
            log = print

        fallback_team_id = 1000
        unmatched_teams = []
        unmatched_riders = []

        total_riders = sum(len(r) for r in startlist_data.values())
        processed = 0

        lines = ['<startlist>']

        for team_name, riders in startlist_data.items():
            team_id = None
            if db:
                team_id, _ = db.match_team(team_name)
            if team_id:
                log(f"  [TEAM]  {team_name} -> ID {team_id}")
            else:
                team_id = str(fallback_team_id)
                fallback_team_id += 1
                unmatched_teams.append(team_name)
                log(f"  [TEAM]  {team_name} -> NOT FOUND (using {team_id})")

            lines.append(f'    <team id="{team_id}">')

            for rider_name in riders:
                rider_id = None
                if db:
                    rider_id, matched = db.match_rider(rider_name, team_id)
                if rider_id:
                    log(f"    [RIDER] {rider_name} -> ID {rider_id}")
                    lines.append(f'        <cyclist id="{rider_id}" />')
                else:
                    unmatched_riders.append(rider_name)
                    log(f"    [RIDER] {rider_name} -> SKIPPED (not in database)")

                processed += 1
                if on_progress:
                    on_progress(processed, total_riders)

            lines.append('    </team>')

        lines.append('</startlist>')
        lines.append('')  # trailing newline

        with open(output_file, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines))

        if unmatched_teams:
            log(f"\n[!] {len(unmatched_teams)} team(s) not matched: "
                + ", ".join(unmatched_teams))
        if unmatched_riders:
            log(f"[!] {len(unmatched_riders)} rider(s) not matched: "
                + ", ".join(unmatched_riders))

        return True


# ===========================================================================
# Multiplayer database modification
# ===========================================================================

FREE_AGENT_TEAM_ID = 119


def apply_multiplayer_startlist(db_path, team_ids, rider_ids):
    """Create a modified database where non-startlist riders are moved out.

    For every cyclist whose team is in *team_ids* but whose own ID is NOT
    in *rider_ids*, set ``fkIDteam`` to 119 (free-agent pool).  Riders on
    teams not in the startlist are left untouched.

    Args:
        db_path:   Path to the source SQLite database.
        team_ids:  Set/collection of matched team ID strings.
        rider_ids: Set/collection of matched cyclist ID strings.

    Returns:
        (working_path, moved_count, contracts_removed) — path to the
        modified SQLite copy, number of riders moved to team 119, and
        number of contract rows deleted.
    """
    working = os.path.join(tempfile.gettempdir(), "pcm_multiplayer_db.sqlite")
    if os.path.exists(working):
        os.remove(working)
    shutil.copy2(db_path, working)

    team_list = [str(t) for t in team_ids if t is not None]
    rider_list = [str(r) for r in rider_ids if r is not None]

    with sqlite3.connect(working) as conn:
        cursor = conn.cursor()

        # Build the WHERE clause with chunked IN parameters
        # fkIDteam IN (participating teams) AND IDcyclist NOT IN (startlist)
        team_placeholders = ", ".join("?" * len(team_list))
        query = (
            f"UPDATE [DYN_cyclist] SET fkIDteam = ? "
            f"WHERE fkIDteam IN ({team_placeholders})"
        )
        params = [FREE_AGENT_TEAM_ID] + team_list

        if rider_list:
            # Chunk the rider exclusion list to stay within SQLite limits
            for i in range(0, len(rider_list), DB_CHUNK_SIZE):
                chunk = rider_list[i:i + DB_CHUNK_SIZE]
                rider_placeholders = ", ".join("?" * len(chunk))
                query += f" AND IDcyclist NOT IN ({rider_placeholders})"
                params.extend(chunk)

        cursor.execute(query, params)
        moved = cursor.rowcount

        # Clear contracts for the moved riders (same WHERE logic)
        del_query = (
            f"DELETE FROM [DYN_contract_cyclist] "
            f"WHERE fkIDteam IN ({team_placeholders})"
        )
        del_params = list(team_list)

        if rider_list:
            for i in range(0, len(rider_list), DB_CHUNK_SIZE):
                chunk = rider_list[i:i + DB_CHUNK_SIZE]
                rp = ", ".join("?" * len(chunk))
                del_query += f" AND fkIDcyclist NOT IN ({rp})"
                del_params.extend(chunk)

        cursor.execute(del_query, del_params)
        contracts_removed = cursor.rowcount

        conn.commit()

    return working, moved, contracts_removed
