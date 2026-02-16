import streamlit as st
import pandas as pd
from supabase import create_client
from datetime import date, datetime, timedelta
import calendar
from dateutil.relativedelta import relativedelta
import plotly.express as px
import time

# --- 1. CONFIGURACIÓN VISUAL (ESTILO FINTECH) ---
st.set_page_config(
    page_title="Finanzas Pro", 
    page_icon="💸", 
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- 2. CSS ADAPTATIVO (DARK/LIGHT MODE FRIENDLY) ---
st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap');
    
    html, body, [class*="css"] {
        font-family: 'Inter', sans-serif;
    }
    
    /* TARJETAS (Métricas) que se adaptan al modo oscuro */
    div[data-testid="stMetric"] {
        background-color: var(--secondary-background-color); 
        border: 1px solid rgba(128, 128, 128, 0.2);
        padding: 15px;
        border-radius: 10px;
        box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
    }
    
    div[data-testid="stMetricLabel"] p {
        font-weight: 600 !important;
        opacity: 0.8;
    }
    
    /* CALENDARIO ADAPTATIVO */
    .day-card {
        background-color: var(--secondary-background-color);
        border: 1px solid rgba(128, 128, 128, 0.2);
        border-radius: 8px;
        height: 100px;
        padding: 8px;
        display: flex;
        flex-direction: column;
        justify-content: flex-start;
        font-size: 0.85rem;
        margin-bottom: 8px;
        box-shadow: 0 2px 4px rgba(0,0,0,0.05);
    }
    .day-header {
        font-weight: 700;
        color: var(--text-color);
        opacity: 0.8;
        margin-bottom: 4px;
        border-bottom: 1px solid rgba(128, 128, 128, 0.2);
    }
    .tag-ing { 
        color: #4ade80; 
        background: rgba(74, 222, 128, 0.1); 
        padding: 2px 6px; border-radius: 4px; font-weight: 600; font-size: 0.75rem; margin-top: 2px;
    }
    .tag-gas { 
        color: #f87171; 
        background: rgba(248, 113, 113, 0.1); 
        padding: 2px 6px; border-radius: 4px; font-weight: 600; font-size: 0.75rem; margin-top: 2px;
    }
    
    /* Sidebar Título */
    .sidebar-brand {
        font-size: 1.5rem;
        font-weight: 800;
        color: var(--text-color);
        margin-bottom: 1rem;
        padding: 10px;
        background: var(--secondary-background-color);
        border-radius: 8px;
        text-align: center;
        border: 1px solid rgba(128, 128, 128, 0.2);
    }
    </style>
""", unsafe_allow_html=True)

# --- 3. CONEXIÓN & FUNCIONES ---
@st.cache_resource
def init_connection():
    try:
        url = st.secrets["SUPABASE_URL"]
        key = st.secrets["SUPABASE_KEY"]
        return create_client(url, key)
    except: st.stop()

supabase = init_connection()

# --- LOGIN ---
def check_password():
    if "password_correct" not in st.session_state:
        st.session_state.password_correct = False
    if st.session_state.password_correct: return True
    col1, col2, col3 = st.columns([1,2,1])
    with col2:
        st.markdown("<br><h3 style='text-align:center'>🔐 Finanzas Pro</h3>", unsafe_allow_html=True)
        pwd = st.text_input("Contraseña", type="password")
        if st.button("Entrar", use_container_width=True):
            if pwd == "admin": 
                st.session_state.password_correct = True
                st.rerun()
            else: st.error("Incorrecto")
    return False

if not check_password(): st.stop()

def fmt_ars(valor):
    if valor is None: valor = 0
    s = f"{valor:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')
    return f"$ {s[:-3]}" if s.endswith(",00") else f"$ {s}"

def calcular_vto_real(fecha_compra, dia_cierre, dia_vto):
    if isinstance(fecha_compra, str):
        try: fecha_compra = datetime.strptime(fecha_compra, "%Y-%m-%d").date()
        except: return date.today()
    try: f_cierre = date(fecha_compra.year, fecha_compra.month, int(dia_cierre))
    except: f_cierre = date(fecha_compra.year, fecha_compra.month, 28)
    if fecha_compra <= f_cierre: resumen = fecha_compra + relativedelta(months=1)
    else: resumen = fecha_compra + relativedelta(months=2)
    try: return date(resumen.year, resumen.month, int(dia_vto))
    except: return date(resumen.year, resumen.month, 28)

def get_maestros():
    cta = pd.DataFrame(supabase.table("cuentas").select("*").execute().data)
    cat = pd.DataFrame(supabase.table("categorias").select("*").execute().data)
    try: su = float(supabase.table("configuracion").select("valor").eq("clave", "sueldo_mensual").execute().data[0]['valor'])
    except: su = 0.0
    return cta, cat, su

def get_movimientos(desde, hasta):
    desde_ext = desde - relativedelta(months=6)
    resp = supabase.table("movimientos").select(
        "*, categorias(nombre, icono), cuentas:cuentas!cuenta_id(nombre, tipo, dia_cierre, dia_vencimiento)"
    ).gte("fecha", str(desde_ext)).lte("fecha", str(hasta)).order("fecha").execute()
    if not resp.data: return pd.DataFrame()
    data = []
    for d in resp.data:
        r = d.copy()
        r['categoria'] = f"{d['categorias']['icono']} {d['categorias']['nombre']}" if d.get('categorias') else "General"
        r['cuenta'] = d['cuentas']['nombre'] if d.get('cuentas') else "Efectivo"
        r['tipo_cta'] = d['cuentas']['tipo'] if d.get('cuentas') else "DEBITO"
        r['cierre'] = d['cuentas'].get('dia_cierre', 23) if d.get('cuentas') else 23
        r['vto'] = d['cuentas'].get('dia_vencimiento', 5) if d.get('cuentas') else 5
        del r['categorias'], r['cuentas']
        data.append(r)
    df = pd.DataFrame(data)
    df['fecha'] = pd.to_datetime(df['fecha']).dt.date
    return df

def db_save(fecha, monto, desc, cta_id, cat_id, tipo, dest_id=None):
    payload = {"fecha": str(fecha), "monto": monto, "descripcion": desc, "cuenta_id": cta_id, "categoria_id": cat_id, "tipo": tipo}
    if dest_id: payload["cuenta_destino_id"] = dest_id
    supabase.table("movimientos").insert(payload).execute()

def db_delete(id_mov):
    supabase.table("movimientos").delete().eq("id", id_mov).execute()

def get_suscripciones(): return pd.DataFrame(supabase.table("suscripciones").select("*").execute().data)
def save_suscripcion(desc, monto, cta_id, cat_id, tipo): supabase.table("suscripciones").insert({"descripcion": desc, "monto": monto, "cuenta_id": cta_id, "categoria_id": cat_id, "tipo": tipo}).execute()
def delete_suscripcion(sid): supabase.table("suscripciones").delete().eq("id", sid).execute()
def get_metas(): return pd.DataFrame(supabase.table("metas").select("*").execute().data)
def save_meta(n, o, f): supabase.table("metas").insert({"nombre": n, "objetivo": o, "fecha_limite": str(f)}).execute()
def update_meta_ahorro(mid, v): supabase.table("metas").update({"ahorrado": v}).eq("id", mid).execute()
def delete_meta(mid): supabase.table("metas").delete().eq("id", mid).execute()

df_cta, df_cat, sueldo_base = get_maestros()

# --- 4. SIDEBAR ---
with st.sidebar:
    st.markdown('<div class="sidebar-brand">🦅 Finanzas Pro</div>', unsafe_allow_html=True)
    menu = st.radio("Navegación", 
        ["📊 Dashboard", "📅 Calendario", "➕ Nueva Operación", "🎯 Metas", "📝 Historial", "💳 Tarjetas", "⚙️ Ajustes"],
        label_visibility="collapsed"
    )
    st.markdown("---")
    c_mes, c_anio = st.columns(2)
    mes_sel = c_mes.selectbox("Mes", range(1, 13), index=date.today().month - 1)
    anio_sel = c_anio.number_input("Año", value=date.today().year, step=1)
    f_ini = date(anio_sel, mes_sel, 1)
    f_fin = f_ini + relativedelta(months=1) - timedelta(days=1)

# ==========================================
# 1. DASHBOARD
# ==========================================
if menu == "📊 Dashboard":
    st.markdown(f"## 📈 Balance: {f_ini.strftime('%B %Y')}")
    df_raw = get_movimientos(f_ini, f_fin)
    
    if not df_raw.empty:
        df_mes = df_raw[(df_raw['fecha'] >= f_ini) & (df_raw['fecha'] <= f_fin)]
        
        # Cálculos
        ing_registrados = df_mes[df_mes['tipo'] == 'INGRESO']['monto'].sum()
        total_ingresos = ing_registrados if ing_registrados > 0 else sueldo_base
        
        gastos_cash = df_mes[df_mes['tipo'] == 'GASTO']['monto'].sum()
        gastos_tj = df_mes[df_mes['tipo'] == 'COMPRA_TARJETA']['monto'].sum()
        total_consumo = gastos_cash + gastos_tj
        
        df_tj = df_raw[df_raw['tipo'] == 'COMPRA_TARJETA'].copy()
        vence_ahora = 0
        if not df_tj.empty:
            df_tj['fecha_vto'] = df_tj.apply(lambda x: calcular_vto_real(x['fecha'], x['cierre'], x['vto']), axis=1)
            vence_ahora = df_tj[(df_tj['fecha_vto'] >= f_ini) & (df_tj['fecha_vto'] <= f_fin)]['monto'].sum()

        saldo_mes = total_ingresos - total_consumo
        caja_real = total_ingresos - gastos_cash - vence_ahora

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("💰 Resultado Neto", fmt_ars(saldo_mes), delta="Ingreso - Consumo Total")
        c2.metric("🏦 Caja Disponible", fmt_ars(caja_real), help="Dinero real tras pagar resumen y cash")
        c3.metric("🛒 Consumo Total", fmt_ars(total_consumo), delta="Cash + Tarjeta", delta_color="inverse")
        c4.metric("💳 Pagar Resumen", fmt_ars(vence_ahora), delta="Vencimiento", delta_color="inverse")

        st.divider()
        g1, g2 = st.columns([2, 1])
        with g1:
            st.markdown("##### 📈 Evolución")
            if not df_mes.empty:
                df_chart = df_mes[df_mes['tipo'] != 'INGRESO']
                if not df_chart.empty:
                    fig = px.bar(df_chart, x='fecha', y='monto', color='categoria', 
                                 color_discrete_sequence=px.colors.qualitative.Pastel)
                    fig.update_layout(xaxis_title=None, yaxis_title=None, height=320, margin=dict(l=0,r=0,t=0,b=0))
                    st.plotly_chart(fig, use_container_width=True)
                else: st.info("Sin gastos.")
        with g2:
            st.markdown("##### 🍰 Rubros")
            if not df_mes.empty:
                df_chart = df_mes[df_mes['tipo'].isin(['GASTO', 'COMPRA_TARJETA'])]
                if not df_chart.empty:
                    fig_p = px.pie(df_chart, values='monto', names='categoria', hole=0.6,
                                   color_discrete_sequence=px.colors.qualitative.Pastel)
                    fig_p.update_layout(showlegend=False, height=320, margin=dict(l=0,r=0,t=0,b=0))
                    st.plotly_chart(fig_p, use_container_width=True)
    else: st.warning("No hay datos en este mes.")

# ==========================================
# 2. CALENDARIO
# ==========================================
elif menu == "📅 Calendario":
    st.markdown(f"### 📅 Agenda: {f_ini.strftime('%B %Y')}")
    df_cal = get_movimientos(f_ini, f_fin)
    if not df_cal.empty:
        df_cal = df_cal[(df_cal['fecha'] >= f_ini) & (df_cal['fecha'] <= f_fin)]
    
    cal = calendar.Calendar()
    semanas = cal.monthdayscalendar(anio_sel, mes_sel)
    dias = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]
    
    cols = st.columns(7)
    for i, d in enumerate(dias):
        cols[i].markdown(f"<div style='text-align:center; font-weight:600; opacity:0.7;'>{d}</div>", unsafe_allow_html=True)
        
    for semana in semanas:
        cols = st.columns(7)
        for i, dia in enumerate(semana):
            with cols[i]:
                if dia != 0:
                    fecha_dia = date(anio_sel, mes_sel, dia)
                    content_html = f"<div class='day-header'>{dia}</div>"
                    
                    if not df_cal.empty:
                        evs = df_cal[df_cal['fecha'] == fecha_dia]
                        ing = evs[evs['tipo']=='INGRESO']['monto'].sum()
                        gas = evs[evs['tipo']!='INGRESO']['monto'].sum()
                        
                        if ing > 0: content_html += f"<div class='tag-ing'>+{fmt_ars(ing)}</div>"
                        if gas > 0: content_html += f"<div class='tag-gas'>-{fmt_ars(gas)}</div>"
                        
                        st.markdown(f"<div class='day-card'>{content_html}</div>", unsafe_allow_html=True)
                        if not evs.empty:
                            with st.popover("", use_container_width=True):
                                st.caption(f"{dia}/{mes_sel}")
                                st.dataframe(evs[['descripcion', 'monto']], hide_index=True)
                    else:
                        st.markdown(f"<div class='day-card' style='opacity:0.3'>{content_html}</div>", unsafe_allow_html=True)
                else: st.write("")

# ==========================================
# 3. NUEVA OPERACIÓN
# ==========================================
elif menu == "➕ Nueva Operación":
    st.markdown("### Registrar Movimiento")
    t1, t2, t3 = st.tabs(["Manual / Cuotas", "🔄 Fijos", "📥 Importar Excel"])
    
    with t1:
        with st.container(border=True):
            tipo_op = st.radio("Tipo", ["Gasto", "Ingreso", "Pagar Tarjeta"], horizontal=True)
            st.divider()
            c1, c2 = st.columns(2)
            f = c1.date_input("Fecha", date.today())
            m = c2.number_input("Monto", min_value=0.0, step=100.0)
            d = st.text_input("Descripción")
            c3, c4 = st.columns(2)
            if tipo_op == "Pagar Tarjeta":
                cta_n = c3.selectbox("Desde", df_cta[df_cta['tipo']!='CREDITO']['nombre'].tolist())
                cta_dest = c4.selectbox("Tarjeta", df_cta[df_cta['tipo']=='CREDITO']['nombre'].tolist())
                cat_n = df_cat.iloc[0]['nombre']
            else:
                cta_n = c3.selectbox("Cuenta", df_cta['nombre'].tolist())
                cat_n = c4.selectbox("Categoría", df_cat['nombre'].tolist())
            cuotas = 1
            if tipo_op == "Gasto":
                cuotas = st.slider("Cuotas", 1, 24, 1)

            if st.button("Guardar", type="primary", use_container_width=True):
                id_c = df_cta[df_cta['nombre'] == cta_n]['id'].values[0]
                id_ct = df_cat[df_cat['nombre'] == cat_n]['id'].values[0]
                if tipo_op == "Pagar Tarjeta":
                    id_d = df_cta[df_cta['nombre'] == cta_dest]['id'].values[0]
                    db_save(f, m, d, id_c, id_ct, "PAGO_TARJETA", id_d)
                elif tipo_op == "Ingreso":
                    db_save(f, m, d, id_c, id_ct, "INGRESO")
                else:
                    es_cred = df_cta[df_cta['nombre'] == cta_n]['tipo'].values[0] == 'CREDITO'
                    tp = "COMPRA_TARJETA" if es_cred else "GASTO"
                    if cuotas > 1:
                        m_c = m / cuotas
                        for i in range(cuotas):
                            f_p = f + relativedelta(months=i)
                            d_c = f"{d} ({i+1}/{cuotas})"
                            db_save(f_p, m_c, d_c, id_c, id_ct, tp)
                    else: db_save(f, m, d, id_c, id_ct, tp)
                st.toast("✅ Guardado"); time.sleep(1); st.rerun()

    with t2:
        df_sus = get_suscripciones()
        if not df_sus.empty:
            c_date, c_info = st.columns([1,2])
            fecha_imp = c_date.date_input("Fecha Impacto", date.today().replace(day=5))
            c_info.info(f"Se crearán en **{fecha_imp.strftime('%B')}**.")
            
            # FIX CRÍTICO: num_rows="fixed" para que no agreguen filas sin ID
            ed_sus = st.data_editor(
                df_sus[['descripcion', 'monto']], 
                use_container_width=True, 
                num_rows="fixed", 
                column_config={"monto": st.column_config.NumberColumn("Monto", format="$ %.2f")}
            )
            
            if st.button("🚀 Procesar", type="primary"):
                c = 0
                for i, row in ed_sus.iterrows():
                    # FIX CRÍTICO: Buscar por índice en el DF original para obtener los IDs ocultos
                    if i in df_sus.index:
                        orig = df_sus.loc[i]
                        db_save(fecha_imp, row['monto'], row['descripcion'], orig['cuenta_id'], orig['categoria_id'], orig['tipo'])
                        c += 1
                st.toast(f"✅ {c} movimientos procesados"); time.sleep(1); st.rerun()
        else: st.warning("No hay fijos configurados.")

    with t3:
        up = st.file_uploader("Excel Santander/Galicia", type=['xlsx', 'csv'])
        if up:
            try:
                if up.name.endswith('.csv'): df_u = pd.read_csv(up)
                else:
                    raw = pd.read_excel(up)
                    head = 0
                    for i in range(len(raw)):
                        if 'Fecha' in raw.iloc[i].values or 'FECHA' in raw.iloc[i].values: head = i+1; break
                    df_u = pd.read_excel(up, skiprows=head)
                df_u = df_u.dropna(how='all').reset_index(drop=True)
                st.dataframe(df_u.head(3), use_container_width=True)
                with st.form("imp"):
                    sel = st.selectbox("Tarjeta Destino", df_cta[df_cta['tipo']=='CREDITO']['nombre'].tolist())
                    c1, c2, c3 = st.columns(3)
                    fc = c1.selectbox("Col. Fecha", df_u.columns); dc = c2.selectbox("Col. Detalle", df_u.columns); mc = c3.selectbox("Col. Pesos", df_u.columns)
                    if st.form_submit_button("Importar"):
                        tid = df_cta[df_cta['nombre']==sel]['id'].values[0]
                        for _, r in df_u.iterrows():
                            try:
                                ms = str(r[mc]).replace('$','').replace(' ','')
                                if ',' in ms and '.' in ms: ms = ms.replace('.','').replace(',','.')
                                elif ',' in ms: ms = ms.replace(',','.')
                                val = abs(float(ms))
                                fval = pd.to_datetime(r[fc], dayfirst=True).date()
                                db_save(fval, val, str(r[dc]), tid, df_cat.iloc[0]['id'], "COMPRA_TARJETA")
                            except: continue
                        st.toast("✅ Importado"); time.sleep(1); st.rerun()
            except Exception as e: st.error(f"Error: {e}")

# ==========================================
# 4. METAS
# ==========================================
elif "Metas" in menu:
    st.markdown("### 🎯 Objetivos")
    df_m = get_metas()
    c1, c2 = st.columns([1, 2])
    with c1:
        with st.container(border=True):
            st.markdown("#### Nueva Meta")
            n = st.text_input("Nombre")
            o = st.number_input("Objetivo ($)", min_value=1.0)
            l = st.date_input("Límite")
            if st.button("Crear", type="primary", use_container_width=True): save_meta(n, o, l); st.rerun()
    with c2:
        if not df_m.empty:
            for _, m in df_m.iterrows():
                with st.container(border=True):
                    ca, cb = st.columns([3,1])
                    pct = m['ahorrado'] / m['objetivo'] if m['objetivo'] > 0 else 0
                    ca.markdown(f"**{m['nombre']}**")
                    ca.progress(min(pct, 1.0))
                    ca.caption(f"{fmt_ars(m['ahorrado'])} / {fmt_ars(m['objetivo'])}")
                    nv = cb.number_input("Monto", value=float(m['ahorrado']), key=f"v{m['id']}", label_visibility="collapsed")
                    if cb.button("💾", key=f"s{m['id']}"): update_meta_ahorro(m['id'], nv); st.rerun()
                    if cb.button("🗑️", key=f"d{m['id']}"): delete_meta(m['id']); st.rerun()
        else: st.info("Sin metas.")

# ==========================================
# 5. HISTORIAL
# ==========================================
elif "Historial" in menu:
    st.markdown("### 📝 Datos")
    check_col, _ = st.columns([1,3])
    ver_todo = check_col.checkbox("Ver todo histórico")
    df_h = get_movimientos(date(2024,1,1), date(2027,1,1)) if ver_todo else get_movimientos(f_ini, f_fin)
    if not ver_todo and not df_h.empty: df_h = df_h[(df_h['fecha'] >= f_ini) & (df_h['fecha'] <= f_fin)]

    if not df_h.empty:
        st.data_editor(
            df_h[['id', 'fecha', 'descripcion', 'monto', 'cuenta', 'tipo']],
            column_config={"monto": st.column_config.NumberColumn("Monto", format="$ %.2f")},
            use_container_width=True, hide_index=True
        )
        with st.expander("🗑️ Borrado"):
            ops = {f"{r['fecha']} | {r['descripcion']}": r['id'] for _, r in df_h.iterrows()}
            s = st.selectbox("Elegir:", ["..."] + list(ops.keys()))
            if st.button("Eliminar Item") and s != "...": db_delete(ops[s]); st.toast("Chau"); time.sleep(1); st.rerun()
            if st.checkbox("Borrar TODO lo visible"):
                if st.button("CONFIRMAR BORRADO"):
                    for _, r in df_h.iterrows(): db_delete(r['id'])
                    st.rerun()
    else: st.info("Sin datos.")

# ==========================================
# 6. CONFIG
# ==========================================
elif "Tarjetas" in menu:
    st.markdown("### 💳 Tarjetas")
    t1, _ = st.tabs(["Config", "Info"])
    with t1:
        for _, r in df_cta[df_cta['tipo']=='CREDITO'].iterrows():
            with st.container(border=True):
                c1, c2, c3, c4 = st.columns([2,1,1,1])
                c1.write(f"**{r['nombre']}**")
                ci = c2.number_input("Cierre", 1, 31, int(r.get('dia_cierre') or 23), key=f"c{r['id']}")
                vt = c3.number_input("Vto", 1, 31, int(r.get('dia_vencimiento') or 5), key=f"v{r['id']}")
                if c4.button("💾", key=f"b{r['id']}"):
                    supabase.table("cuentas").update({"dia_cierre": ci, "dia_vencimiento": vt}).eq("id", r['id']).execute()
                    st.toast("Ok")

elif "Ajustes" in menu:
    st.markdown("### ⚙️ Ajustes")
    with st.container(border=True):
        st.write("Sueldo Base")
        ns = st.number_input("Neto", value=int(sueldo_base), label_visibility="collapsed")
        if st.button("Actualizar"):
            supabase.table("configuracion").upsert({"clave": "sueldo_mensual", "valor": str(ns)}).execute()
            st.toast("Ok")
    
    st.markdown("#### Fijos")
    with st.form("add_sus"):
        c1, c2, c3 = st.columns([2,1,1])
        sd = c1.text_input("Desc")
        sm = c2.number_input("Monto", min_value=0.0)
        sc = c3.selectbox("Pago", df_cta['nombre'].tolist())
        if st.form_submit_button("Agregar"):
            sidc = df_cta[df_cta['nombre']==sc]['id'].values[0]
            sca = df_cat.iloc[0]['id']
            stipo = "COMPRA_TARJETA" if df_cta[df_cta['nombre']==sc]['tipo'].values[0]=='CREDITO' else "GASTO"
            save_suscripcion(sd, sm, sidc, sca, stipo)
            st.rerun()
    
    df_s = get_suscripciones()
    if not df_s.empty:
        st.dataframe(df_s[['descripcion', 'monto']], use_container_width=True, hide_index=True)
        ds = st.selectbox("Borrar:", ["..."] + df_s['descripcion'].tolist())
        if st.button("Eliminar Fijo") and ds != "...":
            did = df_s[df_s['descripcion']==ds]['id'].values[0]
            delete_suscripcion(did); st.rerun()