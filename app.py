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
    goals_for: float
    goals_against: float
    form_points_5: int         # 0-15
    corners_for: float
    corners_against: float
    home_adv: float = 0.10

@dataclass
class MatchItem:
    league: str
    kickoff: str
    home: TeamProfile
    away: TeamProfile

# =====================
# DEMO DATA
# =====================
def demo_matches() -> List[MatchItem]:
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
# BET TYPES
# =====================
BET_TYPES = [
    "Home Win",
    "Draw",
    "Away Win",
    "Double Chance (1X)",
    "Double Chance (X2)",
    "Double Chance (12)",
    "Over 0.5",
    "Over 1.5",
    "Over 2.5",
    "Under 2.5",
    "BTTS (Yes)",
    "BTTS (No)",
    "Home to Score",
    "Away to Score",
    "Over 8.5 Corners",
    "Under 10.5 Corners",
]

# =====================
# ANALYST ENGINE
# =====================
def expected_total_goals(m: MatchItem) -> float:
    home_part = (m.home.goals_for + m.away.goals_against) / 2
    away_part = (m.away.goals_for + m.home.goals_against) / 2
    home_part *= (1 + m.home.home_adv)
    form_boost = ((m.home.form_points_5 - 7) - (m.away.form_points_5 - 7)) * 0.02
    total = (home_part + away_part) * (1 + form_boost)
    return max(0.8, min(4.2, total))

def btts_estimate(m: MatchItem) -> float:
    base = (min(m.home.goals_for, m.away.goals_for) / max(m.home.goals_for, m.away.goals_for)) * 0.8 + 0.1
    defense_factor = ((m.home.goals_against + m.away.goals_against) / 2) / 1.4
    return clamp(base * clamp(defense_factor, 0.7, 1.2), 0.15, 0.85)

def win_side_estimate(m: MatchItem) -> Tuple[str, float]:
    home_strength = (m.home.goals_for - m.home.goals_against) + (m.home.form_points_5 / 15) * 0.6 + 0.15
    away_strength = (m.away.goals_for - m.away.goals_against) + (m.away.form_points_5 / 15) * 0.6
    diff = home_strength - away_strength
    if diff >= 0.35:
        return ("Home Win", clamp(0.55 + diff * 0.25, 0.55, 0.78))
    if diff <= -0.35:
        return ("Away Win", clamp(0.55 + (-diff) * 0.25, 0.55, 0.78))
    return ("Double Chance (1X)", clamp(0.60 + diff * 0.10, 0.58, 0.72))

def corners_estimate(m: MatchItem) -> Tuple[str, float]:
    est_total = (m.home.corners_for + m.away.corners_for + m.home.corners_against + m.away.corners_against) / 2
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

def build_probability_table(m: MatchItem) -> Dict[str, float]:
    tg = expected_total_goals(m)
    p_over05 = over_probability(tg, 0.5)
    p_over15 = over_probability(tg, 1.5)
    p_over25 = over_probability(tg, 2.5)
    p_under25 = clamp(1.0 - p_over25, 0.05, 0.95)

    btts_yes = btts_estimate(m)
    btts_no = clamp(1.0 - btts_yes, 0.10, 0.90)

    win_pick, win_prob = win_side_estimate(m)

    # הערכת 1X2 בסיסית (דמו)
    if win_pick == "Home Win":
        p_home = win_prob
        p_draw = clamp((1 - p_home) * 0.45, 0.10, 0.35)
        p_away = clamp(1 - p_home - p_draw, 0.05, 0.40)
    elif win_pick == "Away Win":
        p_away = win_prob
        p_draw = clamp((1 - p_away) * 0.45, 0.10, 0.35)
        p_home = clamp(1 - p_away - p_draw, 0.05, 0.40)
    else:
        p_home = clamp(win_prob * 0.55, 0.25, 0.55)
        p_draw = clamp(win_prob * 0.35, 0.18, 0.38)
        p_away = clamp(1 - p_home - p_draw, 0.10, 0.45)

    p_1x = clamp(p_home + p_draw, 0.45, 0.90)
    p_x2 = clamp(p_away + p_draw, 0.45, 0.90)
    p_12 = clamp(p_home + p_away, 0.50, 0.92)

    p_home_score = clamp(m.home.goals_for / 2.1, 0.45, 0.82)
    p_away_score = clamp(m.away.goals_for / 2.1, 0.40, 0.78)

    corners_pick, corners_prob = corners_estimate(m)
    p_over_corners = corners_prob if corners_pick.startswith("Over") else clamp(1 - corners_prob, 0.30, 0.70)
    p_under_corners = clamp(1 - p_over_corners, 0.30, 0.70)

    return {
        "Home Win": p_home,
        "Draw": p_draw,
        "Away Win": p_away,
        "Double Chance (1X)": p_1x,
        "Double Chance (X2)": p_x2,
        "Double Chance (12)": p_12,
        "Over 0.5": p_over05,
        "Over 1.5": p_over15,
        "Over 2.5": p_over25,
        "Under 2.5": p_under25,
        "BTTS (Yes)": btts_yes,
        "BTTS (No)": btts_no,
        "Home to Score": p_home_score,
        "Away to Score": p_away_score,
        "Over 8.5 Corners": p_over_corners,
        "Under 10.5 Corners": p_under_corners,
    }

def recommend_top(prob_table: Dict[str, float]) -> Tuple[str, float, List[Tuple[str, float]]]:
    items = sorted(prob_table.items(), key=lambda x: x[1], reverse=True)
    top_bet, top_p = items[0]
    return top_bet, top_p, items[:6]

def analyze_match(m: MatchItem) -> Dict:
    probs = build_probability_table(m)
    top_bet, top_p, top_list = recommend_top(probs)
    conf = round(top_p * 100, 1)
    return {
        "league": m.league,
        "kickoff": m.kickoff,
        "match": f"{m.home.name} vs {m.away.name}",
        "expected_total_goals": round(expected_total_goals(m), 2),
        "top_bet": top_bet,
        "confidence": conf,
        "risk": risk_label(conf),
        "prob_table": probs,
        "top_list": [(b, round(p * 100, 1)) for b, p in top_list],
    }

# =====================
# ODDS + SLIP
# =====================
def combined_odds(legs: List[Dict]) -> float:
    out = 1.0
    for leg in legs:
        out *= float(leg["odds"])
    return out

def implied_probability_from_odds(legs: List[Dict]) -> float:
    p = 1.0
    for leg in legs:
        p *= (1.0 / float(leg["odds"]))
    return clamp(p, 0.0, 1.0)

def analyst_probability(legs: List[Dict]) -> float:
    p = 1.0
    for leg in legs:
        p *= float(leg["model_p"])
    return clamp(p, 0.0, 1.0)

# =====================
# UI
# =====================
st.markdown('<div class="big-title">⚽ אנליסט כדורגל חכם להימורים</div>', unsafe_allow_html=True)
st.markdown('<div class="subtle">מצב דמו עד שה-API יתחבר. אתה בונה טופס עם יחס אמיתי מהאינטרנט ורואה אם זה משתלם.</div>', unsafe_allow_html=True)

# Sidebar
st.sidebar.header("🎛 שליטה")
today = datetime.date.today().strftime("%d/%m/%Y")
st.sidebar.write(f"📅 היום: {today}")

leagues_all = ["La Liga", "Premier League", "Israel Ligat Ha'Al"]
league_filter = st.sidebar.multiselect("סינון ליגות", options=leagues_all, default=leagues_all)
search = st.sidebar.text_input("חיפוש קבוצה/משחק", "")

# Load + analyze
matches = demo_matches()
analyses_all = [analyze_match(m) for m in matches]

analyses = []
for a in analyses_all:
    if a["league"] not in league_filter:
        continue
    if search.strip() and (search.lower() not in a["match"].lower()):
        continue
    analyses.append(a)

# Metrics
colA, colB, colC, colD = st.columns(4)
colA.metric("מס' משחקים מוצגים", len(analyses))
avg_conf = round(sum(x["confidence"] for x in analyses) / max(1, len(analyses)), 1)
colB.metric("ממוצע ביטחון", f"{avg_conf}%")
colC.metric("חזקים (>=74%)", sum(1 for x in analyses if x["confidence"] >= 74))
colD.metric("מסוכנים (<62%)", sum(1 for x in analyses if x["confidence"] < 62))

st.divider()

# Matches + build slip legs
st.subheader("📌 משחקים והמלצות (בחר הימור + הזן Odds)")

legs: List[Dict] = []
for idx, a in enumerate(analyses):
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

    c1, c2, c3, c4 = st.columns([1.6, 1.2, 1.0, 1.2])

    default_bet = a["top_bet"]
    bet_choice = c1.selectbox(
        "סוג הימור",
        options=BET_TYPES,
        index=BET_TYPES.index(default_bet) if default_bet in BET_TYPES else 0,
        key=f"bet_{idx}"
    )

    model_p = a["prob_table"].get(bet_choice, 0.50)
    c2.metric("הערכת הצלחה (אנליסט)", f"{round(model_p*100,1)}%")

    odds = c3.number_input(
        "Odds (יחס)",
        min_value=1.01,
        value=1.70,
        step=0.01,
        format="%.2f",
        key=f"odds_{idx}"
    )

    add_to_slip = c4.checkbox("הוסף לטופס", value=False, key=f"add_{idx}")

    with st.expander("עוד המלצות"):
        for b, p in a["top_list"]:
            st.write(f"- **{b}** — {p}%")

    if add_to_slip:
        legs.append({
            "match": a["match"],
            "league": a["league"],
            "pick": bet_choice,
            "odds": float(odds),
            "model_p": float(model_p),
        })

st.divider()

# Slip summary + copy/export
st.header("🧾 הטופס שלך + יחס מהאינטרנט")

if not legs:
    st.warning("סמן 'הוסף לטופס' לפחות על משחק אחד.")
else:
    stake = st.number_input("כמה אתה שם בטופס? (₪)", min_value=1.0, value=20.0, step=1.0, format="%.0f")

    total_odds = combined_odds(legs)
    model_p = analyst_probability(legs)
    implied_p = implied_probability_from_odds(legs)
    edge = model_p - implied_p

    potential_return = stake * total_odds
    profit = potential_return - stake

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("מספר משחקים", len(legs))
    c2.metric("יחס כולל", f"{total_odds:.2f}")
    c3.metric("החזר פוטנציאלי", f"₪{potential_return:.2f}")
    c4.metric("רווח פוטנציאלי", f"₪{profit:.2f}")

    c5, c6, c7 = st.columns(3)
    c5.metric("הצלחה משוערת (אנליסט)", f"{model_p*100:.1f}%")
    c6.metric("הצלחה משתמעת מהיחסים", f"{implied_p*100:.1f}%")
    c7.metric("Value (Edge)", f"{edge*100:.1f}%")

    if edge > 0.03:
        st.success("✅ לפי האנליסט יש פה Value.")
    elif edge < -0.03:
        st.error("⚠️ לפי האנליסט היחסים לא משתלמים.")
    else:
        st.info("ℹ️ גבולי — אין יתרון ברור.")

    st.subheader("📋 פירוט הטופס")
    for i, leg in enumerate(legs, 1):
        st.write(f'{i}. **{leg["match"]}** — {leg["pick"]} | יחס: **{leg["odds"]:.2f}** | סיכוי אנליסט: **{leg["model_p"]*100:.1f}%**')

    # ===== COPY / EXPORT =====
    st.divider()
    st.subheader("📋 העתקה/ייצוא הטופס")

    lines = []
    lines.append("טופס הימורים (נבנה באתר האנליסט)")
    lines.append(f"תאריך: {datetime.date.today().strftime('%d/%m/%Y')}")
    lines.append("")
    for i, leg in enumerate(legs, 1):
        lines.append(f"{i}. {leg['match']} — {leg['pick']} @ {leg['odds']:.2f}")
    lines.append("")
    lines.append(f"יחס כולל: {total_odds:.2f}")
    lines.append(f"סטייק: ₪{stake:.0f}")
    lines.append(f"החזר פוטנציאלי: ₪{potential_return:.2f}")
    lines.append(f"רווח פוטנציאלי: ₪{profit:.2f}")
    lines.append("")
    lines.append(f"הצלחה משוערת (אנליסט): {model_p*100:.1f}%")
    lines.append(f"הצלחה משתמעת מהיחסים: {implied_p*100:.1f}%")
    lines.append(f"Value (Edge): {edge*100:.1f}%")

    slip_text = "\n".join(lines)

    if st.button("📋 צור טקסט להעתקה"):
        st.text_area("העתק (Ctrl+A ואז Ctrl+C):", slip_text, height=220)

    st.download_button(
        "⬇️ הורד כקובץ TXT",
        data=slip_text.encode("utf-8"),
        file_name="bet_slip.txt",
        mime="text/plain"
    )

    st.caption("אזהרה: זה כלי עזר בלבד. בהימורים אין ודאות, והיחסים כוללים מרווח של סוכנויות.")
