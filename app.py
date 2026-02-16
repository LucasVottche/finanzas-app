import streamlit as st
import pandas as pd
from supabase import create_client
from datetime import date, datetime, timedelta
import calendar
from dateutil.relativedelta import relativedelta
import plotly.express as px
import time

# --- CONFIGURACIÓN ---
st.set_page_config(page_title="Finanzas Pro", page_icon="💰", layout="wide")

# --- LOGIN SIMPLE ---
def check_password():
    if "password_correct" not in st.session_state:
        st.session_state.password_correct = False

    if st.session_state.password_correct:
        return True

    st.title("🔐 Acceso Seguro")
    pwd = st.text_input("Contraseña", type="password")
    if st.button("Entrar"):
        # CAMBIA ESTA CONTRASEÑA POR LA QUE QUIERAS
        if pwd == "admin": 
            st.session_state.password_correct = True
            st.rerun()
        else:
            st.error("Contraseña incorrecta")
    return False

if not check_password():
    st.stop()

# --- CONEXIÓN ---
@st.cache_resource
def init_connection():
    try:
        url = st.secrets["SUPABASE_URL"]
        key = st.secrets["SUPABASE_KEY"]
        return create_client(url, key)
    except: st.stop()

supabase = init_connection()

# --- FORMATOS ---
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

# --- BASE DE DATOS (CRUD) ---
def get_maestros():
    cta = pd.DataFrame(supabase.table("cuentas").select("*").execute().data)
    cat = pd.DataFrame(supabase.table("categorias").select("*").execute().data)
    try: su = float(supabase.table("configuracion").select("valor").eq("clave", "sueldo_mensual").execute().data[0]['valor'])
    except: su = 0.0
    return cta, cat, su

def get_movimientos(desde, hasta):
    desde_ext = desde - relativedelta(months=6) # Margen para cuotas/tarjetas
    resp = supabase.table("movimientos").select(
        "*, categorias(nombre, icono), cuentas:cuentas!cuenta_id(nombre, tipo, dia_cierre, dia_vencimiento)"
    ).gte("fecha", str(desde_ext)).lte("fecha", str(hasta)).order("fecha").execute()
    if not resp.data: return pd.DataFrame()
    data = []
    for d in resp.data:
        r = d.copy()
        r['categoria'] = f"{d['categorias']['icono']} {d['categorias']['nombre']}" if d.get('categorias') else "Sin Cat"
        r['cuenta'] = d['cuentas']['nombre'] if d.get('cuentas') else "Sin Cuenta"
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

# --- NUEVAS FUNCIONES V11 ---
def get_suscripciones():
    return pd.DataFrame(supabase.table("suscripciones").select("*").execute().data)

def save_suscripcion(desc, monto, cta_id, cat_id, tipo):
    supabase.table("suscripciones").insert({"descripcion": desc, "monto": monto, "cuenta_id": cta_id, "categoria_id": cat_id, "tipo": tipo}).execute()

def delete_suscripcion(sid):
    supabase.table("suscripciones").delete().eq("id", sid).execute()

def get_metas():
    return pd.DataFrame(supabase.table("metas").select("*").execute().data)

def save_meta(nombre, objetivo, fecha):
    supabase.table("metas").insert({"nombre": nombre, "objetivo": objetivo, "fecha_limite": str(fecha)}).execute()

def update_meta_ahorro(mid, monto_nuevo):
    supabase.table("metas").update({"ahorrado": monto_nuevo}).eq("id", mid).execute()

def delete_meta(mid):
    supabase.table("metas").delete().eq("id", mid).execute()

# --- CARGA DATOS GLOBALES ---
df_cta, df_cat, sueldo_base = get_maestros()

# --- SIDEBAR ---
with st.sidebar:
    st.title("Lucas Finanzas")
    menu = st.radio("Menú", 
        ["📊 Dashboard", "📅 Calendario", "🎯 Metas", "➕ Cargar", "📝 Historial", "💳 Tarjetas", "⚙️ Ajustes"]
    )
    st.divider()
    mes_sel = st.selectbox("Mes", range(1, 13), index=date.today().month - 1)
    anio_sel = st.number_input("Año", value=date.today().year, step=1)
    f_ini = date(anio_sel, mes_sel, 1)
    f_fin = f_ini + relativedelta(months=1) - timedelta(days=1)

# ==========================================
# 1. DASHBOARD
# ==========================================
if menu == "📊 Dashboard":
    st.header(f"Balance: {f_ini.strftime('%B %Y')}")
    df_raw = get_movimientos(f_ini, f_fin)
    
    if not df_raw.empty:
        df_mes = df_raw[(df_raw['fecha'] >= f_ini) & (df_raw['fecha'] <= f_fin)]
        
        # Cálculos
        ing_registrados = df_mes[df_mes['tipo'] == 'INGRESO']['monto'].sum()
        total_ingresos = ing_registrados if ing_registrados > 0 else sueldo_base
        
        gastos_cash = df_mes[df_mes['tipo'] == 'GASTO']['monto'].sum()
        gastos_tj = df_mes[df_mes['tipo'] == 'COMPRA_TARJETA']['monto'].sum()
        
        # Tarjetas Vencimientos
        df_tj = df_raw[df_raw['tipo'] == 'COMPRA_TARJETA'].copy()
        vence_ahora = 0
        if not df_tj.empty:
            df_tj['fecha_vto'] = df_tj.apply(lambda x: calcular_vto_real(x['fecha'], x['cierre'], x['vto']), axis=1)
            vence_ahora = df_tj[(df_tj['fecha_vto'] >= f_ini) & (df_tj['fecha_vto'] <= f_fin)]['monto'].sum()

        disponible = total_ingresos - gastos_cash - vence_ahora

        # KPIs
        c1, c2, c3 = st.columns(3)
        c1.metric("💰 Resultado Neto", fmt_ars(total_ingresos - (gastos_cash + gastos_tj)))
        c2.metric("✅ Disponible Caja", fmt_ars(disponible), help="Ingresos - Cash - Resumen Tarjeta")
        c3.metric("💳 Pagar Tarjeta", fmt_ars(vence_ahora))

        st.divider()
        g1, g2 = st.columns([2,1])
        with g1:
            if not df_mes.empty:
                fig = px.bar(df_mes[df_mes['tipo'] != 'INGRESO'], x='fecha', y='monto', color='categoria', title="Evolución")
                st.plotly_chart(fig, use_container_width=True)
        with g2:
            if not df_mes.empty:
                st.subheader("Top Gastos")
                st.dataframe(df_mes[df_mes['tipo']!='INGRESO'].sort_values('monto', ascending=False).head(5)[['descripcion', 'monto']], use_container_width=True, hide_index=True)
    else:
        st.info("Sin datos. Usá 'Cargar' para empezar.")

# ==========================================
# 2. CALENDARIO (NUEVO)
# ==========================================
elif menu == "📅 Calendario":
    st.header(f"Agenda: {f_ini.strftime('%B %Y')}")
    df_cal = get_movimientos(f_ini, f_fin)
    if not df_cal.empty:
        df_cal = df_cal[(df_cal['fecha'] >= f_ini) & (df_cal['fecha'] <= f_fin)]
    
    # Crear Calendario Visual
    cal = calendar.Calendar()
    semanas = cal.monthdayscalendar(anio_sel, mes_sel)
    dias_semana = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]
    
    cols = st.columns(7)
    for i, d in enumerate(dias_semana):
        cols[i].markdown(f"**{d}**")
        
    for semana in semanas:
        cols = st.columns(7)
        for i, dia in enumerate(semana):
            with cols[i]:
                if dia != 0:
                    fecha_dia = date(anio_sel, mes_sel, dia)
                    st.write(f"**{dia}**")
                    if not df_cal.empty:
                        # Filtrar eventos del día
                        evs = df_cal[df_cal['fecha'] == fecha_dia]
                        ing = evs[evs['tipo']=='INGRESO']['monto'].sum()
                        gas = evs[evs['tipo']!='INGRESO']['monto'].sum()
                        
                        if ing > 0: st.markdown(f"<span style='color:green'>+${ing:,.0f}</span>", unsafe_allow_html=True)
                        if gas > 0: st.markdown(f"<span style='color:red'>-${gas:,.0f}</span>", unsafe_allow_html=True)
                        
                        if not evs.empty:
                            with st.popover("Ver"):
                                st.dataframe(evs[['descripcion', 'monto']], hide_index=True)
                else:
                    st.write("")

# ==========================================
# 3. METAS (NUEVO)
# ==========================================
elif menu == "🎯 Metas":
    st.header("Objetivos de Ahorro")
    
    tab_ver, tab_crear = st.tabs(["Mis Metas", "Nueva Meta"])
    
    with tab_ver:
        df_m = get_metas()
        if not df_m.empty:
            for _, m in df_m.iterrows():
                with st.container(border=True):
                    c1, c2, c3 = st.columns([3, 2, 1])
                    c1.subheader(m['nombre'])
                    progreso = m['ahorrado'] / m['objetivo'] if m['objetivo'] > 0 else 0
                    c1.progress(min(progreso, 1.0))
                    c1.caption(f"Meta: {fmt_ars(m['objetivo'])} | Fecha: {m['fecha_limite']}")
                    
                    nuevo_ahorro = c2.number_input(f"Ahorrado {m['nombre']}", value=float(m['ahorrado']), key=f"m_{m['id']}")
                    if c3.button("💾", key=f"bm_{m['id']}"):
                        update_meta_ahorro(m['id'], nuevo_ahorro)
                        st.rerun()
                    if c3.button("🗑️", key=f"bd_{m['id']}"):
                        delete_meta(m['id'])
                        st.rerun()
        else:
            st.info("No tenés metas. Creá una!")

    with tab_crear:
        with st.form("new_meta"):
            nom = st.text_input("Nombre (ej: Moto)")
            obj = st.number_input("Monto Objetivo", min_value=1.0)
            limite = st.date_input("Fecha Límite")
            if st.form_submit_button("Crear Meta"):
                save_meta(nom, obj, limite)
                st.success("Creada!"); st.rerun()

# ==========================================
# 4. CARGAR (CON CUOTAS Y RECURRENTES)
# ==========================================
elif menu == "➕ Cargar":
    st.title("Registrar Operación")
    
    t_manual, t_recurrente = st.tabs(["Manual / Cuotas", "🔄 Recurrentes (Suscripciones)"])
    
    with t_manual:
        tipo_op = st.radio("Tipo", ["Gasto", "Ingreso", "Pagar Tarjeta"], horizontal=True)
        with st.container(border=True):
            col1, col2 = st.columns(2)
            f = col1.date_input("Fecha", date.today())
            m = col2.number_input("Monto Total", min_value=0.0)
            d = st.text_input("Descripción")
            
            c3, c4 = st.columns(2)
            # Lógica dinámica de cuentas
            if tipo_op == "Pagar Tarjeta":
                cta_n = c3.selectbox("Desde", df_cta[df_cta['tipo']!='CREDITO']['nombre'].tolist())
                cta_dest = c4.selectbox("Tarjeta", df_cta[df_cta['tipo']=='CREDITO']['nombre'].tolist())
                cat_n = df_cat.iloc[0]['nombre']
            else:
                cta_n = c3.selectbox("Cuenta", df_cta['nombre'].tolist())
                cat_n = c4.selectbox("Categoría", df_cat['nombre'].tolist())
            
            # GESTIÓN DE CUOTAS
            cuotas = 1
            if tipo_op == "Gasto":
                cuotas = st.number_input("Cantidad de Cuotas", min_value=1, value=1, step=1)
                if cuotas > 1:
                    st.info(f"Se crearán {cuotas} gastos de {fmt_ars(m/cuotas)} cada uno.")

            if st.button("Guardar Movimiento", type="primary", use_container_width=True):
                id_c = df_cta[df_cta['nombre'] == cta_n]['id'].values[0]
                id_ct = df_cat[df_cat['nombre'] == cat_n]['id'].values[0]
                
                if tipo_op == "Pagar Tarjeta":
                    id_d = df_cta[df_cta['nombre'] == cta_dest]['id'].values[0]
                    db_save(f, m, d, id_c, id_ct, "PAGO_TARJETA", id_d)
                
                elif tipo_op == "Ingreso":
                    db_save(f, m, d, id_c, id_ct, "INGRESO")
                
                else: # Gasto con o sin cuotas
                    tp = "COMPRA_TARJETA" if df_cta[df_cta['nombre'] == cta_n]['tipo'] == 'CREDITO' else "GASTO"
                    if cuotas > 1:
                        m_cuota = m / cuotas
                        for i in range(cuotas):
                            f_pago = f + relativedelta(months=i)
                            d_cuota = f"{d} (Cuota {i+1}/{cuotas})"
                            db_save(f_pago, m_cuota, d_cuota, id_c, id_ct, tp)
                    else:
                        db_save(f, m, d, id_c, id_ct, tp)
                
                st.success("Guardado!"); time.sleep(1); st.rerun()

    with t_recurrente:
        st.subheader("Cargar Gastos Fijos del Mes")
        df_sus = get_suscripciones()
        if not df_sus.empty:
            st.write("Se cargarán los siguientes gastos con fecha de HOY:")
            st.dataframe(df_sus[['descripcion', 'monto']], hide_index=True)
            if st.button("🚀 Impactar Fijos de Este Mes"):
                count = 0
                for _, s in df_sus.iterrows():
                    db_save(date.today(), s['monto'], s['descripcion'], s['cuenta_id'], s['categoria_id'], s['tipo'])
                    count += 1
                st.success(f"{count} gastos fijos cargados."); time.sleep(2); st.rerun()
        else:
            st.warning("No tenés suscripciones configuradas. Andá a Ajustes.")

# ==========================================
# 5. HISTORIAL
# ==========================================
elif menu == "📝 Historial":
    st.title("Historial")
    ver_todo = st.checkbox("Ver TODO el historial")
    df_h = get_movimientos(date(2024,1,1), date(2027,1,1)) if ver_todo else get_movimientos(f_ini, f_fin)
    
    if ver_todo == False and not df_h.empty:
        df_h = df_h[(df_h['fecha'] >= f_ini) & (df_h['fecha'] <= f_fin)]

    tab_e, tab_d = st.tabs(["Editar", "Borrar"])
    with tab_e:
        if not df_h.empty:
            st.data_editor(df_h[['id', 'fecha', 'descripcion', 'monto', 'cuenta', 'tipo']], width="stretch", hide_index=True)
    with tab_d:
        if not df_h.empty:
            ops = {f"{r['fecha']} | {r['descripcion']}": r['id'] for _, r in df_h.iterrows()}
            sel = st.selectbox("Borrar:", ["..."] + list(ops.keys()))
            if st.button("Eliminar") and sel != "...":
                db_delete(ops[sel]); st.success("Chau!"); st.rerun()
            if st.checkbox("Borrar TODO lo visible"):
                if st.button("BORRAR MASIVO"):
                    for _, r in df_h.iterrows(): db_delete(r['id'])
                    st.rerun()

# ==========================================
# 6. TARJETAS
# ==========================================
elif menu == "💳 Tarjetas":
    st.title("Tarjetas")
    t1, t2 = st.tabs(["Configurar", "Importar"])
    with t1:
        df_c = df_cta[df_cta['tipo']=='CREDITO']
        for _, r in df_c.iterrows():
            with st.container(border=True):
                c1, c2, c3, c4 = st.columns([2,1,1,1])
                c1.write(f"**{r['nombre']}**")
                ci = c2.number_input("Cierre", 1, 31, int(r.get('dia_cierre') or 23), key=f"c{r['id']}")
                vt = c3.number_input("Vto", 1, 31, int(r.get('dia_vencimiento') or 5), key=f"v{r['id']}")
                if c4.button("💾", key=f"b{r['id']}"):
                    supabase.table("cuentas").update({"dia_cierre": ci, "dia_vencimiento": vt}).eq("id", r['id']).execute()
                    st.rerun()
    with t2:
        up = st.file_uploader("Excel Santander/Galicia/BBVA", type=['xlsx', 'csv'])
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
                st.dataframe(df_u.head(), width="stretch")
                with st.form("imp"):
                    sel = st.selectbox("Tarjeta", df_cta[df_cta['tipo']=='CREDITO']['nombre'].tolist())
                    c1, c2, c3 = st.columns(3)
                    fc = c1.selectbox("Fecha", df_u.columns); dc = c2.selectbox("Desc", df_u.columns); mc = c3.selectbox("Monto", df_u.columns)
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
                        st.success("Listo!"); st.rerun()
            except Exception as e: st.error(str(e))

# ==========================================
# 7. AJUSTES (AHORA CON SUSCRIPCIONES)
# ==========================================
elif menu == "⚙️ Ajustes":
    st.header("Configuración")
    
    with st.expander("Sueldo Base", expanded=True):
        ns = st.number_input("Neto Mensual", value=int(sueldo_base))
        if st.button("Actualizar Sueldo"):
            supabase.table("configuracion").upsert({"clave": "sueldo_mensual", "valor": str(ns)}).execute()
            st.rerun()
            
    with st.expander("Administrar Suscripciones (Fijos)"):
        st.caption("Agregá acá tus gastos fijos para cargarlos rápido cada mes.")
        with st.form("new_sus"):
            sd = st.text_input("Descripción (ej: Netflix)")
            sm = st.number_input("Monto", min_value=0.0)
            sc = st.selectbox("Cuenta Pago", df_cta['nombre'].tolist())
            sca = st.selectbox("Rubro", df_cat['nombre'].tolist())
            if st.form_submit_button("Agregar Fijo"):
                sidc = df_cta[df_cta['nombre']==sc]['id'].values[0]
                sidca = df_cat[df_cat['nombre']==sca]['id'].values[0]
                stipo = "COMPRA_TARJETA" if df_cta[df_cta['nombre']==sc]['tipo']=='CREDITO' else "GASTO"
                save_suscripcion(sd, sm, sidc, sidca, stipo)
                st.success("Agregado"); st.rerun()
        
        df_sus = get_suscripciones()
        if not df_sus.empty:
            st.dataframe(df_sus[['descripcion', 'monto']], hide_index=True)
            ds = st.selectbox("Borrar Suscripción:", ["..."] + df_sus['descripcion'].tolist())
            if st.button("Eliminar Fijo") and ds != "...":
                did = df_sus[df_sus['descripcion']==ds]['id'].values[0]
                delete_suscripcion(did)
                st.rerun()