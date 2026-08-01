import os
import random
import logging
import asyncio
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

logging.basicConfig(level=logging.INFO)

# ==============================================================================
# 1. SERVIDOR WEB FALSO PARA RENDER
# ==============================================================================
def run_dummy_server():
    port = int(os.environ.get("PORT", 8080))
    class SimpleHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"Bot Gacha is active and running!")
    server = HTTPServer(('0.0.0.0', port), SimpleHandler)
    server.serve_forever()

threading.Thread(target=run_dummy_server, daemon=True).start()

# ==============================================================================
# 2. CONFIGURACIÓN DE ADMIN, RAREZAS Y CARTAS
# ==============================================================================
ADMIN_ID = 5352886076  # Tu Telegram ID configurado

MENSAJES_PARA_DROP = 20
MINUTOS_PARA_DROP = 45

RAREZAS = {
    "UR": {"peso": 1.5, "estrellas": "⭐⭐⭐⭐⭐ [UR]"},
    "SSS": {"peso": 8.5, "estrellas": "⭐⭐⭐⭐ [SSS]"},
    "S": {"peso": 20.0, "estrellas": "⭐⭐⭐ [S]"},
    "A": {"peso": 30.0, "estrellas": "⭐⭐ [A]"},
    "B": {"peso": 40.0, "estrellas": "⭐ [B]"}
}

CARTAS = [
    {"id": "c1", "nombre": "Egirl Culona", "rareza": "B", "foto": "AgACAgEAAxkBAAEtFOJqbVSecy98r-M9Lxj1MR-5FRa7SwACfgxrG057aUes_Cb1mco0NQEAAwIAA3MAAz0E"},
    {"id": "c2", "nombre": "Nekotina", "rareza": "A", "foto": "https://i.postimg.cc/dtW678Vw/IMG-20260731-200048-385.jpg"},
    {"id": "c3", "nombre": "Puta Barata", "rareza": "S", "foto": "https://files.catbox.moe/lzqsn4.jpg"},
    {"id": "c4", "nombre": "Hane, Office Thot", "rareza": "SSS", "foto": "AgACAgEAAxkBAAMPam1cWUwK8lDOuzN88jWM9T9ZPs4AAtgOaxshNmhHfSGqf02dcssBAAMCAAN5AAM9BA"},
]

inventarios = {}          
carta_activa = {}         
ultimo_mensaje_inv = {}   
estado_inv_usuario = {}   
contador_mensajes = {}    
tareas_tiempo = {}        

def elegir_carta_aleatoria():
    pool = []
    for carta in CARTAS:
        rareza_info = RAREZAS.get(carta["rareza"], {"peso": 10.0})
        peso = int(rareza_info["peso"] * 10)
        pool.extend([carta] * peso)
    return random.choice(pool)

async def auto_borrar_comando(update: Update):
    if update.message and update.effective_chat.type in ["group", "supergroup"]:
        try:
            await update.message.delete()
        except Exception:
            pass

async def ejecutar_drop(bot, chat_id, carta_forzada=None, motivo=""):
    carta = carta_forzada if carta_forzada else elegir_carta_aleatoria()
    carta_activa[chat_id] = carta
    info_rareza = RAREZAS.get(carta["rareza"], {}).get("estrellas", carta["rareza"])

    keyboard = [[InlineKeyboardButton("🃏 ¡RECLAMAR CARTA!", callback_data=f"claim_{carta['id']}")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    subtitulo = f"\n<i>{motivo}</i>" if motivo else ""

    caption = (
        f"🚨 <b>¡UNA CARTA SALVAJE HA APARECIDO!</b> 🚨{subtitulo}\n\n"
        f"🎴 <b>{carta['nombre']}</b>\n"
        f"📊 Rareza: {info_rareza}\n\n"
        f"<i>¡El primero en presionar el botón se la queda!</i>"
    )

    try:
        await bot.send_photo(
            chat_id=chat_id,
            photo=carta["foto"],
            caption=caption,
            reply_markup=reply_markup,
            parse_mode="HTML"
        )
    except Exception as e:
        logging.error(f"Error al enviar la carta: {e}")
        await bot.send_message(
            chat_id=chat_id,
            text=f"⚠️ (Error cargando imagen)\n\n{caption}",
            reply_markup=reply_markup,
            parse_mode="HTML"
        )

def reiniciar_temporizador_chat(app_or_context, chat_id):
    if chat_id in tareas_tiempo and not tareas_tiempo[chat_id].done():
        tareas_tiempo[chat_id].cancel()

    bot = app_or_context.bot if hasattr(app_or_context, 'bot') else app_or_context

    async def _loop_tiempo():
        while True:
            await asyncio.sleep(MINUTOS_PARA_DROP * 60)
            await ejecutar_drop(bot, chat_id, motivo="Drop automático por tiempo")
            if chat_id in contador_mensajes:
                contador_mensajes[chat_id] = 0

    tareas_tiempo[chat_id] = asyncio.create_task(_loop_tiempo())

# ==============================================================================
# 3. NAVEGACIÓN DE INVENTARIO
# ==============================================================================

def generar_vista_inventario(user_id, user_name):
    todas_las_cartas = inventarios.get(user_id, [])
    if not todas_las_cartas:
        return None, None, None

    estado = estado_inv_usuario.get(user_id, {"index": 0, "filtro": "TODAS"})
    filtro = estado["filtro"]

    cartas_filtradas = todas_las_cartas if filtro == "TODAS" else [c for c in todas_las_cartas if c["rareza"] == filtro]
    if not cartas_filtradas:
        cartas_filtradas = todas_las_cartas
        filtro = "TODAS"
        estado["filtro"] = "TODAS"

    conteo_cartas = {}
    cartas_unicas = []
    for c in cartas_filtradas:
        cid = c["id"]
        if cid not in conteo_cartas:
            conteo_cartas[cid] = 1
            cartas_unicas.append(c)
        else:
            conteo_cartas[cid] += 1

    idx = estado["index"] % len(cartas_unicas)
    estado["index"] = idx
    estado_inv_usuario[user_id] = estado

    carta_actual = cartas_unicas[idx]
    cantidad_copias = conteo_cartas[carta_actual["id"]]
    info_rareza = RAREZAS.get(carta_actual["rareza"], {}).get("estrellas", carta_actual["rareza"])

    caption = (
        f"📦 <b>INVENTARIO INTERACTIVO DE @{user_name}</b>\n\n"
        f"🎴 <b>{carta_actual['nombre']}</b> (<code>{carta_actual['id']}</code>)\n"
        f"📊 Rareza: {info_rareza}\n"
        f"🔢 Tienes en posesión: <b>x{cantidad_copias}</b>\n"
        f"📑 Carta <b>{idx + 1}</b> de <b>{len(cartas_unicas)}</b> (Filtro: <code>{filtro}</code>)\n"
        f"✨ Total en tu colección: <b>{len(todas_las_cartas)}</b> cartas"
    )

    row_nav = [
        InlineKeyboardButton("◀", callback_data=f"inv_nav_{user_id}_prev"),
        InlineKeyboardButton(f"{idx + 1}/{len(cartas_unicas)}", callback_data="inv_noop"),
        InlineKeyboardButton("▶", callback_data=f"inv_nav_{user_id}_next"),
    ]
    row_filtros = [
        InlineKeyboardButton("TODAS", callback_data=f"inv_flt_{user_id}_TODAS"),
        InlineKeyboardButton("UR", callback_data=f"inv_flt_{user_id}_UR"),
        InlineKeyboardButton("SSS", callback_data=f"inv_flt_{user_id}_SSS"),
        InlineKeyboardButton("S", callback_data=f"inv_flt_{user_id}_S"),
        InlineKeyboardButton("A", callback_data=f"inv_flt_{user_id}_A"),
        InlineKeyboardButton("B", callback_data=f"inv_flt_{user_id}_B"),
    ]
    row_share = [
        InlineKeyboardButton("📢 Compartir esta carta en el chat", callback_data=f"inv_share_{user_id}_{carta_actual['id']}")
    ]

    reply_markup = InlineKeyboardMarkup([row_nav, row_filtros, row_share])
    return carta_actual["foto"], caption, reply_markup

# ==============================================================================
# 4. COMANDOS Y EVENTOS
# ==============================================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await auto_borrar_comando(update)
    chat_id = update.effective_chat.id
    reiniciar_temporizador_chat(context, chat_id)
    await update.message.reply_text(
        "✨ <b>¡Bienvenido al Sistema de Gacha de Cartas!</b> ✨\n\n"
        "Comandos disponibles:\n"
        "• <code>/drop</code> - Genera una carta en el grupo.\n"
        "• <code>/inventario</code> - Abre tu panel visual de cartas e inventario.",
        parse_mode="HTML"
    )

async def drop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await auto_borrar_comando(update)
    chat_id = update.effective_chat.id
    user = update.effective_user
    args = context.args

    carta_forzada = None
    if args and user.id == ADMIN_ID:
        carta_id = args[0]
        carta_forzada = next((c for c in CARTAS if c["id"] == carta_id), None)
        if not carta_forzada:
            msg = await context.bot.send_message(chat_id, f"❌ No existe ninguna carta con el ID <code>{carta_id}</code>.", parse_mode="HTML")
            await asyncio.sleep(5)
            try: await msg.delete()
            except: pass
            return

    await ejecutar_drop(context.bot, chat_id, carta_forzada=carta_forzada)
    contador_mensajes[chat_id] = 0
    reiniciar_temporizador_chat(context, chat_id)

async def inventario(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await auto_borrar_comando(update)
    user = update.effective_user
    chat_id = update.effective_chat.id
    nombre_usuario = user.username or user.first_name

    if user.id in ultimo_mensaje_inv:
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=ultimo_mensaje_inv[user.id])
        except Exception:
            pass

    user_cards = inventarios.get(user.id, [])
    if not user_cards:
        msg = await context.bot.send_message(
            chat_id,
            f"📦 <b>Inventario de @{nombre_usuario}</b>\n\n"
            "Tu colección está vacía actualmente. ¡Atrapa cartas presionando el botón de drop!",
            parse_mode="HTML"
        )
        ultimo_mensaje_inv[user.id] = msg.message_id
        return

    if user.id not in estado_inv_usuario:
        estado_inv_usuario[user.id] = {"index": 0, "filtro": "TODAS"}

    foto, caption, reply_markup = generar_vista_inventario(user.id, nombre_usuario)

    try:
        msg = await context.bot.send_photo(
            chat_id=chat_id,
            photo=foto,
            caption=caption,
            reply_markup=reply_markup,
            parse_mode="HTML"
        )
        ultimo_mensaje_inv[user.id] = msg.message_id
    except Exception as e:
        logging.error(f"Falló al enviar foto del inventario: {e}")
        msg = await context.bot.send_message(
            chat_id=chat_id,
            text=caption,
            reply_markup=reply_markup,
            parse_mode="HTML"
        )
        ultimo_mensaje_inv[user.id] = msg.message_id

async def inventario_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    clicker_id = query.from_user.id

    if data == "inv_noop":
        await query.answer()
        return

    partes = data.split("_")
    accion = partes[1]
    target_user_id = int(partes[2])

    if clicker_id != target_user_id:
        await query.answer("❌ Este no es tu inventario. Escribe /inventario para abrir el tuyo.", show_alert=True)
        return

    user_name = query.from_user.username or query.from_user.first_name

    if accion == "nav":
        direccion = partes[3]
        estado = estado_inv_usuario.get(clicker_id, {"index": 0, "filtro": "TODAS"})
        estado["index"] += 1 if direccion == "next" else -1
        estado_inv_usuario[clicker_id] = estado

    elif accion == "flt":
        nuevo_filtro = partes[3]
        estado_inv_usuario[clicker_id] = {"index": 0, "filtro": nuevo_filtro}

    elif accion == "share":
        carta_id = partes[3]
        cartas_usuario = inventarios.get(clicker_id, [])
        carta = next((c for c in cartas_usuario if c["id"] == carta_id), None)
        if carta:
            copias = sum(1 for c in cartas_usuario if c["id"] == carta_id)
            info_rareza = RAREZAS.get(carta["rareza"], {}).get("estrellas", carta["rareza"])
            try:
                await context.bot.send_photo(
                    chat_id=query.message.chat_id,
                    photo=carta["foto"],
                    caption=f"✨ <b>@{user_name} MUESTRA SU CARTA:</b>\n\n"
                            f"🎴 <b>{carta['nombre']}</b> (<code>{carta['id']}</code>)\n"
                            f"📊 Rareza: {info_rareza}\n"
                            f"🔢 Copias acumuladas: <b>x{copias}</b>",
                    parse_mode="HTML"
                )
            except Exception:
                await context.bot.send_message(
                    chat_id=query.message.chat_id,
                    text=f"✨ <b>@{user_name} MUESTRA SU CARTA:</b>\n\n"
                         f"🎴 <b>{carta['nombre']}</b> (<code>{carta['id']}</code>)\n"
                         f"📊 Rareza: {info_rareza}\n"
                         f"🔢 Copias acumuladas: <b>x{copias}</b>",
                    parse_mode="HTML"
                )
            await query.answer("📢 ¡Carta compartida con el grupo!")
        return

    foto, caption, reply_markup = generar_vista_inventario(clicker_id, user_name)
    if foto:
        try:
            from telegram import InputMediaPhoto
            await query.edit_message_media(
                media=InputMediaPhoto(media=foto, caption=caption, parse_mode="HTML"),
                reply_markup=reply_markup
            )
        except Exception:
            await query.answer()

async def manejar_mensajes_grupo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_chat or update.effective_chat.type not in ["group", "supergroup"]:
        return

    chat_id = update.effective_chat.id

    if chat_id not in tareas_tiempo:
        reiniciar_temporizador_chat(context, chat_id)

    contador_mensajes[chat_id] = contador_mensajes.get(chat_id, 0) + 1

    if contador_mensajes[chat_id] >= MENSAJES_PARA_DROP:
        contador_mensajes[chat_id] = 0
        await ejecutar_drop(context.bot, chat_id, motivo="Drop automático por actividad del grupo")
        reiniciar_temporizador_chat(context, chat_id)

async def claim_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    chat_id = query.message.chat_id

    if chat_id not in carta_activa or carta_activa[chat_id] is None:
        await query.answer("❌ ¡Esta carta ya fue reclamada o expiró!", show_alert=True)
        return

    carta = carta_activa[chat_id]
    carta_activa[chat_id] = None

    if user.id not in inventarios:
        inventarios[user.id] = []
    inventarios[user.id].append(carta)

    info_rareza = RAREZAS.get(carta["rareza"], {}).get("estrellas", carta["rareza"])

    await query.answer(f"🎉 ¡Felicidades! Has reclamado a {carta['nombre']}")
    try:
        await query.edit_message_caption(
            caption=f"✅ <b>CARTA RECLAMADA</b>\n\n"
                    f"🎴 <b>{carta['nombre']}</b> ({info_rareza})\n"
                    f"👤 Dueño actual: @{user.username or user.first_name}",
            reply_markup=None,
            parse_mode="HTML"
        )
    except Exception:
        await query.edit_message_text(
            text=f"✅ <b>CARTA RECLAMADA</b>\n\n"
                 f"🎴 <b>{carta['nombre']}</b> ({info_rareza})\n"
                 f"👤 Dueño actual: @{user.username or user.first_name}",
            reply_markup=None,
            parse_mode="HTML"
        )

async def dar_carta(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await auto_borrar_comando(update)
    user = update.effective_user
    chat_id = update.effective_chat.id

    if user.id != ADMIN_ID or not update.message.reply_to_message or not context.args:
        return

    carta_id = context.args[0]
    carta = next((c for c in CARTAS if c["id"] == carta_id), None)
    if not carta:
        return

    target_user = update.message.reply_to_message.from_user
    if target_user.id not in inventarios:
        inventarios[target_user.id] = []

    inventarios[target_user.id].append(carta)
    info_rareza = RAREZAS.get(carta["rareza"], {}).get("estrellas", carta["rareza"])

    await context.bot.send_message(
        chat_id,
        f"🎁 <b>¡CARTA OTORGADA!</b>\n\n"
        f"Se ha añadido <b>{carta['nombre']}</b> ({info_rareza}) al inventario de @{target_user.username or target_user.first_name}.",
        parse_mode="HTML"
    )

async def quitar_carta(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await auto_borrar_comando(update)
    user = update.effective_user
    chat_id = update.effective_chat.id

    if user.id != ADMIN_ID or not update.message.reply_to_message or not context.args:
        return

    carta_id = context.args[0]
    target_user = update.message.reply_to_message.from_user

    if target_user.id not in inventarios or not inventarios[target_user.id]:
        return

    user_cards = inventarios[target_user.id]
    carta_a_remover = next((c for c in user_cards if c["id"] == carta_id), None)

    if not carta_a_remover:
        return

    user_cards.remove(carta_a_remover)
    await context.bot.send_message(
        chat_id,
        f"🗑️ Se ha removido la carta <b>{carta_a_remover['nombre']}</b> del inventario de @{target_user.username or target_user.first_name}.",
        parse_mode="HTML"
    )

# ==============================================================================
# 5. COMANDO PARA OBTENER FILE_ID
# ==============================================================================
async def obtener_id_foto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await auto_borrar_comando(update)
    user = update.effective_user
    chat_id = update.effective_chat.id

    if user.id != ADMIN_ID:
        return

    if not update.message.reply_to_message or not update.message.reply_to_message.photo:
        msg = await context.bot.send_message(
            chat_id, 
            "⚠️ Responde a una foto escribiendo <code>/id</code> para obtener su File ID.",
            parse_mode="HTML"
        )
        await asyncio.sleep(5)
        try:
            await msg.delete()
        except Exception:
            pass
        return

    foto = update.message.reply_to_message.photo[-1]
    file_id = foto.file_id

    await context.bot.send_message(
        chat_id,
        f"✅ <b>File ID generado para tu bot:</b>\n\n"
        f"<code>{file_id}</code>\n\n"
        f"<i>(Toca el código arriba para copiarlo automáticamente)</i>",
        parse_mode="HTML"
    )

# ==============================================================================
# 6. INICIALIZACIÓN
# ==============================================================================
if __name__ == "__main__":
    TOKEN = os.environ.get("TELEGRAM_TOKEN")
    if TOKEN:
        app = ApplicationBuilder().token(TOKEN).build()
        
        # Comandos existentes
        app.add_handler(CommandHandler("start", start))
        app.add_handler(CommandHandler("drop", drop))
        app.add_handler(CommandHandler("inventario", inventario))
        app.add_handler(CommandHandler("dar", dar_carta))
        app.add_handler(CommandHandler("quitar", quitar_carta))
        
        # Nuevo comando para extraer File ID
        app.add_handler(CommandHandler("id", obtener_id_foto))
        
        # Handlers de callbacks y mensajes
        app.add_handler(CallbackQueryHandler(claim_callback, pattern="^claim_"))
        app.add_handler(CallbackQueryHandler(inventario_callback, pattern="^inv_"))
        app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), manejar_mensajes_grupo))
        
        print("🤖 Bot iniciado...")
        app.run_polling()
        
