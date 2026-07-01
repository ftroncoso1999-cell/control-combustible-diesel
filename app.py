import json
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path
from io import BytesIO
import textwrap

import pandas as pd
import streamlit as st
from streamlit_autorefresh import st_autorefresh
import altair as alt


APP_DIR = Path(__file__).parent
DATA_DIR = APP_DIR / "data"
DB_PATH = DATA_DIR / "registros_combustible.db"
CALIB_PATH = DATA_DIR / "calibracion.json"


st.set_page_config(
    page_title="Control Combustible",
    page_icon="⛽",
    layout="wide",
    initial_sidebar_state="collapsed",
)
st_autorefresh(interval=1000, key="reloj")

# =========================
# DATOS / CÁLCULOS
# =========================
def load_calibration():
    with open(CALIB_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def init_db():
    DATA_DIR.mkdir(exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS registros (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha_hora TEXT NOT NULL,
            estanque TEXT NOT NULL,
            nivel_cm REAL NOT NULL,
            volumen_l REAL NOT NULL,
            porcentaje REAL NOT NULL,
            estado_operacional TEXT NOT NULL,
            operador TEXT NOT NULL,
            observacion TEXT,
            estado_registro TEXT NOT NULL DEFAULT 'VÁLIDO',
            motivo_anulacion TEXT,
            fecha_anulacion TEXT
        )
        """
    )
    con.commit()
    con.close()


def get_connection():
    return sqlite3.connect(DB_PATH)


def normalize_cm(value: float):
    cm_int = int(value)
    mm = int(round((value - cm_int) * 10, 0))
    if mm == 10:
        cm_int += 1
        mm = 0
    return cm_int, mm


def lookup_liters(tank: str, nivel_cm: float, cal_data: dict):
    cm_int, mm = normalize_cm(nivel_cm)
    key = f"{cm_int}.{mm}"
    tank_table = cal_data["calibration"].get(tank, {})
    return tank_table.get(key), cm_int, mm


def calc_percentage(tank: str, liters: float, cal_data: dict):
    cfg = cal_data["config"][tank]
    min_l = cfg["min_liters"]
    max_l = cfg["max_liters"]
    pct = (liters - min_l) / (max_l - min_l)
    return max(0, min(1, pct))


def estado_operacional(pct: float):
    if pct >= 0.95:
        return "COMPLETO"
    if pct < 0.10:
        return "REQUIERE ABASTECIMIENTO"
    if pct < 0.20:
        return "NIVEL CRÍTICO"
    if pct < 0.50:
        return "NIVEL BAJO"
    return "NORMAL"


def color_by_pct(pct: float):
    if pct < 0.20:
        return "#ff3b30"
    if pct < 0.50:
        return "#ffc107"
    return "#54d143"


def status_css(pct: float):
    if pct < 0.20:
        return "critical"
    if pct < 0.50:
        return "low"
    return "ok"


def save_record(tank, nivel_cm, liters, pct, estado, operador, obs):
    con = get_connection()
    cur = con.cursor()
    cur.execute(
        """
        INSERT INTO registros (
            fecha_hora, estanque, nivel_cm, volumen_l, porcentaje,
            estado_operacional, operador, observacion, estado_registro
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'VÁLIDO')
        """,
        (
            datetime.now(ZoneInfo("America/Santiago")).strftime("%Y-%m-%d %H:%M:%S")
            tank,
            float(nivel_cm),
            float(liters),
            float(pct),
            estado,
            operador.strip(),
            obs.strip(),
        ),
    )
    con.commit()
    con.close()


def load_records(valid_only=False):
    con = get_connection()
    query = "SELECT * FROM registros ORDER BY fecha_hora DESC"
    if valid_only:
        query = "SELECT * FROM registros WHERE estado_registro = 'VÁLIDO' ORDER BY fecha_hora DESC"
    df = pd.read_sql_query(query, con)
    con.close()
    if not df.empty:
        df["fecha_hora"] = pd.to_datetime(df["fecha_hora"])
    return df


def annul_record(record_id: int, motivo: str):
    con = get_connection()
    cur = con.cursor()
    cur.execute(
        """
        UPDATE registros
        SET estado_registro = 'ANULADO',
            motivo_anulacion = ?,
            fecha_anulacion = ?
        WHERE id = ?
        """,
        (motivo.strip(), datetime.now().strftime("%Y-%m-%d %H:%M:%S"), int(record_id)),
    )
    con.commit()
    con.close()


def fmt_liters(v):
    return f"{v:,.0f}".replace(",", ".") + " L"


def fmt_pct(v):
    return f"{v*100:.1f}%".replace(".", ",")


def latest_by_tank():
    df = load_records(valid_only=True)
    latest = {}
    for tank_name in ["TKR", "TK1", "TK2"]:
        if df.empty:
            latest[tank_name] = None
        else:
            temp = df[df["estanque"] == tank_name].sort_values("fecha_hora")
            latest[tank_name] = None if temp.empty else temp.iloc[-1].to_dict()
    return latest


def default_state(tank_name):
    liters, _, _ = lookup_liters(tank_name, 0.0, cal_data)
    liters = liters or 0
    pct = calc_percentage(tank_name, liters, cal_data) if liters else 0
    return {
        "estanque": tank_name,
        "nivel_cm": 0.0,
        "volumen_l": liters,
        "porcentaje": pct,
        "estado_operacional": estado_operacional(pct),
    }


def max_liters(tank_name):
    return cal_data["config"][tank_name]["max_liters"]


# =========================
# TANQUES VISUALES HTML
# =========================
def vertical_tank(tank_name, pct, liters, nivel_cm, compact=False):
    pct100 = max(0, min(100, pct * 100))
    color = color_by_pct(pct)
    estado = estado_operacional(pct)
    cls = status_css(pct)
    compact_class = "compact" if compact else ""
    return f"""
    <div class="tank-visual-card {compact_class}">
        <div class="tank-visual-title">{tank_name}</div>
        <div class="vertical-layout">
            <div class="vertical-tank">
                <div class="vertical-liquid" style="height:{pct100:.1f}%; background:{color};"></div>
                <div class="vertical-wave" style="bottom:{pct100:.1f}%;"></div>
                <div class="vertical-shine"></div>
            </div>
            <div class="scale">
                <span>100%</span><span>75%</span><span>50%</span><span>25%</span><span>0%</span>
            </div>
        </div>
        <div class="tank-percent" style="color:{color};">{fmt_pct(pct)}</div>
        <div class="tank-cm">{nivel_cm:.1f} cm</div>
        <div class="status-badge {cls}">● {estado}</div>
        <div class="tank-liters">{fmt_liters(liters)}</div>
    </div>
    """


def horizontal_tank(tank_name, pct, liters, nivel_cm, compact=False):
    pct100 = max(0, min(100, pct * 100))
    color = color_by_pct(pct)
    estado = estado_operacional(pct)
    cls = status_css(pct)
    compact_class = "compact" if compact else ""
    return f"""
    <div class="tank-visual-card horizontal-card {compact_class}">
        <div class="tank-visual-title">{tank_name}</div>
        <div class="horizontal-layout">
            <div class="horizontal-tank">
                <div class="horizontal-liquid" style="width:{pct100:.1f}%; background:{color};"></div>
                <div class="horizontal-wave" style="left:{max(0, pct100-2):.1f}%;"></div>
                <div class="horizontal-shine"></div>
                <div class="tank-leg leg-left"></div>
                <div class="tank-leg leg-right"></div>
            </div>
            <div class="scale scale-horizontal">
                <span>100%</span><span>75%</span><span>50%</span><span>25%</span><span>0%</span>
            </div>
        </div>
        <div class="tank-percent" style="color:{color};">{fmt_pct(pct)}</div>
        <div class="tank-cm">{nivel_cm:.1f} cm</div>
        <div class="status-badge {cls}">● {estado}</div>
        <div class="tank-liters">{fmt_liters(liters)}</div>
    </div>
    """


def tank_visual(tank_name, pct, liters, nivel_cm, compact=False):
    if tank_name == "TKR":
        return horizontal_tank(tank_name, pct, liters, nivel_cm, compact=compact)
    return vertical_tank(tank_name, pct, liters, nivel_cm, compact=compact)


def state_from_row_or_default(tank_name, row):
    if row is None:
        row = default_state(tank_name)
    pct = float(row["porcentaje"])
    liters = float(row["volumen_l"])
    nivel = float(row["nivel_cm"])
    return pct, liters, nivel



def operational_state(latest):
    cards = []
    total = 0.0
    alarms = []

    for tank_name in ["TK1", "TK2", "TKR"]:
        row = latest.get(tank_name)
        if row is None:
            row = default_state(tank_name)

        pct = float(row["porcentaje"])
        liters = float(row["volumen_l"])
        nivel = float(row["nivel_cm"])
        estado = estado_operacional(pct)
        color = color_by_pct(pct)
        css = status_css(pct)

        total += liters

        if pct < 0.10:
            alarms.append(f"🚨 {tank_name}: REQUIERE ABASTECIMIENTO")
        elif pct < 0.20:
            alarms.append(f"🔴 {tank_name}: NIVEL CRÍTICO")
        elif pct < 0.50:
            alarms.append(f"🟡 {tank_name}: NIVEL BAJO")

        cards.append(
            f'<div class="op-card">'
            f'<div class="op-tank">{tank_name}</div>'
            f'<div class="op-status-dot" style="background:{color};"></div>'
            f'<div class="op-pct" style="color:{color};">{fmt_pct(pct)}</div>'
            f'<div class="op-liters">{fmt_liters(liters)}</div>'
            f'<div class="op-cm">{nivel:.1f} cm</div>'
            f'<div class="op-badge {css}">{estado}</div>'
            f'</div>'
        )

    if alarms:
        alarm_html = "".join([f'<div class="alarm-row">{a}</div>' for a in alarms])
        alarm_class = "alarm-active"
        alarm_title = "ALARMAS ACTIVAS"
    else:
        alarm_html = '<div class="alarm-row ok-line">✅ Sin alarmas activas</div>'
        alarm_class = "alarm-ok"
        alarm_title = "ESTADO GENERAL"

    return "".join(cards), total, alarm_html, alarm_class, alarm_title


def operational_dashboard_html(latest):
    cards_html, total, alarm_html, alarm_class, alarm_title = operational_state(latest)
    return (
        '<div class="op-dashboard">'
        '<div class="op-header">'
        '<div>'
        '<div class="op-title">DASHBOARD OPERACIONAL</div>'
        '<div class="op-subtitle">Vista rápida del estado actual de combustible por estanque</div>'
        '</div>'
        '<div class="op-total">'
        '<div class="op-total-label">TOTAL DISPONIBLE</div>'
        f'<div class="op-total-value">{fmt_liters(total)}</div>'
        '</div>'
        '</div>'
        '<div class="op-grid">'
        f'{cards_html}'
        f'<div class="op-alarm {alarm_class}">'
        f'<div class="op-alarm-title">{alarm_title}</div>'
        f'{alarm_html}'
        '</div>'
        '</div>'
        '</div>'
    )


def consumption_summary():
    df = load_records(valid_only=True)
    if df.empty:
        return {}, pd.DataFrame()

    df = df.sort_values("fecha_hora").copy()
    df["delta_litros"] = df.groupby("estanque")["volumen_l"].diff()
    df["consumo_litros"] = df["delta_litros"].apply(lambda x: abs(x) if pd.notna(x) and x < 0 else 0)
    df["reposicion_litros"] = df["delta_litros"].apply(lambda x: x if pd.notna(x) and x > 0 else 0)

    now = pd.Timestamp.now()
    periods = {
        "24h": now - pd.Timedelta(hours=24),
        "7d": now - pd.Timedelta(days=7),
        "30d": now - pd.Timedelta(days=30),
    }

    summary = {}
    for tank_name in ["TKR", "TK1", "TK2"]:
        tank_df = df[df["estanque"] == tank_name].copy()
        if tank_df.empty:
            summary[tank_name] = {
                "consumo_24h": 0,
                "consumo_7d": 0,
                "consumo_30d": 0,
                "ultima_variacion": 0,
                "tendencia": "SIN DATOS",
                "registros": 0,
            }
            continue

        last_delta = tank_df["delta_litros"].dropna()
        last_delta_value = float(last_delta.iloc[-1]) if not last_delta.empty else 0

        if last_delta_value < 0:
            tendencia = "BAJANDO"
        elif last_delta_value > 0:
            tendencia = "SUBIENDO / REPOSICIÓN"
        else:
            tendencia = "ESTABLE"

        summary[tank_name] = {
            "consumo_24h": float(tank_df[tank_df["fecha_hora"] >= periods["24h"]]["consumo_litros"].sum()),
            "consumo_7d": float(tank_df[tank_df["fecha_hora"] >= periods["7d"]]["consumo_litros"].sum()),
            "consumo_30d": float(tank_df[tank_df["fecha_hora"] >= periods["30d"]]["consumo_litros"].sum()),
            "ultima_variacion": last_delta_value,
            "tendencia": tendencia,
            "registros": int(len(tank_df)),
        }

    return summary, df


def consumption_dashboard_html():
    summary, _ = consumption_summary()

    if not summary:
        return (
            '<div class="consumption-panel">'
            '<div class="consumption-title">CONSUMO OPERACIONAL</div>'
            '<div class="consumption-empty">Aún no existen mediciones suficientes para calcular consumo.</div>'
            '</div>'
        )

    cards = []
    total_24 = 0
    total_7 = 0
    total_30 = 0

    for tank_name in ["TKR", "TK1", "TK2"]:
        item = summary[tank_name]
        total_24 += item["consumo_24h"]
        total_7 += item["consumo_7d"]
        total_30 += item["consumo_30d"]

        tendencia = item["tendencia"]
        if tendencia == "BAJANDO":
            trend_class = "trend-down"
            trend_icon = "▼"
        elif tendencia == "SUBIENDO / REPOSICIÓN":
            trend_class = "trend-up"
            trend_icon = "▲"
        elif tendencia == "ESTABLE":
            trend_class = "trend-stable"
            trend_icon = "▬"
        else:
            trend_class = "trend-none"
            trend_icon = "•"

        cards.append(
            f'<div class="cons-card">'
            f'<div class="cons-tank">{tank_name}</div>'
            f'<div class="cons-main">{fmt_liters(item["consumo_24h"])}</div>'
            f'<div class="cons-label">Consumo últimas 24 h</div>'
            f'<div class="cons-row"><span>7 días</span><b>{fmt_liters(item["consumo_7d"])}</b></div>'
            f'<div class="cons-row"><span>30 días</span><b>{fmt_liters(item["consumo_30d"])}</b></div>'
            f'<div class="cons-trend {trend_class}">{trend_icon} {tendencia}</div>'
            f'<div class="cons-small">Última variación: {fmt_liters(item["ultima_variacion"])}</div>'
            f'</div>'
        )

    return (
        '<div class="consumption-panel">'
        '<div class="consumption-header">'
        '<div>'
        '<div class="consumption-title">CONSUMO OPERACIONAL</div>'
        '<div class="consumption-sub">Calculado automáticamente por diferencia entre mediciones válidas consecutivas</div>'
        '</div>'
        '<div class="cons-total">'
        '<div class="cons-total-label">CONSUMO TOTAL 24 H</div>'
        f'<div class="cons-total-value">{fmt_liters(total_24)}</div>'
        '</div>'
        '</div>'
        '<div class="cons-grid">'
        f'{"".join(cards)}'
        '<div class="cons-total-card">'
        '<div class="cons-tank">TOTAL SISTEMA</div>'
        f'<div class="cons-row big"><span>24 h</span><b>{fmt_liters(total_24)}</b></div>'
        f'<div class="cons-row big"><span>7 días</span><b>{fmt_liters(total_7)}</b></div>'
        f'<div class="cons-row big"><span>30 días</span><b>{fmt_liters(total_30)}</b></div>'
        '<div class="cons-note">Solo considera bajas de volumen. Las reposiciones no se cuentan como consumo.</div>'
        '</div>'
        '</div>'
        '</div>'
    )


def consumption_table():
    _, df = consumption_summary()
    if df.empty:
        return df

    out = df[[
        "fecha_hora",
        "estanque",
        "nivel_cm",
        "volumen_l",
        "porcentaje",
        "delta_litros",
        "consumo_litros",
        "reposicion_litros",
        "operador",
        "observacion",
    ]].copy()

    out = out.sort_values("fecha_hora", ascending=False)
    return out



def prepare_export_data():
    df_all = load_records(valid_only=False)
    df_valid = load_records(valid_only=True)
    cons_df = consumption_table()

    latest = latest_by_tank()
    resumen_rows = []
    total_disponible = 0

    for tank_name in ["TKR", "TK1", "TK2"]:
        row = latest.get(tank_name)
        if row is None:
            row = default_state(tank_name)

        litros = float(row["volumen_l"])
        pct = float(row["porcentaje"])
        total_disponible += litros

        resumen_rows.append({
            "Estanque": tank_name,
            "Nivel cm": float(row["nivel_cm"]),
            "Volumen L": litros,
            "% llenado": pct,
            "Estado": estado_operacional(pct),
            "Fecha informe": datetime.now().strftime("%d-%m-%Y %H:%M"),
        })

    resumen_df = pd.DataFrame(resumen_rows)
    total_df = pd.DataFrame([{
        "Concepto": "Total combustible disponible",
        "Valor L": total_disponible,
        "Fecha informe": datetime.now().strftime("%d-%m-%Y %H:%M"),
    }])

    summary, _ = consumption_summary()
    consumo_rows = []
    for tank_name, item in summary.items():
        consumo_rows.append({
            "Estanque": tank_name,
            "Consumo 24h L": item["consumo_24h"],
            "Consumo 7d L": item["consumo_7d"],
            "Consumo 30d L": item["consumo_30d"],
            "Última variación L": item["ultima_variacion"],
            "Tendencia": item["tendencia"],
            "Registros": item["registros"],
        })
    consumo_resumen_df = pd.DataFrame(consumo_rows)

    return resumen_df, total_df, df_all, df_valid, cons_df, consumo_resumen_df


def make_excel_report():
    output = BytesIO()
    resumen_df, total_df, df_all, df_valid, cons_df, consumo_resumen_df = prepare_export_data()

    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        resumen_df.to_excel(writer, index=False, sheet_name="Resumen")
        total_df.to_excel(writer, index=False, sheet_name="Total disponible")
        consumo_resumen_df.to_excel(writer, index=False, sheet_name="Consumo resumen")
        df_valid.to_excel(writer, index=False, sheet_name="Registros validos")
        df_all.to_excel(writer, index=False, sheet_name="Historial completo")
        cons_df.to_excel(writer, index=False, sheet_name="Detalle consumos")

        wb = writer.book
        for ws in wb.worksheets:
            ws.freeze_panes = "A2"
            for cell in ws[1]:
                cell.font = cell.font.copy(bold=True)
            for col in ws.columns:
                max_len = 0
                col_letter = col[0].column_letter
                for cell in col:
                    try:
                        value_len = len(str(cell.value)) if cell.value is not None else 0
                        max_len = max(max_len, value_len)
                    except Exception:
                        pass
                ws.column_dimensions[col_letter].width = min(max_len + 3, 35)

    output.seek(0)
    return output.getvalue()


def make_csv_history(valid_only=True):
    df = load_records(valid_only=valid_only)
    return df.to_csv(index=False, sep=";", encoding="utf-8-sig").encode("utf-8-sig")


def export_panel_html():
    return (
        '<div class="export-panel">'
        '<div class="export-title">EXPORTACIÓN PROFESIONAL</div>'
        '<div class="export-sub">Descarga informes para respaldo, revisión operacional o envío a supervisión.</div>'
        '<div class="export-grid">'
        '<div class="export-card">'
        '<div class="export-card-title">Informe completo Excel</div>'
        '<div class="export-card-text">Incluye resumen, total disponible, consumos, registros válidos, historial completo y detalle de consumos.</div>'
        '</div>'
        '<div class="export-card">'
        '<div class="export-card-title">Historial CSV</div>'
        '<div class="export-card-text">Formato simple para análisis rápido, respaldo o carga en otros sistemas.</div>'
        '</div>'
        '<div class="export-card">'
        '<div class="export-card-title">Uso recomendado</div>'
        '<div class="export-card-text">Generar al cierre de turno, cierre diario o antes de una reunión operacional.</div>'
        '</div>'
        '</div>'
        '</div>'
    )


# =========================
# INICIO
# =========================
cal_data = load_calibration()
init_db()

# =========================
# ESTILO
# =========================
st.markdown(
    """
    <style>
        .block-container {
            padding-top: 1.0rem;
            padding-bottom: 2rem;
            max-width: 1450px;
        }

        .stApp {
            background:#0b0f17;
        }

        .top-banner {
            background: linear-gradient(90deg, #002B49 0%, #003B5C 100%);
            color:white;
            border-radius:14px;
            padding:22px 26px;
            box-shadow:0 4px 18px rgba(0,0,0,.25);
            margin-bottom:18px;
            display:flex;
            align-items:center;
            justify-content:space-between;
        }

        .top-title {
            font-size:32px;
            font-weight:900;
            letter-spacing:.3px;
        }

        .top-sub {
            font-size:16px;
            color:#BDD7EE;
            margin-top:6px;
            font-weight:700;
        }

        .top-time {
            font-size:17px;
            font-weight:800;
            color:#ffffff;
            text-align:right;
        }

        .info-strip {
            background:#EAF3FA;
            color:#1F2933;
            border:1px solid #A6A6A6;
            border-radius:10px;
            padding:12px 16px;
            font-size:16px;
            margin-bottom:18px;
        }

        .panel-card {
            background:#111722;
            border:1px solid #263241;
            border-radius:14px;
            padding:20px;
            box-shadow:0 2px 12px rgba(0,0,0,.25);
        }

        .panel-card h2, .panel-card h3 {
            color:white;
        }

        .section-title {
            background:#002B49;
            color:white;
            padding:10px 14px;
            border-radius:10px 10px 0 0;
            font-size:18px;
            font-weight:900;
            margin-top:18px;
        }

        .total-panel {
            background:linear-gradient(90deg,#002B49,#003B5C);
            color:white;
            border-radius:14px;
            padding:18px 22px;
            margin:18px 0;
            display:flex;
            justify-content:space-between;
            align-items:center;
            box-shadow:0 2px 12px rgba(0,0,0,.25);
        }

        .total-panel .label-total {
            font-size:20px;
            font-weight:900;
        }

        .total-panel .value-total {
            font-size:32px;
            font-weight:900;
        }

        .alert-panel {
            border-radius:12px;
            padding:12px 16px;
            margin:12px 0;
            font-weight:900;
            text-align:center;
        }

        .alert-ok {
            background:#E2F0D9;
            color:#0B7D3B;
        }

        .alert-low {
            background:#FFF2CC;
            color:#9A6A00;
        }

        .alert-critical {
            background:#FCE4D6;
            color:#C00000;
        }

        .tank-visual-card {
            background:linear-gradient(180deg,#172131,#0f1724);
            border:1px solid #35445a;
            border-radius:16px;
            padding:18px;
            text-align:center;
            box-shadow:inset 0 0 20px rgba(255,255,255,.03), 0 3px 12px rgba(0,0,0,.25);
            color:white;
            min-height:430px;
        }

        .tank-visual-card.compact {
            min-height:260px;
            padding:12px;
        }

        .tank-visual-title {
            font-size:24px;
            font-weight:900;
            color:white;
            margin-bottom:8px;
        }

        .tank-visual-card.compact .tank-visual-title {
            font-size:18px;
        }

        .vertical-layout {
            display:flex;
            justify-content:center;
            align-items:center;
            gap:14px;
            height:240px;
            margin:8px 0;
        }

        .compact .vertical-layout {
            height:150px;
            gap:8px;
        }

        .vertical-tank {
            position:relative;
            width:118px;
            height:220px;
            border-radius:58px 58px 22px 22px;
            background:linear-gradient(90deg,#17212d 0%,#d1dbe6 22%,#738190 48%,#f0f5fa 62%,#1a2531 100%);
            border:2px solid #9faab6;
            overflow:hidden;
            box-shadow: inset 0 10px 18px rgba(255,255,255,.18), inset 0 -16px 22px rgba(0,0,0,.45), 0 12px 22px rgba(0,0,0,.4);
        }

        .compact .vertical-tank {
            width:72px;
            height:138px;
            border-radius:36px 36px 14px 14px;
        }

        .vertical-liquid {
            position:absolute;
            bottom:0;
            left:0;
            width:100%;
            opacity:.92;
            box-shadow:0 -8px 18px rgba(84,209,67,.25);
        }

        .vertical-liquid::before {
            content:"";
            position:absolute;
            top:-8px;
            left:0;
            width:100%;
            height:14px;
            background:rgba(255,255,255,.26);
            border-radius:50%;
        }

        .vertical-wave {
            position:absolute;
            left:0;
            width:100%;
            height:12px;
            transform:translateY(7px);
            background:rgba(255,255,255,.22);
            border-radius:50%;
        }

        .vertical-shine {
            position:absolute;
            top:20px;
            left:30px;
            width:20px;
            height:155px;
            border-radius:14px;
            background:linear-gradient(180deg,rgba(255,255,255,.26),rgba(255,255,255,.02));
        }

        .horizontal-layout {
            display:flex;
            justify-content:center;
            align-items:center;
            gap:14px;
            height:230px;
            margin:8px 0;
        }

        .compact .horizontal-layout {
            height:135px;
        }

        .horizontal-tank {
            position:relative;
            width:410px;
            height:148px;
            border-radius:75px;
            background:linear-gradient(180deg,#d0d9e3 0%,#606f80 22%,#2a3443 50%,#101821 100%);
            border:2px solid #9ba7b4;
            overflow:hidden;
            box-shadow: inset 0 10px 20px rgba(255,255,255,.18), inset 0 -16px 22px rgba(0,0,0,.45), 0 12px 22px rgba(0,0,0,.4);
        }

        .compact .horizontal-tank {
            width:210px;
            height:82px;
            border-radius:41px;
        }

        .horizontal-liquid {
            position:absolute;
            bottom:0;
            left:0;
            height:48%;
            opacity:.94;
            box-shadow:0 -8px 18px rgba(84,209,67,.25);
        }

        .horizontal-liquid::before {
            content:"";
            position:absolute;
            top:-8px;
            left:0;
            right:0;
            height:13px;
            background:rgba(255,255,255,.25);
            border-radius:50%;
        }

        .horizontal-wave {
            position:absolute;
            bottom:47%;
            width:28px;
            height:70px;
            background:rgba(255,255,255,.20);
            border-radius:50%;
            transform:translateX(-20px);
        }

        .horizontal-shine {
            position:absolute;
            top:20px;
            left:65px;
            right:65px;
            height:34px;
            border-radius:50%;
            background:linear-gradient(180deg,rgba(255,255,255,.34),rgba(255,255,255,0));
        }

        .tank-leg {
            position:absolute;
            bottom:0;
            width:30px;
            height:28px;
            background:#1f2b38;
            border:1px solid #4b5c70;
        }

        .leg-left { left:72px; }
        .leg-right { right:72px; }

        .scale {
            height:220px;
            border-left:1px solid #d7e2ee;
            display:flex;
            flex-direction:column;
            justify-content:space-between;
            padding-left:8px;
            color:white;
            font-size:12px;
            font-weight:800;
        }

        .compact .scale {
            height:138px;
            font-size:10px;
        }

        .scale-horizontal {
            height:148px;
        }

        .compact .scale-horizontal {
            height:82px;
        }

        .tank-percent {
            font-size:46px;
            line-height:1.0;
            font-weight:950;
            margin-top:4px;
        }

        .compact .tank-percent {
            font-size:28px;
        }

        .tank-cm {
            font-size:16px;
            color:#f2f6fb;
            margin-top:4px;
        }

        .compact .tank-cm {
            font-size:12px;
        }

        .tank-liters {
            color:#1e9bff;
            font-size:24px;
            font-weight:900;
            margin-top:8px;
        }

        .compact .tank-liters {
            font-size:14px;
        }

        .status-badge {
            display:inline-block;
            border-radius:8px;
            padding:8px 13px;
            font-size:14px;
            font-weight:900;
            margin-top:10px;
        }

        .compact .status-badge {
            font-size:10px;
            padding:5px 8px;
        }

        .status-badge.ok {
            background:rgba(84,209,67,.18);
            color:#54d143;
        }

        .status-badge.low {
            background:rgba(255,193,7,.18);
            color:#ffc107;
        }

        .status-badge.critical {
            background:rgba(255,59,48,.18);
            color:#ff3b30;
        }

        .guide-card {
            background:#111722;
            border:1px solid #35445a;
            border-radius:14px;
            padding:16px;
            color:white;
            min-height:260px;
        }

        .guide-row {
            display:flex;
            justify-content:space-between;
            gap:8px;
            margin:14px 0;
            font-size:14px;
        }

        .dot {
            display:inline-block;
            width:13px;
            height:13px;
            border-radius:50%;
            margin-right:8px;
        }

        .stButton > button {
            background:#002B49;
            color:white;
            border:1px solid #002B49;
            border-radius:12px;
            padding:.8rem 1rem;
            font-size:17px;
            font-weight:900;
        }

        .stButton > button:hover {
            background:#003B5C;
            color:white;
        }

        .op-dashboard {
            background:linear-gradient(180deg,#111d2b,#0b111b);
            border:1px solid #35445a;
            border-radius:16px;
            padding:18px;
            margin:4px 0 18px 0;
            box-shadow:0 3px 14px rgba(0,0,0,.28);
            color:white;
        }

        .op-header {
            display:flex;
            justify-content:space-between;
            align-items:center;
            gap:18px;
            margin-bottom:14px;
        }

        .op-title {
            font-size:24px;
            font-weight:950;
            color:#1e9bff;
        }

        .op-subtitle {
            font-size:15px;
            color:#c7d4e2;
            margin-top:4px;
        }

        .op-total {
            background:linear-gradient(90deg,#002B49,#003B5C);
            border-radius:12px;
            padding:12px 18px;
            min-width:260px;
            text-align:center;
        }

        .op-total-label {
            font-size:13px;
            font-weight:900;
            color:#BDD7EE;
        }

        .op-total-value {
            font-size:30px;
            font-weight:950;
            color:white;
        }

        .op-grid {
            display:grid;
            grid-template-columns:1fr 1fr 1fr 1.25fr;
            gap:12px;
        }

        .op-card {
            background:#0f1724;
            border:1px solid #35445a;
            border-radius:14px;
            padding:14px;
            text-align:center;
            min-height:150px;
            position:relative;
            box-shadow:inset 0 0 18px rgba(255,255,255,.03);
        }

        .op-tank {
            font-size:20px;
            font-weight:950;
            color:white;
        }

        .op-status-dot {
            width:15px;
            height:15px;
            border-radius:50%;
            margin:8px auto 6px auto;
            box-shadow:0 0 10px currentColor;
        }

        .op-pct {
            font-size:34px;
            font-weight:950;
            line-height:1.0;
        }

        .op-liters {
            color:#1e9bff;
            font-size:18px;
            font-weight:900;
            margin-top:6px;
        }

        .op-cm {
            color:#d7e2ee;
            font-size:13px;
            margin-top:3px;
        }

        .op-badge {
            display:inline-block;
            margin-top:8px;
            border-radius:8px;
            padding:5px 9px;
            font-size:11px;
            font-weight:950;
        }

        .op-badge.ok {
            background:rgba(84,209,67,.18);
            color:#54d143;
        }

        .op-badge.low {
            background:rgba(255,193,7,.18);
            color:#ffc107;
        }

        .op-badge.critical {
            background:rgba(255,59,48,.18);
            color:#ff3b30;
        }

        .op-alarm {
            border-radius:14px;
            padding:14px;
            min-height:150px;
            border:1px solid #35445a;
        }

        .op-alarm-title {
            font-size:17px;
            font-weight:950;
            margin-bottom:10px;
            color:white;
        }

        .alarm-row {
            font-size:14px;
            font-weight:850;
            margin:8px 0;
            padding:7px 9px;
            border-radius:8px;
            background:rgba(255,255,255,.06);
        }

        .alarm-active {
            background:linear-gradient(180deg,#2a1717,#160c0c);
            border-color:#7a2d2d;
        }

        .alarm-ok {
            background:linear-gradient(180deg,#132516,#0b170e);
            border-color:#2e6f39;
        }

        .ok-line {
            color:#54d143;
        }

        @media (max-width: 1100px) {
            .op-header {
                flex-direction:column;
                align-items:stretch;
            }
            .op-grid {
                grid-template-columns:1fr;
            }
        }


        .consumption-panel {
            background:linear-gradient(180deg,#111d2b,#0b111b);
            border:1px solid #35445a;
            border-radius:16px;
            padding:18px;
            margin:18px 0;
            color:white;
            box-shadow:0 3px 14px rgba(0,0,0,.28);
        }

        .consumption-header {
            display:flex;
            justify-content:space-between;
            align-items:center;
            gap:18px;
            margin-bottom:14px;
        }

        .consumption-title {
            font-size:24px;
            font-weight:950;
            color:#1e9bff;
        }

        .consumption-sub {
            color:#c7d4e2;
            font-size:15px;
            margin-top:4px;
        }

        .consumption-empty {
            background:#0f1724;
            border:1px solid #35445a;
            border-radius:12px;
            padding:16px;
            color:#d7e2ee;
            font-weight:800;
            text-align:center;
        }

        .cons-total {
            background:linear-gradient(90deg,#002B49,#003B5C);
            border-radius:12px;
            padding:12px 18px;
            min-width:260px;
            text-align:center;
        }

        .cons-total-label {
            font-size:13px;
            font-weight:900;
            color:#BDD7EE;
        }

        .cons-total-value {
            font-size:30px;
            font-weight:950;
            color:white;
        }

        .cons-grid {
            display:grid;
            grid-template-columns:1fr 1fr 1fr 1.05fr;
            gap:12px;
        }

        .cons-card, .cons-total-card {
            background:#0f1724;
            border:1px solid #35445a;
            border-radius:14px;
            padding:14px;
            min-height:190px;
            box-shadow:inset 0 0 18px rgba(255,255,255,.03);
        }

        .cons-tank {
            color:white;
            font-size:20px;
            font-weight:950;
            margin-bottom:8px;
            text-align:center;
        }

        .cons-main {
            color:#1e9bff;
            font-size:30px;
            font-weight:950;
            text-align:center;
        }

        .cons-label {
            color:#c7d4e2;
            text-align:center;
            font-size:13px;
            margin-bottom:12px;
        }

        .cons-row {
            display:flex;
            justify-content:space-between;
            gap:12px;
            padding:7px 0;
            border-bottom:1px solid rgba(255,255,255,.08);
            color:#d7e2ee;
            font-size:14px;
        }

        .cons-row.big {
            font-size:17px;
            font-weight:900;
        }

        .cons-row b {
            color:white;
        }

        .cons-trend {
            margin-top:12px;
            border-radius:8px;
            padding:8px;
            font-size:13px;
            font-weight:950;
            text-align:center;
        }

        .trend-down {
            background:rgba(255,59,48,.18);
            color:#ff3b30;
        }

        .trend-up {
            background:rgba(84,209,67,.18);
            color:#54d143;
        }

        .trend-stable {
            background:rgba(30,155,255,.18);
            color:#1e9bff;
        }

        .trend-none {
            background:rgba(255,255,255,.08);
            color:#d7e2ee;
        }

        .cons-small {
            margin-top:8px;
            color:#c7d4e2;
            font-size:12px;
            text-align:center;
        }

        .cons-note {
            margin-top:12px;
            color:#c7d4e2;
            font-size:13px;
            line-height:1.35;
            background:rgba(255,255,255,.06);
            border-radius:8px;
            padding:9px;
        }

        @media (max-width: 1100px) {
            .consumption-header {
                flex-direction:column;
                align-items:stretch;
            }
            .cons-grid {
                grid-template-columns:1fr;
            }
        }


        .export-panel {
            background:linear-gradient(180deg,#111d2b,#0b111b);
            border:1px solid #35445a;
            border-radius:16px;
            padding:18px;
            margin:18px 0;
            color:white;
            box-shadow:0 3px 14px rgba(0,0,0,.28);
        }

        .export-title {
            font-size:24px;
            font-weight:950;
            color:#1e9bff;
        }

        .export-sub {
            color:#c7d4e2;
            font-size:15px;
            margin-top:4px;
            margin-bottom:14px;
        }

        .export-grid {
            display:grid;
            grid-template-columns:1fr 1fr 1fr;
            gap:12px;
        }

        .export-card {
            background:#0f1724;
            border:1px solid #35445a;
            border-radius:14px;
            padding:14px;
            min-height:120px;
            box-shadow:inset 0 0 18px rgba(255,255,255,.03);
        }

        .export-card-title {
            color:white;
            font-size:18px;
            font-weight:950;
            margin-bottom:8px;
        }

        .export-card-text {
            color:#c7d4e2;
            font-size:14px;
            line-height:1.35;
        }

        @media (max-width: 1100px) {
            .export-grid {
                grid-template-columns:1fr;
            }
        }

    </style>
    """,
    unsafe_allow_html=True,
)

now_str = datetime.now(ZoneInfo("America/Santiago")).strftime("%d-%m-%Y %H:%M:%S")

st.markdown(
    f"""
    <div class="top-banner">
        <div>
            <div class="top-title">SISTEMA DIGITAL DE CONTROL DE COMBUSTIBLE</div>
            <div class="top-sub">Fase 1.5 · Exportación profesional · cm → litros</div>
        </div>
        <div class="top-time">FECHA Y HORA<br>{now_str}</div>
    </div>
    """,
    unsafe_allow_html=True,
)

st.markdown(
    '<div class="info-strip">Ingrese el nivel en centímetros. El sistema calcula litros, porcentaje y representa visualmente el nivel de combustible.</div>',
    unsafe_allow_html=True,
)

tab_buscador, tab_historial, tab_tendencias, tab_exportar = st.tabs(["🔎 BUSCADOR / REGISTRO", "📋 HISTORIAL", "📈 TENDENCIAS", "📤 EXPORTAR"])


with tab_buscador:
    latest = latest_by_tank()
    st.markdown(operational_dashboard_html(latest), unsafe_allow_html=True)
    left, right = st.columns([0.82, 1.18], gap="large")

    with left:
        st.markdown('<div class="panel-card">', unsafe_allow_html=True)
        st.subheader("Ingreso de medición")

        tank = st.selectbox("Estanque", ["TKR", "TK1", "TK2"])
        nivel_cm = st.number_input("Nivel (cm)", min_value=0.0, value=0.0, step=0.1, format="%.1f")
        operador = st.text_input("Operador")
        observacion = st.text_area("Observación", height=90)

        liters, cm_int, mm = lookup_liters(tank, nivel_cm, cal_data)

        if liters is None:
            st.error(f"No se encontró valor para {tank} en {cm_int}.{mm} cm. Revise rango de tabla.")
            pct = 0
            estado = "SIN DATO"
        else:
            pct = calc_percentage(tank, liters, cal_data)
            estado = estado_operacional(pct)
            color = color_by_pct(pct)
            st.markdown(
                f"""
                <div class="alert-panel alert-{'critical' if pct < 0.2 else 'low' if pct < 0.5 else 'ok'}">
                    ESTADO OPERACIONAL: {estado}
                </div>
                """,
                unsafe_allow_html=True,
            )

            if st.button("💾 REGISTRAR MEDICIÓN", use_container_width=True):
                if not operador.strip():
                    st.warning("Debe ingresar nombre del operador.")
                else:
                    save_record(tank, nivel_cm, liters, pct, estado, operador, observacion)
                    st.success("Medición guardada correctamente.")
                    st.rerun()

        st.markdown('</div>', unsafe_allow_html=True)

        if liters is not None:
            st.markdown(
                f"""
                <div class="total-panel">
                    <div>
                        <div class="label-total">MEDICIÓN ACTUAL</div>
                        <div>{tank} · {nivel_cm:.1f} cm · {fmt_pct(pct)}</div>
                    </div>
                    <div class="value-total">{fmt_liters(liters)}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

    with right:
        if liters is not None:
            st.markdown(tank_visual(tank, pct, liters, nivel_cm), unsafe_allow_html=True)
        else:
            st.info("Ingrese un nivel válido para visualizar el tanque.")

    # Resumen con últimos niveles válidos
    latest = latest_by_tank()
    st.markdown('<div class="section-title">RESUMEN VISUAL DE TANQUES - ÚLTIMA MEDICIÓN VÁLIDA</div>', unsafe_allow_html=True)
    c1, c2, c3, c4 = st.columns([1, 1, 1.25, 0.9], gap="medium")

    for col, tank_name in zip([c1, c2, c3], ["TK1", "TK2", "TKR"]):
        row = latest.get(tank_name)
        pct2, liters2, nivel2 = state_from_row_or_default(tank_name, row)
        with col:
            st.markdown(tank_visual(tank_name, pct2, liters2, nivel2, compact=True), unsafe_allow_html=True)

    with c4:
        st.markdown(
            """
            <div class="guide-card">
                <h3>GUÍA DE NIVELES</h3>
                <div class="guide-row"><span><span class="dot" style="background:#54d143;"></span><b style="color:#54d143;">NORMAL</b></span><span>50% - 100%</span></div>
                <div class="guide-row"><span><span class="dot" style="background:#ffc107;"></span><b style="color:#ffc107;">BAJO</b></span><span>20% - 49%</span></div>
                <div class="guide-row"><span><span class="dot" style="background:#ff3b30;"></span><b style="color:#ff3b30;">CRÍTICO</b></span><span>0% - 19%</span></div>
                <hr>
                <div style="font-size:13px; color:#d7e2ee;">Cuando el nivel esté bajo o crítico, el tanque cambia de color automáticamente.</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    # Total combustible disponible por última medición válida
    total = 0
    for tank_name in ["TKR", "TK1", "TK2"]:
        row = latest.get(tank_name)
        if row is not None:
            total += float(row["volumen_l"])
    st.markdown(
        f"""
        <div class="total-panel">
            <div class="label-total">TOTAL COMBUSTIBLE DISPONIBLE SEGÚN ÚLTIMAS MEDICIONES VÁLIDAS</div>
            <div class="value-total">{fmt_liters(total)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown('<div class="section-title">ÚLTIMAS MEDICIONES REGISTRADAS - SOLO VÁLIDAS</div>', unsafe_allow_html=True)
    df_valid = load_records(valid_only=True).head(5)
    if df_valid.empty:
        st.info("Aún no existen registros válidos.")
    else:
        show = df_valid[["fecha_hora", "estanque", "nivel_cm", "volumen_l", "porcentaje", "estado_operacional", "operador", "observacion"]].copy()
        show["volumen_l"] = show["volumen_l"].map(fmt_liters)
        show["porcentaje"] = show["porcentaje"].map(fmt_pct)
        show = show.rename(
            columns={
                "fecha_hora": "Fecha / hora",
                "estanque": "Estanque",
                "nivel_cm": "Nivel (cm)",
                "volumen_l": "Volumen",
                "porcentaje": "% llenado",
                "estado_operacional": "Estado",
                "operador": "Operador",
                "observacion": "Observación",
            }
        )
        st.dataframe(show, use_container_width=True, hide_index=True)


with tab_historial:
    st.markdown('<div class="section-title">HISTORIAL COMPLETO DE MEDICIONES</div>', unsafe_allow_html=True)
    df = load_records(valid_only=False)

    if df.empty:
        st.info("Aún no existen registros.")
    else:
        st.dataframe(df, use_container_width=True, hide_index=True)

        st.markdown('<div class="section-title">ANULAR MEDICIÓN POR ERROR DE INGRESO</div>', unsafe_allow_html=True)
        valid_df = df[df["estado_registro"] == "VÁLIDO"]
        if valid_df.empty:
            st.info("No hay mediciones válidas para anular.")
        else:
            ids = valid_df["id"].tolist()
            selected_id = st.selectbox("Seleccione ID a anular", ids)
            motivo = st.text_input("Motivo de anulación")
            if st.button("⚠️ ANULAR REGISTRO", use_container_width=True):
                if not motivo.strip():
                    st.warning("Debe ingresar motivo de anulación.")
                else:
                    annul_record(selected_id, motivo)
                    st.success("Registro anulado. Ya no aparecerá en últimas mediciones ni gráficos.")
                    st.rerun()


with tab_tendencias:
    st.markdown(consumption_dashboard_html(), unsafe_allow_html=True)
    st.markdown('<div class="section-title">TENDENCIAS HISTÓRICAS DE COMBUSTIBLE</div>', unsafe_allow_html=True)
    df_valid = load_records(valid_only=True)

    st.markdown('<div class="section-title">DETALLE DE CONSUMOS ENTRE MEDICIONES</div>', unsafe_allow_html=True)
    cons_df = consumption_table()
    if cons_df.empty:
        st.info("Aún no existen mediciones suficientes para calcular consumo.")
    else:
        show_cons = cons_df.copy()
        show_cons["volumen_l"] = show_cons["volumen_l"].map(fmt_liters)
        show_cons["porcentaje"] = show_cons["porcentaje"].map(fmt_pct)
        show_cons["delta_litros"] = show_cons["delta_litros"].fillna(0).map(fmt_liters)
        show_cons["consumo_litros"] = show_cons["consumo_litros"].map(fmt_liters)
        show_cons["reposicion_litros"] = show_cons["reposicion_litros"].map(fmt_liters)
        show_cons = show_cons.rename(columns={
            "fecha_hora": "Fecha / hora",
            "estanque": "Estanque",
            "nivel_cm": "Nivel (cm)",
            "volumen_l": "Volumen",
            "porcentaje": "% llenado",
            "delta_litros": "Variación",
            "consumo_litros": "Consumo",
            "reposicion_litros": "Reposición",
            "operador": "Operador",
            "observacion": "Observación",
        })
        st.dataframe(show_cons, use_container_width=True, hide_index=True)

    if df_valid.empty:
        st.info("Aún no existen datos válidos para graficar.")
    else:
        for tank_name in ["TKR", "TK1", "TK2"]:
            st.markdown(f"### {tank_name}")
            tank_df = df_valid[df_valid["estanque"] == tank_name].copy()
            tank_df = tank_df.sort_values("fecha_hora")

            if tank_df.empty:
                st.info(f"No hay datos válidos para {tank_name}.")
                continue

            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Última medición", fmt_liters(tank_df["volumen_l"].iloc[-1]))
            c2.metric("Máximo histórico", fmt_liters(tank_df["volumen_l"].max()))
            c3.metric("Mínimo histórico", fmt_liters(tank_df["volumen_l"].min()))
            c4.metric("Promedio", fmt_liters(tank_df["volumen_l"].mean()))

            chart = (
                alt.Chart(tank_df)
                .mark_line(point=True)
                .encode(
                    x=alt.X("fecha_hora:T", title="Fecha / hora"),
                    y=alt.Y("volumen_l:Q", title="Litros"),
                    tooltip=[
                        alt.Tooltip("fecha_hora:T", title="Fecha / hora"),
                        alt.Tooltip("nivel_cm:Q", title="Nivel cm"),
                        alt.Tooltip("volumen_l:Q", title="Litros"),
                        alt.Tooltip("porcentaje:Q", title="% llenado", format=".1%"),
                        alt.Tooltip("operador:N", title="Operador"),
                    ],
                )
                .properties(height=320)
            )
            st.altair_chart(chart, use_container_width=True)
            st.markdown("---")


with tab_exportar:
    st.markdown(export_panel_html(), unsafe_allow_html=True)

    fecha_archivo = datetime.now().strftime("%Y%m%d_%H%M")
    excel_data = make_excel_report()
    csv_valid = make_csv_history(valid_only=True)
    csv_all = make_csv_history(valid_only=False)

    col1, col2, col3 = st.columns(3)

    with col1:
        st.download_button(
            label="📘 Descargar informe completo Excel",
            data=excel_data,
            file_name=f"informe_combustible_{fecha_archivo}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )

    with col2:
        st.download_button(
            label="📋 Descargar registros válidos CSV",
            data=csv_valid,
            file_name=f"registros_validos_{fecha_archivo}.csv",
            mime="text/csv",
            use_container_width=True,
        )

    with col3:
        st.download_button(
            label="🗂️ Descargar historial completo CSV",
            data=csv_all,
            file_name=f"historial_completo_{fecha_archivo}.csv",
            mime="text/csv",
            use_container_width=True,
        )

    st.markdown('<div class="section-title">PREVISUALIZACIÓN DEL INFORME</div>', unsafe_allow_html=True)

    resumen_df, total_df, df_all, df_valid, cons_df, consumo_resumen_df = prepare_export_data()

    st.subheader("Resumen por tanque")
    st.dataframe(resumen_df, use_container_width=True, hide_index=True)

    st.subheader("Consumo operacional resumido")
    if consumo_resumen_df.empty:
        st.info("Aún no existen consumos calculados.")
    else:
        st.dataframe(consumo_resumen_df, use_container_width=True, hide_index=True)

    st.subheader("Últimos registros válidos")
    if df_valid.empty:
        st.info("Aún no existen registros válidos.")
    else:
        st.dataframe(df_valid.head(10), use_container_width=True, hide_index=True)

