import streamlit as st
import requests
import datetime
import math

# =====================
# CONFIG
# =====================
BASE_URL = "https://v3.football.api-sports.io"

# קורא מפתח מ-Secrets (Streamlit Cloud)
API_KEY = ""
try:
    API_KEY = st.secrets.get("APISPORTS_KEY", "")
except Exception:
    API_KEY = ""

DEMO_MODE = (API_KEY.strip() == "")

HEADERS = {"x-apisports-key": API_KEY} if not DEMO_MODE else {}

# =====================
# LOW-LEVEL API
# =====================
def api_get(endpoint: str, params: dict | None = None):
    """מחזיר response list (או [] אם אין/בעיה)."""
    if DEMO_MODE:
        return []
    try:
        r = requests.get(f"{BASE_URL}/{endpoint}", headers=HEADERS, params=params, timeout=20)
        data = r.json()
        return data.get("response", [])
    except Exception:
        return []

# =====================
# MATH / ANALYSIS
# =====================
def poisson_prob(lmbd: float, goals: int) -> float:
    return (math.exp(-lmbd) * (lmbd ** goals)) / math.factorial(goals)

def over_probability(avg_goals: float, line: float = 2.5) -> float:
    # P(total > line) ~ 1 - P(total <= floor(line))
    cutoff = int(line)
    p_leq = 0.0
    for g in range(0, cutoff + 1):
        p_leq += poisson_prob(avg_goals, g)
    return max(0.0, min(1.0, 1.0 - p_leq))

def safe_float(x, default=0.0):
    try:
        if x is None:
            return default
        return float(x)
    except Exception:
        return default

# =====================
# API-FOOTBALL DATA
# =====================
def get_fixtures_today():
    today = datetime.date.today().strftime("%Y-%m-%d")
    return api_get("fixtures", {"date": today})

def get_team_stats(team_id: int, league_id: int, season: int):
    # מחזיר dict סטטיסטיקה או None
    res = api_get("teams/statistics", {"team": team_id, "league": league_id, "season": season})
    return res[0] if res else None

def get_h2h(home_id: int, away_id: int, last: int = 10):
    return api_get("fixtures/headtohead", {"h2h": f"{home_id}-{away_id}", "last": last})

# =====================
# ANALYST ENGINE
# =====================
def analyze_match_from_api_fixture(fx):
    home = fx["teams"]["home"]
    away = fx["teams"]["away"]
    league = fx["league"]

    league_id = league["id"]
    season = league["season"]

    home_stats = get_team_stats(home["id"], league_id, season)
    away_stats = get_team_stats(away["id"], league_id, season)

    # אם אין סטטיסטיקות (קורה לפעמים) נשתמש בערכי בסיס כדי לא להיתקע
    home_goals_for = 1.2
    away_goals_for = 1.1
    if home_stats:
        home_goals_for = safe_float(home_stats["goals"]["for"]["average"]["total"], 1.2)
    if away_stats:
        away_goals_for = safe_float(away_stats["goals"]["for"]["average"]["total"], 1.1)

    # H2H אמיתי (אם יש)
    h2h = get_h2h(home["id"], away["id"], last=10)
    h2h_avg_goals = None
    if h2h:
        total_goals = 0
        count = 0
        for m in h2h:
            g_home = m.get("goals", {}).get("home", None)
            g_away = m.get("goals", {}).get("away", None)
            if g_home is not None and g_away is not None:
                total_goals += (g_home + g_away)
                count += 1
        if count > 0:
            h2h_avg_goals = total_goals / count

    # סגנון ליגה בסיסי (אפשר לשפר בהמשך) – כרגע נרכך לפי שערים ממוצעים של הקבוצות
    avg_goals = home_goals_for + away_goals_for
    if h2h_avg_goals is not None:
        avg_goals = 0.7 * avg_goals + 0.3 * h2h_avg_goals

    over25 = over_probability(avg_goals, 2.5)
    over15 = over_probability(avg_goals, 1.5)

    # BTTS קירוב פשוט: אם לשתי הקבוצות ממוצע > ~0.9 אז סיכוי עולה
    btts_est = max(0.0, min(1.0, (min(home_goals_for, away_goals_for) / max(home_goals_for, away_goals_for)) * 0.9 + 0.1))

    # Team to score (קירוב)
    home_score = max(0.0, min(1.0, home_goals_for / 2.2))
    away_score = max(0.0, min(1.0, away_goals_for / 2.2))

    # 1X2 קירוב גס (ללא Elo אמיתי כרגע)
    if home_goals_for > away_goals_for * 1.15:
        win_pick = "Home Win"
    elif away_goals_for > home_goals_for * 1.15:
        win_pick = "Away Win"
    else:
        win_pick = "Double Chance (1X)"

    recs = []

    # בוחרים “חזקים” לפי ספים
    if over25 >= 0.62:
        recs.append(("Over 2.5", over25))
    elif over15 >= 0.78:
        recs.append(("Over 1.5", over15))

    if btts_est >= 0.58:
        recs.append(("BTTS (Yes)", btts_est))

    # Team to score
    if home_score >= 0.70:
        recs.append(("Home to Score", home_score))
    if away_score >= 0.70:
        recs.append(("Away to Score", away_score))

    # Double chance / win
    recs.append((win_pick, 0.55))

    # קרנות/כובש – תלוי דאטה/odds, כרגע מסומן כ”מוכן להרחבה”
    # recs.append(("Corners (coming soon)", 0.0))
    # recs.append(("Anytime Goalscorer (needs odds/player)", 0.0))

    # ממיר ל-Top recommendation
    recs_sorted = sorted(recs, key=lambda x: x[1], reverse=True)
    top_bet, top_prob = recs_sorted[0]
    confidence = round(top_prob * 100, 1)

    return {
        "match": f'{home["name"]} vs {away["name"]}',
        "league": f'{league.get("name","")}',
        "top_bet": top_bet,
        "confidence": confidence,
        "all_recs": recs_sorted,
        "avg_goals": round(avg_goals, 2),
        "h2h_used": h2h_avg_goals is not None,
    }

# =====================
# BET BUILDER
# =====================
def bet_builder(selected_matches):
    # מכפלה של הסתברויות של הבחירה העליונה (פשטני אבל נותן אינדיקציה)
    p = 1.0
    for m in selected_matches:
        p *= (m["confidence"] / 100.0)
    hit_rate = round(p * 100, 1)

    # רמות סיכון
    n = len(selected_matches)
    if n <= 3:
        risk = "נמוך"
    elif n <= 6:
        risk = "בינוני"
    else:
        risk = "גבוה"

    return {"matches": n, "hit_rate": hit_rate, "risk": risk}

# =====================
# UI
# =====================
st.set_page_config(page_title="Football Analyst", layout="wide")
st.title("⚽ אנליסט כדורגל חכם להימורים")

with st.expander("סטטוס מערכת", expanded=False):
    st.write("API KEY מוגדר?" , "✅ כן" if not DEMO_MODE else "❌ לא (מצב דמו)")
    st.write("טיפ: ב-Streamlit → Manage app → Settings → Secrets הוסף:")
    st.code('APISPORTS_KEY = "YOUR_KEY_HERE"', language="toml")

fixtures = get_fixtures_today()

if not fixtures:
    st.warning("כרגע אין משחקים שנמשכו מה-API. אם עוד אין לך מפתח — זה תקין. מצב דמו פעיל עם משחקי דוגמה.")
    demo = [
        {"match": "Barcelona vs Sevilla", "league": "La Liga", "top_bet": "Over 1.5", "confidence": 79.0, "all_recs":[("Over 1.5",0.79),("BTTS (Yes)",0.60),("Double Chance (1X)",0.55)], "avg_goals": 2.65, "h2h_used": False},
        {"match": "Chelsea vs Everton", "league": "Premier League", "top_bet": "Double Chance (1X)", "confidence": 61.0, "all_recs":[("Double Chance (1X)",0.61),("Under 2.5",0.58)], "avg_goals": 2.25, "h2h_used": False},
        {"match": "Maccabi Tel Aviv vs Hapoel Haifa", "league": "Israel Ligat Ha'Al", "top_bet": "Home to Score", "confidence": 74.0, "all_recs":[("Home to Score",0.74),("Over 1.5",0.77)], "avg_goals": 2.45, "h2h_used": False},
    ]
    analyses = demo
else:
    analyses = []
    st.success(f"נמשכו {len(fixtures)} משחקים להיום.")
    for fx in fixtures:
        try:
            analyses.append(analyze_match_from_api_fixture(fx))
        except Exception:
            # לא נופלים – פשוט מדלגים
            pass

# ===== Display matches =====
st.subheader("📌 משחקים והמלצות")
for a in analyses:
    with st.expander(f'{a["match"]}  —  ⭐ {a["top_bet"]}  ({a["confidence"]}%)'):
        st.write("ליגה:", a.get("league", ""))
        st.write("ממוצע שערים מחושב:", a.get("avg_goals", ""))
        st.write("השתמש ב-H2H:", "✅ כן" if a.get("h2h_used") else "❌ לא")
        st.write("המלצות (מהחזק לחלש):")
        for bet, prob in a["all_recs"]:
            st.write(f"- {bet}  —  {round(prob*100,1)}%")

# ===== Bet slip builder =====
st.divider()
st.header("🧾 בניית טופס חכם")

selected = st.multiselect(
    "בחר משחקים לטופס",
    analyses,
    format_func=lambda x: x["match"]
)

col1, col2, col3 = st.columns(3)
if selected:
    summary = bet_builder(selected)
    col1.metric("מספר משחקים", summary["matches"])
    col2.metric("אחוז פגיעה משוער", f'{summary["hit_rate"]}%')
    col3.metric("רמת סיכון", summary["risk"])
else:
    col1.metric("מספר משחקים", "0")
    col2.metric("אחוז פגיעה משוער", "-")
    col3.metric("רמת סיכון", "-")
