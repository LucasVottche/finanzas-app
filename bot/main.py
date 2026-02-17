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
from telegram.constants import ParseMode
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters

# --- IMPORTANTE: Librería de IA ---
import google.generativeai as genai
from PIL import Image

# ==========================================
# 1. CONFIGURACIÓN
# ==========================================
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_KEY")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_SECRET") or os.environ.get("TELEGRAM_TOKEN")
ALLOWED_USER_ID = os.environ.get("ALLOWED_USER_ID")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY") # Nueva Variable

# Configurar Supabase
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# Configurar Gemini (IA)
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
    # Usamos Gemini 1.5 Flash que es rápido y barato/gratis
    model = genai.GenerativeModel('gemini-1.5-flash')
else:
    model = None

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ==========================================
# 2. FUNCIONES DE AYUDA
# ==========================================
def fmt_money(val):
    return f"${val:,.0f}".replace(",", ".")

def get_account_by_name(name):
    try:
        res = supabase.table("cuentas").select("*").execute()
        cuentas = res.data or []
        for acc in cuentas:
            if name.lower() in acc['nombre'].lower(): return acc
        for acc in cuentas:
            if "efectivo" in acc['nombre'].lower(): return acc
        return cuentas[0] if cuentas else None
    except: return None

def get_smart_category(description):
    """Categorización inteligente por texto."""
    text = description.lower()
    keywords_map = {
        "Comida": ["mcdonald", "burger", "pizza", "restaurante", "cena", "almuerzo", "delivery", "pedidosya", "rappi", "cafe", "starbucks", "bar", "confiteria"],
        "Supermercado": ["coto", "dia", "jumbo", "carrefour", "super", "chino", "vea", "chango", "disco", "carniceria", "verduleria", "market", "almacen"],
        "Transporte": ["uber", "taxi", "nafta", "cabify", "sube", "tren", "bondi", "colectivo", "peaje", "estacionamiento", "shell", "ypf", "axion"],
        "Servicios": ["luz", "gas", "internet", "celular", "claro", "personal", "movistar", "flow", "cable", "edenor", "edesur", "metrogas"],
        "Salud": ["farmacia", "medico", "doctor", "remedios", "obra social", "dentista"],
        "Salidas": ["cine", "boliche", "teatro", "entrada", "recital"],
        "Ropa": ["zapatillas", "remera", "pantalon", "nike", "adidas", "zara", "shopping"]
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
            if target_cat_name.lower() in cat['nombre'].lower():
                return cat
        
        # Fallback a General
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

        res = supabase.table("movimientos").select("tipo, monto")\
            .gte("fecha", str(first_day)).lte("fecha", str(last_day)).execute()
        
        data = res.data or []
        ingresos_registrados = sum(d['monto'] for d in data if d['tipo'] == 'INGRESO')
        gastos = sum(d['monto'] for d in data if d['tipo'] in ['GASTO', 'COMPRA_TARJETA'])
        
        total_ingresos = ingresos_registrados if ingresos_registrados > 0 else sueldo_base
        return total_ingresos, gastos
    except Exception as e:
        logger.error(f"Error balance: {e}")
        return 0, 0

# --- NUEVA FUNCIÓN: PROCESAR IMAGEN CON GEMINI ---
async def analyze_receipt_image(image_bytes):
    if not model:
        return None
    
    try:
        # Prompt para la IA
        prompt = """
        Analiza esta imagen de un ticket o comprobante de pago.
        Extrae la siguiente información en formato JSON puro (sin markdown):
        {
            "monto": float (el total pagado),
            "descripcion": string (nombre del comercio o resumen corto),
            "fecha": string (formato YYYY-MM-DD, si no hay fecha usa hoy)
        }
        Si no encuentras el comercio, pon "Gasto Ticket".
        Si no encuentras la fecha, usa la fecha de hoy.
        Solo devuelve el JSON.
        """
        
        # Abrir imagen desde memoria
        img = Image.open(io.BytesIO(image_bytes))
        
        # Llamar a Gemini
        response = await asyncio.to_thread(model.generate_content, [prompt, img])
        text_resp = response.text.replace('```json', '').replace('```', '').strip()
        
        data = json.loads(text_resp)
        return data
    except Exception as e:
        logger.error(f"Error Gemini: {e}")
        return None

# ==========================================
# 3. HANDLERS
# ==========================================

async def reply_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ing, gas = get_monthly_balance()
    neto = ing - gas
    meses = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]
    mes_nombre = meses[date.today().month - 1]

    await update.message.reply_text(
        f"📅 *Balance {mes_nombre}*\n\n"
        f"📥 Ingresos: `{fmt_money(ing)}`\n"
        f"🛒 Consumo:  `{fmt_money(gas)}`\n"
        f"-------------------\n"
        f"💵 *Neto: {fmt_money(neto)}*",
        parse_mode=ParseMode.MARKDOWN
    )

async def show_menu(update: Update):
    keyboard = [[KeyboardButton("💰 Balance Mes"), KeyboardButton("❓ Ayuda")]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text("¿Qué quieres hacer?", reply_markup=reply_markup)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 *Bot Finanzas Pro*\n\n"
        "Escribe un gasto (`1500 Cena`), mándame una **FOTO** 📸 de un ticket, o usa los botones.",
        parse_mode=ParseMode.MARKDOWN
    )
    await show_menu(update)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "💡 *Guía Rápida:*\n\n"
        "📸 *Fotos:* Mándame foto de un ticket y lo cargo solo.\n"
        "1️⃣ *Texto:* `1500 Super`\n"
        "2️⃣ *Fecha:* `50000 Alquiler 2026-04-01`\n"
        "3️⃣ *Tarjeta:* `25000 Nike Visa`\n"
        "4️⃣ *Deshacer:* Usa /deshacer para borrar el último.\n"
    )
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

async def undo_last(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        last_mov = supabase.table("movimientos").select("*").eq("source", "telegram_bot").order("created_at", desc=True).limit(1).execute()
        last_card = supabase.table("compras_tarjeta").select("*").eq("source", "telegram_bot").order("created_at", desc=True).limit(1).execute()
        
        mov_data = last_mov.data[0] if last_mov.data else None
        card_data = last_card.data[0] if last_card.data else None
        
        to_delete = None
        table_name = ""
        
        if mov_data and card_data:
            t_mov = datetime.fromisoformat(mov_data['created_at'].replace('Z', '+00:00'))
            t_card = datetime.fromisoformat(card_data['created_at'].replace('Z', '+00:00'))
            if t_mov > t_card:
                to_delete = mov_data; table_name = "movimientos"
            else:
                to_delete = card_data; table_name = "compras_tarjeta"
        elif mov_data: to_delete = mov_data; table_name = "movimientos"
        elif card_data: to_delete = card_data; table_name = "compras_tarjeta"

        if to_delete:
            desc = to_delete.get('descripcion', '-')
            monto = to_delete.get('monto') or to_delete.get('monto_total')
            if table_name == "compras_tarjeta":
                supabase.table("cuotas_tarjeta").delete().eq("compra_id", to_delete['id']).execute()
            supabase.table(table_name).delete().eq("id", to_delete['id']).execute()
            await update.message.reply_text(f"🗑️ *Eliminado:* {desc} (${monto})", parse_mode=ParseMode.MARKDOWN)
        else:
            await update.message.reply_text("🤷‍♂️ Nada reciente para borrar.")
    except Exception as e:
        logger.error(f"Error undo: {e}")
        await update.message.reply_text("❌ Error al deshacer.")

# --- HANDLER PARA FOTOS ---
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Seguridad
    if ALLOWED_USER_ID and str(update.effective_user.id) != str(ALLOWED_USER_ID):
        return

    if not model:
        await update.message.reply_text("⚠️ La IA no está configurada (falta GEMINI_API_KEY).")
        return

    status_msg = await update.message.reply_text("👀 Analizando ticket con IA...")
    
    try:
        # 1. Descargar foto
        photo_file = await update.message.photo[-1].get_file()
        img_bytes = await photo_file.download_as_bytearray()
        
        # 2. Analizar con Gemini
        data = await analyze_receipt_image(img_bytes)
        
        if not data:
            await status_msg.edit_text("❌ No pude leer el ticket.")
            return
            
        monto = float(data.get("monto", 0))
        descripcion = data.get("descripcion", "Gasto Foto")
        fecha_str = data.get("fecha")
        
        # Lógica de guardado estándar
        fecha_gasto = date.today()
        if fecha_str:
            try: fecha_gasto = datetime.strptime(fecha_str, "%Y-%m-%d").date()
            except: pass

        # Cuenta y Categoría
        target_account = get_account_by_name("Efectivo") # Por defecto efectivo en fotos
        categoria = get_smart_category(descripcion)
        
        if not target_account or not categoria:
            await status_msg.edit_text("❌ Error config DB.")
            return

        # Guardar (Asumimos Gasto normal para fotos por ahora)
        supabase.table("movimientos").insert({
            "fecha": str(fecha_gasto),
            "monto": monto,
            "descripcion": descripcion,
            "cuenta_id": target_account['id'],
            "categoria_id": categoria['id'],
            "tipo": "GASTO",
            "source": "telegram_bot"
        }).execute()
        
        await status_msg.edit_text(
            f"✅ *Ticket Procesado*\n\n"
            f"📝 {descripcion}\n"
            f"💲 `{fmt_money(monto)}`\n"
            f"📂 {categoria['nombre']}\n"
            f"📅 {fecha_gasto}",
            parse_mode=ParseMode.MARKDOWN
        )

    except Exception as e:
        logger.error(f"Error foto: {e}")
        await status_msg.edit_text("❌ Error procesando la imagen.")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Seguridad
    if ALLOWED_USER_ID and str(update.effective_user.id) != str(ALLOWED_USER_ID):
        await update.message.reply_text("⛔ No autorizado.")
        return

    text = update.message.text

    if text == "💰 Balance Mes":
        await reply_balance(update, context); return
    if text == "❓ Ayuda":
        await help_command(update, context); return

    # Parseo Texto
    match_monto = re.search(r'(\d+([.,]\d{1,2})?)', text)
    if not match_monto:
        await update.message.reply_text("🤷‍♂️ Escribe el monto primero (ej: `2500 Taxi`).", parse_mode=ParseMode.MARKDOWN); return

    monto = float(match_monto.group(1).replace(',', '.'))
    clean_text = text.replace(match_monto.group(0), '').strip()
    
    fecha_gasto = date.today()
    match_date = re.search(r'(\d{4}-\d{2}-\d{2})', clean_text)
    if match_date:
        try:
            fecha_str = match_date.group(1)
            fecha_gasto = datetime.strptime(fecha_str, "%Y-%m-%d").date()
            clean_text = clean_text.replace(fecha_str, '').strip()
        except: pass

    # Cuenta
    target_account = None
    try:
        all_accounts = supabase.table("cuentas").select("nombre, id, tipo").execute().data or []
        desc_words = []
        for word in clean_text.split():
            is_acc = False
            for acc in all_accounts:
                if word.lower() in acc['nombre'].lower():
                    target_account = acc; is_acc = True; break
            if not is_acc: desc_words.append(word)
    except: desc_words = clean_text.split()
    
    if not target_account: target_account = get_account_by_name("Efectivo")
    descripcion = " ".join(desc_words) or "Gasto Telegram"
    
    # Categoría
    categoria = get_smart_category(descripcion)

    if not target_account or not categoria:
        await update.message.reply_text("❌ Error DB.")
        return

    try:
        if target_account['tipo'] == 'CREDITO':
            compra = supabase.table("compras_tarjeta").insert({
                "fecha_compra": str(fecha_gasto), "monto_total": monto, "cuotas_total": 1,
                "cuenta_id": target_account['id'], "categoria_id": categoria['id'],
                "descripcion": descripcion, "source": "telegram_bot", "merchant": descripcion
            }).execute()
            if compra.data:
                supabase.table("cuotas_tarjeta").insert({
                    "compra_id": compra.data[0]['id'], "nro_cuota": 1, "fecha_cuota": str(fecha_gasto),
                    "monto_cuota": monto, "estado": "pendiente"
                }).execute()
                await update.message.reply_text(f"💳 *Tarjeta*\n📝 {descripcion}\n💲 `{fmt_money(monto)}`\n📂 {categoria['nombre']}", parse_mode=ParseMode.MARKDOWN)
        else:
            supabase.table("movimientos").insert({
                "fecha": str(fecha_gasto), "monto": monto, "descripcion": descripcion,
                "cuenta_id": target_account['id'], "categoria_id": categoria['id'],
                "tipo": "GASTO", "source": "telegram_bot"
            }).execute()
            await update.message.reply_text(f"✅ *Guardado*\n📝 {descripcion}\n💲 `{fmt_money(monto)}`\n📂 {categoria['nombre']}", parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        logger.error(f"Error DB: {e}"); await update.message.reply_text("❌ Error guardando.")

# ==========================================
# 4. LIFESPAN & APP
# ==========================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    if not TELEGRAM_TOKEN:
        logger.error("Falta TELEGRAM_TOKEN")
        yield; return

    bot_app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    
    bot_app.add_handler(CommandHandler("start", start))
    bot_app.add_handler(CommandHandler("saldo", reply_balance))
    bot_app.add_handler(CommandHandler("ayuda", help_command))
    bot_app.add_handler(CommandHandler("deshacer", undo_last))
    
    # Handler para fotos
    bot_app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    # Handler para texto
    bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    await bot_app.initialize()
    try: await bot_app.bot.delete_webhook(drop_pending_updates=True)
    except: pass
    
    await bot_app.start()
    await bot_app.updater.start_polling(allowed_updates=Update.ALL_TYPES)
    logger.info("🤖 Bot con IA (Vision) iniciado!")
    
    yield
    
    await bot_app.updater.stop()
    await bot_app.stop()
    await bot_app.shutdown()

app = FastAPI(lifespan=lifespan)

@app.get("/")
def health_check(): return {"status": "ok", "bot": "ai_enabled"}