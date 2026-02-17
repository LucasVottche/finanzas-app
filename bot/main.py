import os
import re
import asyncio
import logging
import json
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from dateutil.relativedelta import relativedelta
import io

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

# IA IMPORTACIONES
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold

# ==========================================
# 1. CONFIGURACIÓN Y CONSTANTES
# ==========================================
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_KEY")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_SECRET") or os.environ.get("TELEGRAM_TOKEN")
ALLOWED_USER_ID = os.environ.get("ALLOWED_USER_ID")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# Configuración de IA (Gemini)
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
    
    # Configuración para forzar respuesta JSON
    generation_config = {
        "temperature": 0.1,  # Baja temperatura para ser preciso
        "response_mime_type": "application/json",
    }
    
    # Configuración de seguridad: DESACTIVAR BLOQUEOS
    # Esto es CRÍTICO para que lea facturas/PDFs con direcciones o datos
    safety_settings = {
        HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
    }

    model = genai.GenerativeModel(
        'gemini-1.5-flash', 
        generation_config=generation_config,
        safety_settings=safety_settings
    )
else:
    model = None

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ==========================================
# 2. FUNCIONES DE AYUDA (LÓGICA)
# ==========================================
def fmt_money(val):
    return f"${val:,.0f}".replace(",", ".")

def get_account_by_name(name):
    try:
        res = supabase.table("cuentas").select("*").execute()
        cuentas = res.data or []
        for acc in cuentas:
            if name and name.lower() in acc['nombre'].lower(): return acc
        for acc in cuentas:
            if "efectivo" in acc['nombre'].lower(): return acc
        return cuentas[0] if cuentas else None
    except: return None

def get_smart_category(description):
    text = description.lower()
    keywords_map = {
        "Comida": ["mcdonald", "burger", "pizza", "restaurante", "cena", "almuerzo", "delivery", "pedidosya", "rappi", "cafe", "starbucks", "bar", "comidas", "bebidas", "market", "kiosco"],
        "Supermercado": ["coto", "dia", "jumbo", "carrefour", "super", "chino", "vea", "chango", "disco", "carniceria", "verduleria", "fruteria"],
        "Transporte": ["uber", "taxi", "nafta", "cabify", "sube", "tren", "bondi", "colectivo", "peaje", "estacionamiento", "shell", "ypf", "axion"],
        "Servicios": ["luz", "gas", "internet", "celular", "claro", "personal", "movistar", "flow", "cable", "edenor", "edesur", "metrogas", "abl", "agua"],
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
        
        for cat in all_cats:
            if target_cat_name.lower() in cat['nombre'].lower(): return cat
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

# --- FUNCIÓN IA PRINCIPAL ---
async def analyze_media(file_bytes, mime_type):
    if not model: return None
    try:
        # Prompt optimizado para documentos financieros
        prompt = """
        Actúa como un sistema contable automatizado.
        Analiza este archivo (Imagen o PDF).
        
        Extrae la siguiente información en formato JSON estricto:
        {
            "monto": numero (float, usa punto. Ej: 1500.50. Busca el TOTAL final a pagar),
            "descripcion": "string breve (Nombre del comercio o motivo)",
            "fecha": "YYYY-MM-DD" (Busca la fecha del comprobante. Si no hay, null)
        }
        
        Reglas:
        1. Si hay subtotales e impuestos, busca el "Total" o "Importe Final".
        2. Si es una transferencia, usa "Transferencia a [Destinatario]" como descripción.
        3. Ignora códigos de barras o números de serie.
        """
        
        part = {"mime_type": mime_type, "data": file_bytes}
        
        # Llamada a Gemini (ejecutando en thread aparte para no bloquear)
        response = await asyncio.to_thread(model.generate_content, [prompt, part])
        
        # Verificamos si la IA bloqueó la respuesta por seguridad (común en PDFs legales)
        if response.prompt_feedback and response.prompt_feedback.block_reason:
            logger.error(f"IA Bloqueada: {response.prompt_feedback.block_reason}")
            return None
            
        text_resp = response.text
        return json.loads(text_resp)
    except Exception as e:
        logger.error(f"Error IA Analysis: {e}")
        return None

# ==========================================
# 3. HANDLERS TELEGRAM
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
    await update.message.reply_text("👋 *Bot Finanzas Pro*\nEscribe gastos, manda fotos/PDFs o usa el menú.", parse_mode=ParseMode.MARKDOWN)
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
            await update.message.reply_text("🤷‍♂️ Nada reciente para eliminar.")
    except Exception as e:
        logger.error(f"Undo error: {e}")
        await update.message.reply_text("❌ Error al deshacer.")

# --- HANDLER PARA ARCHIVOS (FOTOS Y DOCUMENTOS PDF) ---
async def handle_files(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if ALLOWED_USER_ID and str(update.effective_user.id) != str(ALLOWED_USER_ID): return

    if not model:
        await update.message.reply_text("⚠️ Error: GEMINI_API_KEY no configurada.")
        return

    # Acción de escribiendo...
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    status_msg = await update.message.reply_text("👀 Analizando archivo...")
    
    try:
        file_obj = None
        mime = ""
        
        # CASO 1: DOCUMENTO (PDF o Imagen enviada "como archivo")
        if update.message.document:
            mime = update.message.document.mime_type
            # Verificación básica de tipos soportados por Gemini
            if mime not in ["application/pdf", "image/jpeg", "image/png", "image/webp"]:
                await status_msg.edit_text(f"❌ Formato '{mime}' no soportado. Envía PDF o Imágenes.")
                return
            file_obj = await update.message.document.get_file()

        # CASO 2: FOTO (Imagen comprimida normal de Telegram)
        elif update.message.photo:
            # Tomamos la resolución más alta
            file_obj = await update.message.photo[-1].get_file()
            mime = "image/jpeg"
        
        else:
            await status_msg.edit_text("❌ No se detectó un archivo válido.")
            return

        # Descargar el archivo a memoria
        file_bytes = await file_obj.download_as_bytearray()
        
        # PROCESAR CON IA
        data = await analyze_media(file_bytes, mime)
        
        if not data:
            await status_msg.edit_text("❌ La IA no pudo leer el archivo. Intenta una foto más clara.")
            return

        monto = float(data.get("monto", 0))
        desc = data.get("descripcion", "Gasto Archivo")
        fecha_str = data.get("fecha")
        
        # Procesar Fecha
        fecha_gasto = date.today()
        if fecha_str:
            try: fecha_gasto = datetime.strptime(fecha_str, "%Y-%m-%d").date()
            except: pass # Si falla, queda hoy

        # Categorizar
        cta = get_account_by_name("Efectivo")
        cat = get_smart_category(desc)
        
        if not cta or not cat:
            await status_msg.edit_text("❌ Error: Faltan categorías/cuentas en la DB.")
            return

        # Guardar en Supabase
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
            f"✅ *Gasto Registrado*\n📝 {desc}\n💲 `{fmt_money(monto)}`\n📂 {cat['nombre']}\n📅 {fecha_gasto}",
            parse_mode=ParseMode.MARKDOWN
        )

    except Exception as e:
        logger.error(f"File Handler Error: {e}")
        await status_msg.edit_text("❌ Error procesando el archivo.")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if ALLOWED_USER_ID and str(update.effective_user.id) != str(ALLOWED_USER_ID): return
    text = update.message.text

    if text == "💰 Balance Mes": await reply_balance(update, context); return
    if text == "❓ Ayuda": await help_command(update, context); return

    match = re.search(r'(\d+([.,]\d{1,2})?)', text)
    if not match: 
        await update.message.reply_text("🤷‍♂️ Primero el monto (ej: 1500 taxi).")
        return

    monto = float(match.group(1).replace(',', '.'))
    clean_text = text.replace(match.group(0), '').strip()
    
    fecha_gasto = date.today()
    match_d = re.search(r'(\d{4}-\d{2}-\d{2})', clean_text)
    if match_d:
        try:
            fecha_gasto = datetime.strptime(match_d.group(1), "%Y-%m-%d").date()
            clean_text = clean_text.replace(match_d.group(1), '').strip()
        except: pass

    acc = None
    try:
        all_acc = supabase.table("cuentas").select("*").execute().data or []
        words = clean_text.split()
        desc_w = []
        for w in words:
            found = False
            for a in all_acc:
                if w.lower() in a['nombre'].lower(): acc = a; found = True; break
            if not found: desc_w.append(w)
        clean_text = " ".join(desc_w)
    except: pass
    
    if not acc: acc = get_account_by_name("Efectivo")
    desc = clean_text or "Gasto Telegram"
    cat = get_smart_category(desc)

    try:
        if acc.get('tipo') == 'CREDITO':
            c = supabase.table("compras_tarjeta").insert({
                "fecha_compra": str(fecha_gasto), "monto_total": monto, "cuotas_total": 1,
                "cuenta_id": acc['id'], "categoria_id": cat['id'], "descripcion": desc, "source": "telegram_bot", "merchant": desc
            }).execute()
            if c.data:
                supabase.table("cuotas_tarjeta").insert({
                    "compra_id": c.data[0]['id'], "nro_cuota": 1, "fecha_cuota": str(fecha_gasto), "monto_cuota": monto, "estado": "pendiente"
                }).execute()
                await update.message.reply_text(f"💳 *Tarjeta*\n📝 {desc}\n💲 `{fmt_money(monto)}`", parse_mode=ParseMode.MARKDOWN)
        else:
            supabase.table("movimientos").insert({
                "fecha": str(fecha_gasto), "monto": monto, "descripcion": desc,
                "cuenta_id": acc['id'], "categoria_id": cat['id'], "tipo": "GASTO", "source": "telegram_bot"
            }).execute()
            await update.message.reply_text(f"✅ *Guardado*\n📝 {desc}\n💲 `{fmt_money(monto)}`", parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        logger.error(f"Text Handler Error: {e}")
        await update.message.reply_text("❌ Error DB.")

# ==========================================
# 4. LIFESPAN / STARTUP
# ==========================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    if not TELEGRAM_TOKEN:
        logger.error("No token found")
        yield
        return
        
    bot = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    bot.add_handler(CommandHandler("start", start))
    bot.add_handler(CommandHandler("saldo", reply_balance))
    bot.add_handler(CommandHandler("ayuda", help_command))
    bot.add_handler(CommandHandler("deshacer", undo_last))
    
    # FILTRO IMPORTANTE: Acepta Fotos OR Documentos (PDF), pero NO comandos
    file_filter = (filters.PHOTO | filters.Document.ALL) & ~filters.COMMAND
    bot.add_handler(MessageHandler(file_filter, handle_files))
    
    bot.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    await bot.initialize()
    try: await bot.bot.delete_webhook(drop_pending_updates=True)
    except: pass
    await bot.start()
    await bot.updater.start_polling(allowed_updates=Update.ALL_TYPES)
    
    logger.info("Bot iniciado...")
    yield
    
    await bot.updater.stop()
    await bot.stop()
    await bot.shutdown()

app = FastAPI(lifespan=lifespan)

@app.get("/")
def health(): return {"status": "ok", "mode": "PDF_FIXED"}