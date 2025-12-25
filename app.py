import streamlit as st
import datetime
import math
from dataclasses import dataclass
from typing import List, Dict, Tuple

# =====================
# PAGE CONFIG + STYLE
# =====================
st.set_page_config(page_title="אנליסט כדורגל חכם", layout="wide")

st.markdown("""
<style>
    .big-title { font-size: 40px; font-weight: 800; }
    .subtle { color: #888; }
    .chip { display:inline-block; padding: 4px 10px; border-radius: 999px; font-size: 12px; margin-right: 6px; }
    .chip-strong { background: #e8fff1; border: 1px solid #b6f2cd; }
    .chip-mid { background: #fff7e6; border: 1px solid #ffe0a6; }
    .chip-risk { background: #ffecec; border: 1px solid #ffb3b3; }
    .card { border: 1px solid #eee; border-radius: 14px; padding: 14px 16px; margin-bottom: 12px; background: white; }
    .row { display:flex; justify-content:space-between; align-items:center; gap:12px; }
    .muted { color:#666; font-size: 13px; }
</style>
""", unsafe_allow_html=True)

# =====================
# CORE MATH
# =====================
def poisson_prob(lmbd: float, goals: int) -> float:
    return (math.exp(-lmbd) * (lmbd ** goals)) / math.factorial(goals)

def over_probability(avg_goals: float, line: float) -> float:
    cutoff = int(line)
    p_leq = 0.0
    for g in range(0, cutoff + 1):
        p_leq += poisson_prob(avg_goals, g)
    return max(0.0, min(1.0, 1.0 - p_leq))

def clamp(x: float, lo=0.0, hi=1.0) -> float:
    return max(lo, min(hi, x))

# =====================
# DATA MODELS
# =====================
@dataclass
class TeamProfile:
    name: str
    goals_for: float           # ממוצע שערים
    goals_against: float       # ממוצע ספיגה
    form_points_5: int         # נק' ב-5 אחרונים (0-15)
    corners_for: float         # קרנות למשחק
    corners_against: float     # קרנות נגד
    home_adv: float = 0.10     # יתרון ביתיות קטן (לדמו)

@dataclass
class MatchItem:
    league: str
    kickoff: str
    home: TeamProfile
    away: TeamProfile

# =====================
# DEMO DATA (עד שיגיע API)
# =====================
def demo_matches() -> List[MatchItem]:
    # אפשר לשנות/להוסיף ידנית פה בקלות
    return [
        MatchItem(
            league="La Liga",
            kickoff="21:00",
            home=TeamProfile("Barcelona", 2.05, 0.95, 12, 6.4, 3.7),
            away=TeamProfile("Sevilla", 1.25, 1.35, 8, 4.9, 5.1),
        ),
        MatchItem(
            league="Premier League",
            kickoff="19:30",
            home=TeamProfile("Chelsea", 1.55, 1.15, 10, 6.0, 4.2),
            away=TeamProfile("Everton", 1.05, 1.25, 7, 4.3, 5.5),
        ),
        MatchItem(
            league="Israel Ligat Ha'Al",
            kickoff="20:15",
            home=TeamProfile("Maccabi Tel Aviv", 1.75, 0.85, 13, 6.2, 3.9),
            away=TeamProfile("Hapoel Haifa", 1.10, 1.30, 6, 4.4, 5.3),
        ),
    ]

# =====================
# ANALYST ENGINE (חיזוק)
# =====================
def expected_total_goals(m: MatchItem) -> float:
    # ממוצע שערים צפוי: התקפה מול הגנה + איזון
    # בסיס: (הבקעה בית + ספיגה חוץ)/2 + (הבקעה חוץ + ספיגה בית)/2
    home_part = (m.home.goals_for + m.away.goals_against) / 2
    away_part = (m.away.goals_for + m.home.goals_against) / 2

    # יתרון ביתיות קטן: מעלה את ההבקעה הביתית קצת
    home_part *= (1 + m.home.home_adv)

    # מומנטום (5 משחקים): כל נקודה מעל 7 מוסיפה מעט, מתחת מורידה מעט
    form_boost = ((m.home.form_points_5 - 7) - (m.away.form_points_5 - 7)) * 0.02
    total = (home_part + away_part) * (1 + form_boost)

    return max(0.8, min(4.2, total))

def btts_estimate(m: MatchItem) -> float:
    # אם לשתי הקבוצות יש מעל 1.0 שער למשחק וסופגות לא מעט -> BTTS עולה
    base = (min(m.home.goals_for, m.away.goals_for) / max(m.home.goals_for, m.away.goals_for)) * 0.8 + 0.1
    defense_factor = ((m.home.goals_against + m.away.goals_against) / 2) / 1.4
    return clamp(base * clamp(defense_factor, 0.7, 1.2), 0.15, 0.85)

def win_side_estimate(m: MatchItem) -> Tuple[str, float]:
    # הערכה גסה לצד חזק יותר: התקפה-ספיגה + מומנטום
    home_strength = (m.home.goals_for - m.home.goals_against) + (m.home.form_points_5 / 15) * 0.6 + 0.15
    away_strength = (m.away.goals_for - m.away.goals_against) + (m.away.form_points_5 / 15) * 0.6

    diff = home_strength - away_strength
    if diff >= 0.35:
        return ("Home Win", clamp(0.55 + diff * 0.25, 0.55, 0.78))
    if diff <= -0.35:
        return ("Away Win", clamp(0.55 + (-diff) * 0.25, 0.55, 0.78))
    # קרוב -> דאבל צ'אנס
    return ("Double Chance (1X)", clamp(0.60 + diff * 0.10, 0.58, 0.72))

def corners_estimate(m: MatchItem) -> Tuple[str, float]:
    # קרנות: סכום קרנות בעד / נגד
    est_total = (m.home.corners_for + m.away.corners_for + m.home.corners_against + m.away.corners_against) / 2
    # קו דמו
    line = 8.5
    prob_over = clamp((est_total - line) * 0.10 + 0.55, 0.35, 0.75)
    pick = "Over 8.5 Corners" if prob_over >= 0.55 else "Under 10.5 Corners"
    prob = prob_over if pick.startswith("Over") else clamp(0.65 - (prob_over - 0.55), 0.40, 0.70)
    return (pick, prob)

def risk_label(conf: float) -> str:
    if conf >= 74:
        return "חזק"
    if conf >= 62:
        return "בינוני"
    return "מסוכן"

def analyze_match(m: MatchItem) -> Dict:
    total_goals = expected_total_goals(m)
    p_over25 = over_probability(total_goals, 2.5)
    p_over15 = over_probability(total_goals, 1.5)

    btts = btts_estimate(m)
    win_pick, win_prob = win_side_estimate(m)
    corners_pick, corners_prob = corners_estimate(m)

    # המלצות מועמדות (מה שנחשב “הכי חזק”)
    candidates = [
        ("Over 2.5", p_over25),
        ("Over 1.5", p_over15),
        ("BTTS (Yes)", btts),
        (win_pick, win_prob),
        (corners_pick, corners_prob),
        ("Home to Score", clamp(m.home.goals_for / 2.1, 0.45, 0.82)),
        ("Away to Score", clamp(m.away.goals_for / 2.1, 0.40, 0.78)),
    ]
    candidates = sorted(candidates, key=lambda x: x[1], reverse=True)

    top_bet, top_prob = candidates[0]
    confidence = round(top_prob * 100, 1)

    return {
        "league": m.league,
        "kickoff": m.kickoff,
        "match": f"{m.home.name} vs {m.away.name}",
        "home": m.home.name,
        "away": m.away.name,
        "expected_total_goals": round(total_goals, 2),
        "top_bet": top_bet,
        "confidence": confidence,
        "risk": risk_label(confidence),
        "all_recs": [(b, round(p * 100, 1)) for b, p in candidates[:5]],
    }

# =====================
# BET BUILDER
# =====================
def build_slip(analyses: List[Dict]) -> Dict:
    p = 1.0
    for a in analyses:
        p *= (a["confidence"] / 100.0)
    hit = round(p * 100, 2)

    n = len(analyses)
    if n <= 3:
        risk = "נמוך"
    elif n <= 6:
        risk = "בינוני"
    else:
        risk = "גבוה"
    return {"n": n, "hit": hit, "risk": risk}

def auto_build(analyses: List[Dict], mode: str) -> List[Dict]:
    # בוחר משחקים לפי confidence
    sorted_a = sorted(analyses, key=lambda x: x["confidence"], reverse=True)
    if mode == "3 חזקים":
        return sorted_a[:3]
    if mode == "6 סיכון נמוך":
        # לוקחים 6 עם ביטחון סביר
        return [a for a in sorted_a if a["confidence"] >= 62][:6] or sorted_a[:6]
    if mode == "10 אגרסיבי":
        return sorted_a[:10]
    return sorted_a[:3]

# =====================
# UI
# =====================
st.markdown('<div class="big-title">⚽ אנליסט כדורגל חכם להימורים</div>', unsafe_allow_html=True)
st.markdown('<div class="subtle">עד שה-API יתחבר — אנחנו עובדים במצב דמו עם נתוני דוגמה חזקים ומפתחים את האנליסט והעיצוב.</div>', unsafe_allow_html=True)

# Sidebar controls
st.sidebar.header("🎛 שליטה")
today = datetime.date.today().strftime("%d/%m/%Y")
st.sidebar.write(f"📅 היום: {today}")

league_filter = st.sidebar.multiselect(
    "סינון ליגות",
    options=["La Liga", "Premier League", "Israel Ligat Ha'Al"],
    default=["La Liga", "Premier League", "Israel Ligat Ha'Al"],
)

search = st.sidebar.text_input("חיפוש קבוצה/משחק", "")

auto_mode = st.sidebar.selectbox("טופס אוטומטי", ["כבוי", "3 חזקים", "6 סיכון נמוך", "10 אגרסיבי"])

# Data
matches = demo_matches()
analyses_all = [analyze_match(m) for m in matches]

# Filter
analyses = []
for a in analyses_all:
    if a["league"] not in league_filter:
        continue
    if search.strip():
        if search.lower() not in a["match"].lower():
            continue
    analyses.append(a)

# Header metrics
colA, colB, colC, colD = st.columns(4)
colA.metric("מס' משחקים מוצגים", len(analyses))
colB.metric("ממוצע ביטחון", f'{round(sum(x["confidence"] for x in analyses)/max(1,len(analyses)),1)}%')
colC.metric("חזקים (>=74%)", sum(1 for x in analyses if x["confidence"] >= 74))
colD.metric("מסוכנים (<62%)", sum(1 for x in analyses if x["confidence"] < 62))

st.divider()

# Auto build slip
selected_for_slip = []
if auto_mode != "כבוי":
    selected_for_slip = auto_build(analyses, auto_mode)
    st.info(f"נבנה טופס אוטומטי: **{auto_mode}** (אפשר לשנות ידנית למטה)")

# Matches list
st.subheader("📌 משחקים והמלצות")
for a in analyses:
    risk = a["risk"]
    chip_class = "chip-strong" if risk == "חזק" else "chip-mid" if risk == "בינוני" else "chip-risk"
    st.markdown(f"""
    <div class="card">
      <div class="row">
        <div>
          <div style="font-size:18px;font-weight:700;">{a["match"]}</div>
          <div class="muted">{a["league"]} • שעה: {a["kickoff"]} • שערים צפויים: {a["expected_total_goals"]}</div>
        </div>
        <div style="text-align:right;">
          <span class="chip {chip_class}">{risk}</span>
          <div style="font-size:16px;font-weight:700;">⭐ {a["top_bet"]}</div>
          <div class="muted">ביטחון: {a["confidence"]}%</div>
        </div>
      </div>
    </div>
    """, unsafe_allow_html=True)

    with st.expander("לראות עוד המלצות"):
        for bet, prob in a["all_recs"]:
            st.write(f"- **{bet}** — {prob}%")

# Manual slip
st.divider()
st.header("🧾 בניית טופס חכם")

choices = st.multiselect(
    "בחר משחקים לטופס ידנית",
    analyses,
    default=selected_for_slip,
    format_func=lambda x: f'{x["match"]} — {x["top_bet"]} ({x["confidence"]}%)'
)

if choices:
    slip = build_slip(choices)
    c1, c2, c3 = st.columns(3)
    c1.metric("מספר משחקים", slip["n"])
    c2.metric("אחוז פגיעה משוער", f'{slip["hit"]}%')
    c3.metric("רמת סיכון", slip["risk"])
    st.success("הטופס שלך:")
    for i, a in enumerate(choices, 1):
        st.write(f'{i}. **{a["match"]}** — ⭐ {a["top_bet"]} ({a["confidence"]}%)')
else:
    st.warning("בחר לפחות משחק אחד כדי לבנות טופס.")
