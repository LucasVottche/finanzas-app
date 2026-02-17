import os
import re
import asyncio
import logging
import json
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from dateutil.relativedelta import relativedelta

from fastapi import FastAPI
from supabase import create_client
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.constants import ParseMode, ChatAction
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    CommandHandler,
    MessageHandler,
    filters
)

# IA
import google.generativeai as genai

# ==========================================
# 1. CONFIGURACIÓN
# ==========================================
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_KEY")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_SECRET") or os.environ.get("TELEGRAM_TOKEN")
ALLOWED_USER_ID = os.environ.get("ALLOWED_USER_ID")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
    # Usamos configuración para forzar respuesta JSON
    generation_config = {
        "temperature": 0.2,
        "response_mime_type": "application/json",
    }
    model = genai.GenerativeModel('gemini-1.5-flash', generation_config=generation_config)
else:
    model = None

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ==========================================
# 2. FUNCIONES DE AYUDA (LOGICA DE NEGOCIO)
# ==========================================
def fmt_money(val):
    return f"${val:,.0f}".replace(",", ".")

def get_account_by_name(name):
    try:
        # Busca coincidencia exacta o parcial
        res = supabase.table("cuentas").select("*").execute()
        cuentas = res.data or []
        
        # 1. Búsqueda por nombre específico
        for acc in cuentas:
            if name and name.lower() in acc['nombre'].lower(): return acc
        
        # 2. Búsqueda de "Efectivo" como fallback
        for acc in cuentas:
            if "efectivo" in acc['nombre'].lower(): return acc
            
        # 3. Retorna la primera cuenta si no hay match
        return cuentas[0] if cuentas else None
    except: return None

def get_smart_category(description):
    text = description.lower()
    keywords_map = {
        "Comida": ["mcdonald", "burger", "pizza", "restaurante", "cena", "almuerzo", "delivery", "pedidosya", "rappi", "cafe", "starbucks", "bar", "comidas", "bebidas", "market", "kiosco"],
        "Supermercado": ["coto", "dia", "jumbo", "carrefour", "super", "chino", "vea", "chango", "disco", "carniceria", "verduleria", "fruteria"],
        "Transporte": ["uber", "taxi", "nafta", "cabify", "sube", "tren", "bondi", "colectivo", "peaje", "estacionamiento", "shell", "ypf", "axion"],
        "Servicios": ["luz", "gas", "internet", "celular", "claro", "personal", "movistar", "flow", "cable", "edenor", "edesur", "metrogas", "abl"],
        "Salud": ["farmacia", "medico", "doctor", "remedios", "obra social", "dentista", "swiss", "osde"],
        "Salidas": ["cine", "boliche", "teatro", "entrada", "recital", "juego"],
        "Ropa": ["zapatillas", "remera", "pantalon", "nike", "adidas", "zara", "shopping", "indumentaria"],
        "Transferencias": ["transferencia", "envio", "pago a", "destinatario"]
    }

    try:
        res = supabase.table("categorias").select("*").execute()
        all_cats = res.data or []
        target_cat_name = "General"

        found = False
        for cat_name, terms in keywords_map.items():
            for term in terms:
                if term in text:
                    target_cat_name = cat_name
                    found = True
                    break
            if found: break
        
        # Buscar la categoría en la DB
        for cat in all_cats:
            if target_cat_name.lower() in cat['nombre'].lower(): return cat
        
        # Fallback a "General" o la primera
        for cat in all_cats:
            if "general" in cat['nombre'].lower(): return cat
        return all_cats[0] if all_cats else None
    except: return None

def get_base_salary():
    try:
        res = supabase.table("configuracion").select("valor").eq("clave", "sueldo_mensual").execute()
        if res.data: return float(res.data[0]['valor'])
        return 0.0
    except: return 0.0

def get_monthly_balance():
    try:
        today = date.today()
        first_day = date(today.year, today.month, 1)
        last_day = first_day + relativedelta(months=1) - timedelta(days=1)
        
        sueldo_base = get_base_salary()
        
        res = supabase.table("movimientos").select("tipo, monto").gte("fecha", str(first_day)).lte("fecha", str(last_day)).execute()
        data = res.data or []
        
        ing = sum(d['monto'] for d in data if d['tipo'] == 'INGRESO')
        gas = sum(d['monto'] for d in data if d['tipo'] in ['GASTO', 'COMPRA_TARJETA'])
        
        return (ing if ing > 0 else sueldo_base), gas
    except: return 0, 0

# --- FUNCIÓN IA MULTIMEDIA (PDF/FOTO) ---
async def analyze_media(file_bytes, mime_type):
    if not model: return None
    try:
        # Prompt mejorado para extracción financiera precisa
        prompt = """
        Eres un asistente contable experto. Analiza este comprobante (Ticket, Factura o Transferencia).
        Extrae la siguiente información en formato JSON estricto:
        
        1. "monto": El total final a pagar (número flotante, usa punto decimal). Busca "Total", "Importe", "Monto". Ignora subtotales.
        2. "descripcion": El nombre del comercio o motivo (string corto). Si es transferencia, pon "Transferencia a [Nombre]".
        3. "fecha": La fecha del comprobante en formato "YYYY-MM-DD". Si no hay fecha visible, usa null.
        
        Ejemplo de salida deseada:
        {"monto": 1250.50, "descripcion": "Supermercado Coto", "fecha": "2024-02-20"}
        """
        
        part = {"mime_type": mime_type, "data": file_bytes}
        
        # Llamada a Gemini
        response = await asyncio.to_thread(model.generate_content, [prompt, part])
        
        # Al usar response_mime_type='application/json', el texto ya debería ser JSON válido
        return json.loads(response.text)
    except Exception as e:
        logger.error(f"Error IA: {e}")
        return None

# ==========================================
# 3. HANDLERS
# ==========================================

async def reply_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ing, gas = get_monthly_balance()
    mes_nombre = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"][date.today().month - 1]
    
    await update.message.reply_text(
        f"📅 *Balance {mes_nombre}*\n\n📥 Ingresos: `{fmt_money(ing)}`\n🛒 Consumo:  `{fmt_money(gas)}`\n-------------------\n💵 *Neto: {fmt_money(ing - gas)}*",
        parse_mode=ParseMode.MARKDOWN
    )

async def show_menu(update: Update):
    kb = [[KeyboardButton("💰 Balance Mes"), KeyboardButton("❓ Ayuda")]]
    await update.message.reply_text("¿Qué quieres hacer?", reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True))

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 *Bot Finanzas Pro*\nEscribe gastos (ej: `5000 gym`), manda fotos/PDFs o usa el menú.", parse_mode=ParseMode.MARKDOWN)
    await show_menu(update)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "💡 *Ayuda:*\n📸 Manda **Fotos** o **PDFs** de comprobantes.\n✍️ Escribe: `1500 Super`\n↩️ `/deshacer` para borrar último.",
        parse_mode=ParseMode.MARKDOWN
    )

async def undo_last(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        last_mov = supabase.table("movimientos").select("*").eq("source", "telegram_bot").order("created_at", desc=True).limit(1).execute()
        last_card = supabase.table("compras_tarjeta").select("*").eq("source", "telegram_bot").order("created_at", desc=True).limit(1).execute()
        
        m_d = last_mov.data[0] if last_mov.data else None
        c_d = last_card.data[0] if last_card.data else None
        
        target = None
        table = ""
        
        if m_d and c_d:
            tm = datetime.fromisoformat(m_d['created_at'].replace('Z', '+00:00'))
            tc = datetime.fromisoformat(c_d['created_at'].replace('Z', '+00:00'))
            if tm > tc: target = m_d; table = "movimientos"
            else: target = c_d; table = "compras_tarjeta"
        elif m_d: target = m_d; table = "movimientos"
        elif c_d: target = c_d; table = "compras_tarjeta"

        if target:
            if table == "compras_tarjeta":
                supabase.table("cuotas_tarjeta").delete().eq("compra_id", target['id']).execute()
            supabase.table(table).delete().eq("id", target['id']).execute()
            monto = target.get('monto') or target.get('monto_total')
            await update.message.reply_text(f"🗑️ Eliminado: {target.get('descripcion')} ({fmt_money(monto)})")
        else:
            await update.message.reply_text("🤷‍♂️ Nada reciente para borrar.")
    except Exception as e:
        logger.error(f"Undo error: {e}")
        await update.message.reply_text("❌ Error al deshacer.")

# --- HANDLER UNIFICADO MEJORADO (FOTO Y DOCUMENTO) ---
async def handle_files(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if ALLOWED_USER_ID and str(update.effective_user.id) != str(ALLOWED_USER_ID): return

    if not model:
        await update.message.reply_text("⚠️ Falta configurar GEMINI_API_KEY en variables de entorno.")
        return

    # Indicador visual de "Escribiendo..."
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    status_msg = await update.message.reply_text("👀 Analizando comprobante...")
    
    try:
        file_obj = None
        mime = ""
        
        # 1. Detectar si es DOCUMENTO (PDF o Imagen como archivo)
        if update.message.document:
            mime = update.message.document.mime_type
            # Filtramos solo lo que Gemini suele soportar bien
            if mime not in ["application/pdf", "image/jpeg", "image/png", "image/webp"]:
                await status_msg.edit_text(f"❌ Formato no soportado ({mime}). Envía PDF o JPG/PNG.")
                return
            file_obj = await update.message.document.get_file()

        # 2. Detectar si es FOTO (Comprimida de Telegram)
        elif update.message.photo:
            # Telegram manda varias resoluciones, tomamos la última (más grande)
            file_obj = await update.message.photo[-1].get_file()
            mime = "image/jpeg"
        
        else:
            await status_msg.edit_text("❌ No se detectó archivo válido.")
            return

        # Descargar archivo a memoria
        file_bytes = await file_obj.download_as_bytearray()
        
        # --- PROCESAMIENTO IA ---
        data = await analyze_media(file_bytes, mime)
        
        if not data:
            await status_msg.edit_text("❌ La IA no pudo leer el archivo. Intenta con una foto más clara.")
            return

        monto = float(data.get("monto", 0))
        desc = data.get("descripcion", "Gasto Archivo")
        fecha_str = data.get("fecha")
        
        # Validación de fecha
        fecha_gasto = date.today()
        if fecha_str:
            try: 
                fecha_gasto = datetime.strptime(fecha_str, "%Y-%m-%d").date()
            except: 
                # Si falla la fecha, usamos hoy, pero logueamos
                logger.warning(f"Fecha inválida recibida: {fecha_str}")
                pass

        # Lógica de categorías y cuentas
        cta = get_account_by_name("Efectivo") 
        cat = get_smart_category(desc)
        
        if not cta or not cat:
            await status_msg.edit_text("❌ Error configuración base de datos (Cuentas/Categorías).")
            return

        # Inserción en BD
        supabase.table("movimientos").insert({
            "fecha": str(fecha_gasto), 
            "monto": monto, 
            "descripcion": desc,
            "cuenta_id": cta['id'], 
            "categoria_id": cat['id'], 
            "tipo": "GASTO", 
            "source": "telegram_bot"
        }).execute()

        await status_msg.edit_text(
            f"✅ *Gasto Registrado*\n"
            f"📝 {desc}\n"
            f"💲 `{fmt_money(monto)}`\n"
            f"📂 {cat['nombre']}\n"
            f"📅 {fecha_gasto}",
            parse_mode=ParseMode.MARKDOWN
        )

    except Exception as e:
        logger.error(f"File process error: {e}")
        await status_msg.edit_text("❌ Ocurrió un error procesando el archivo.")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if ALLOWED_USER_ID and str(update.effective_user.id) != str(ALLOWED_USER_ID): return
    text = update.message.text

    if text == "💰 Balance Mes": await reply_balance(update, context); return
    if text == "❓ Ayuda": await help_command(update, context); return

    # Detectar monto con regex (soporta 1000, 1000.50, 1000,50)
    match = re.search(r'(\d+([.,]\d{1,2})?)', text)
    if not match: 
        await update.message.reply_text("🤷‍♂️ No entendí. Escribe primero el monto (ej: '1500 taxi').")
        return

    monto = float(match.group(1).replace(',', '.'))
    clean_text = text.replace(match.group(0), '').strip()
    
    # Detectar fecha manual si el usuario escribe YYYY-MM-DD
    fecha_gasto = date.today()
    match_d = re.search(r'(\d{4}-\d{2}-\d{2})', clean_text)
    if match_d:
        try:
            fecha_gasto = datetime.strptime(match_d.group(1), "%Y-%m-%d").date()
            clean_text = clean_text.replace(match_d.group(1), '').strip()
        except: pass

    # Detectar Cuenta en el texto
    acc = None
    try:
        all_acc = supabase.table("cuentas").select("*").execute().data or []
        words = clean_text.split()
        desc_w = []
        for w in words:
            found = False
            for a in all_acc:
                if w.lower() in a['nombre'].lower(): 
                    acc = a; found = True; break
            if not found: desc_w.append(w)
        clean_text = " ".join(desc_w)
    except: pass
    
    if not acc: acc = get_account_by_name("Efectivo")
    desc = clean_text or "Gasto Telegram"
    cat = get_smart_category(desc)

    try:
        if acc.get('tipo') == 'CREDITO':
            c = supabase.table("compras_tarjeta").insert({
                "fecha_compra": str(fecha_gasto), 
                "monto_total": monto, 
                "cuotas_total": 1,
                "cuenta_id": acc['id'], 
                "categoria_id": cat['id'], 
                "descripcion": desc, 
                "source": "telegram_bot", 
                "merchant": desc
            }).execute()
            
            if c.data:
                supabase.table("cuotas_tarjeta").insert({
                    "compra_id": c.data[0]['id'], 
                    "nro_cuota": 1, 
                    "fecha_cuota": str(fecha_gasto), 
                    "monto_cuota": monto, 
                    "estado": "pendiente"
                }).execute()
                await update.message.reply_text(f"💳 *Tarjeta Registrada*\n📝 {desc}\n💲 `{fmt_money(monto)}`", parse_mode=ParseMode.MARKDOWN)
        else:
            supabase.table("movimientos").insert({
                "fecha": str(fecha_gasto), 
                "monto": monto, 
                "descripcion": desc,
                "cuenta_id": acc['id'], 
                "categoria_id": cat['id'], 
                "tipo": "GASTO", 
                "source": "telegram_bot"
            }).execute()
            await update.message.reply_text(f"✅ *Gasto Registrado*\n📝 {desc}\n💲 `{fmt_money(monto)}`", parse_mode=ParseMode.MARKDOWN)
    except Exception as e: 
        logger.error(f"DB Error: {e}")
        await update.message.reply_text("❌ Error guardando en base de datos.")

# ==========================================
# 4. LIFESPAN Y ARRANQUE
# ==========================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    if not TELEGRAM_TOKEN:
        logger.error("No TELEGRAM_TOKEN found")
        yield
        return
        
    bot = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    
    # Comandos
    bot.add_handler(CommandHandler("start", start))
    bot.add_handler(CommandHandler("saldo", reply_balance))
    bot.add_handler(CommandHandler("ayuda", help_command))
    bot.add_handler(CommandHandler("deshacer", undo_last))
    
    # --- FILTRO MEJORADO PARA ARCHIVOS ---
    # Acepta: Fotos comprimidas O Documentos (PDFs, imágenes sin compresión)
    # Excluye comandos
    file_filter = (filters.PHOTO | filters.Document.ALL) & ~filters.COMMAND
    bot.add_handler(MessageHandler(file_filter, handle_files))
    
    # Texto plano
    bot.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    await bot.initialize()
    try: await bot.bot.delete_webhook(drop_pending_updates=True)
    except: pass
    await bot.start()
    await bot.updater.start_polling(allowed_updates=Update.ALL_TYPES)
    
    logger.info("🤖 Bot iniciado correctamente")
    
    yield
    
    await bot.updater.stop()
    await bot.stop()
    await bot.shutdown()

app = FastAPI(lifespan=lifespan)

@app.get("/")
def health(): return {"status": "ok", "mode": "smart-multimedia"}