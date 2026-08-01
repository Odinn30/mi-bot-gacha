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
# 1. SERVIDOR WEB FALSO PARA RENDER (Mantiene el servicio activo en 'Live')
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
# 2. CONFIGURACIÓN DE ADMIN, RAREZAS, CARTAS Y AUTOMATIZACIÓN
# ==============================================================================
# ⚠️ CAMBIA ESTE NÚMERO POR TU ID REAL DE TELEGRAM
ADMIN_ID = 5352886076 

# Configuraciones de Drops Automáticos
MENSAJES_PARA_DROP = 20    # Dropea una carta cada X mensajes en el chat
MINUTOS_PARA_DROP = 45     # Dropea una carta si pasan X minutos sin importar la actividad

RAREZAS = {
    "UR": {"peso": 1.5, "estrellas": "⭐⭐⭐⭐⭐ [UR]"},
    "SSS": {"peso": 8.5, "estrellas": "⭐⭐⭐⭐ [SSS]"},
    "S": {"peso": 20.0, "estrellas": "⭐⭐⭐ [S]"},
    "A": {"peso": 30.0, "estrellas": "⭐⭐ [A]"},
    "B": {"peso": 40.0, "estrellas": "⭐ [B]"}
}

CARTAS = [
    {"id": "c1", "nombre": "Guerrera Novata", "rareza": "B", "foto": "https://i.imgur.com/EJEMPLO1.jpg"},
    {"id": "c2", "nombre": "Mago del Bosque", "rareza": "A", "foto": "https://i.imgur.com/EJEMPLO2.jpg"},
    {"id": "c3", "nombre": "Caballero Oscuro", "rareza": "S", "foto": "https://i.imgur.com/EJEMPLO3.jpg"},
    {"id": "c4", "nombre": "Reina Celestial", "rareza": "SSS", "foto": "https://i.imgur.com/EJEMPLO4.jpg"},
    {"id": "c5", "nombre": "Deidad Suprema UR", "rareza": "UR", "foto": "https://i.imgur.com/EJEMPLO5.jpg"},
]

# Almacenamiento temporal en memoria
inventarios = {}          # { user_id: [carta1, carta2, ...] }
carta_activa = {}         # { chat_id: carta_actual_sin_reclamar }
ultimo_mensaje_inv = {}   # { user_id: message_id }
estado_inv_usuario = {}   # { user_id: {"index": int, "filtro": str} }
contador_mensajes = {}    # { chat_id: int }
tareas_tiempo = {}        # { chat_id: asyncio.Task }

def elegir_carta_aleatoria():
    pool = []
    for carta in CARTAS:
        rareza_info = RAREZAS.get(carta["rareza"], {"peso": 10.0})
        peso = int(rareza_info["peso"] * 10)
        pool.extend([carta] * peso)
    return random.choice(pool)

async def auto_borrar_comando(update: Update):
    """Elimina el mensaje de comando para mantener pulcro el grupo."""
    if update.message and update.effective_chat.type in ["group", "supergroup"]:
        try:
            await update.message.delete()
        except Exception:
            pass

async def ejecutar_drop(bot, chat_id, carta_forzada=None, motivo=""):
    if carta_forzada:
        carta = carta_forzada
    else:
        carta = elegir_carta_aleatoria()

    carta_activa[chat_id] = carta
    info_rareza = RAREZAS[carta["rareza"]]["estrellas"]

    keyboard = [[InlineKeyboardButton("🃏 ¡RECLAMAR CARTA!", callback_data=f"claim_{carta['id']}")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    subtitulo = f"\n_{motivo}_" if motivo else ""

    await bot.send_photo(
        chat_id=chat_id,
        photo=carta["foto"],
        caption=f"🚨 **¡UNA CARTA SALVAJE HA APARECIDO!** 🚨{subtitulo}\n\n"
                f"🎴 **{carta['nombre']}**\n"
                f"📊 Rareza: {info_rareza}\n\n"
                f"_¡El primero en presionar el botón se la queda!_",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

def reiniciar_temporizador_chat(app_or_context, chat_id):
    if chat_id in tareas_tiempo and not tareas_tiempo[chat_id].done():
        tareas_tiempo[chat_id].cancel()

    bot = app_or_context.bot if hasattr(app_or_context, 'bot') else app_or_context

    async def _loop_tiempo():
        while True:
            await asyncio.sleep(MINUTOS_PARA_DROP * 60)
            await ejecutar_drop(bot, chat_id, motivo="Drop automático por tiempo de espera")
            if chat_id in contador_mensajes:
                contador_mensajes[chat_id] = 0

    tareas_tiempo[chat_id] = asyncio.create_task(_loop_tiempo())

# ==============================================================================
# 3. NAVEGACIÓN DE INVENTARIO Y MENÚS
# ==============================================================================

def generar_vista_inventario(user_id, user_name):
    """Genera la foto, el texto explicativo y los botones para navegar el inventario."""
    todas_las_cartas = inventarios.get(user_id, [])
    
    if not todas_las_cartas:
        return None, None, None

    estado = estado_inv_usuario.get(user_id, {"index": 0, "filtro": "TODAS"})
    filtro = estado["filtro"]

    # Filtrar cartas según selección
    if filtro == "TODAS":
        cartas_filtradas = todas_las_cartas
    else:
        cartas_filtradas = [c for c in todas_las_cartas if c["rareza"] == filtro]

    if not cartas_filtradas:
        # Si no hay cartas de esa rareza, resetea a TODAS
        cartas_filtradas = todas_las_cartas
        filtro = "TODAS"
        estado["filtro"] = "TODAS"

    # Consolidar cartas únicas y sus cantidades
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
        f"📦 **INVENTARIO INTERACTIVO DE @{user_name}**\n\n"
        f"🎴 **{carta_actual['nombre']}** (`{carta_actual['id']}`)\n"
        f"📊 Rareza: {info_rareza}\n"
        f"🔢 Tienes en posesión: **x{cantidad_copias}**\n"
        f"📑 Carta **{idx + 1}** de **{len(cartas_unicas)}** (Filtro: `{filtro}`)\n"
        f"✨ Total en tu colección: **{len(todas_las_cartas)}** cartas"
    )

    # Botones de navegación
    row_nav = [
        InlineKeyboardButton("◀", callback_data=f"inv_nav_{user_id}_prev"),
        InlineKeyboardButton(f"{idx + 1}/{len(cartas_unicas)}", callback_data="inv_noop"),
        InlineKeyboardButton("▶", callback_data=f"inv_nav_{user_id}_next"),
    ]

    # Botones de filtro de rareza
    row_filtros = [
        InlineKeyboardButton("TODAS", callback_data=f"inv_flt_{user_id}_TODAS"),
        InlineKeyboardButton("UR", callback_data=f"inv_flt_{user_id}_UR"),
        InlineKeyboardButton("SSS", callback_data=f"inv_flt_{user_id}_SSS"),
        InlineKeyboardButton("S", callback_data=f"inv_flt_{user_id}_S"),
        InlineKeyboardButton("A", callback_data=f"inv_flt_{user_id}_A"),
        InlineKeyboardButton("B", callback_data=f"inv_flt_{user_id}_B"),
    ]

    # Botón de compartir en el chat público
    row_share = [
        InlineKeyboardButton("📢 Compartir esta carta en el chat", callback_data=f"inv_share_{user_id}_{carta_actual['id']}")
    ]

    reply_markup = InlineKeyboardMarkup([row_nav, row_filtros, row_share])
    return carta_actual["foto"], caption, reply_markup

# ==============================================================================
# 4. COMANDOS Y MANEJADORES DE EVENTOS
# ==============================================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await auto_borrar_comando(update)
    chat_id = update.effective_chat.id
    reiniciar_temporizador_chat(context, chat_id)
    await update.message.reply_text(
        "✨ **¡Bienvenido al Sistema de Gacha de Cartas!** ✨\n\n"
        "Comandos disponibles:\n"
        "• `/drop` - Genera una carta en el grupo.\n"
        "• `/inventario` - Abre tu panel visual de cartas e inventario.\n\n"
        "Comandos de Administradora:\n"
        "• `/drop ID_carta` - Fuerza la aparición de una carta específica.\n"
        "• `/dar ID_carta` - (Respondiendo) Otorga una carta a un miembro.\n"
        "• `/quitar ID_carta` - (Respondiendo) Elimina una carta del inventario."
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
            msg = await context.bot.send_message(chat_id, f"❌ No existe ninguna carta con el ID `{carta_id}`.")
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

    # Borra la ventana de inventario previa enviada para mantener orden
    if user.id in ultimo_mensaje_inv:
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=ultimo_mensaje_inv[user.id])
        except Exception:
            pass

    user_cards = inventarios.get(user.id, [])
    if not user_cards:
        msg = await context.bot.send_message(
            chat_id,
            f"📦 **Inventario de @{nombre_usuario}**\n\n"
            "Tu colección está vacía actualmente. ¡Atrapa cartas presionando el botón de drop!"
        )
        ultimo_mensaje_inv[user.id] = msg.message_id
        return

    # Inicializar estado por defecto si no existe
    if user.id not in estado_inv_usuario:
        estado_inv_usuario[user.id] = {"index": 0, "filtro": "TODAS"}

    foto, caption, reply_markup = generar_vista_inventario(user.id, nombre_usuario)

    try:
        msg = await context.bot.send_photo(
            chat_id=chat_id,
            photo=foto,
            caption=caption,
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )
        ultimo_mensaje_inv[user.id] = msg.message_id
    except Exception as e:
        logging.error(f"Error al desplegar menú de inventario: {e}")

async def inventario_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    clicker_id = query.from_user.id

    if data == "inv_noop":
        await query.answer()
        return

    partes = data.split("_")
    accion = partes[1]       # nav, flt, o share
    target_user_id = int(partes[2])

    # Control de seguridad: solo el dueño puede interactuar
    if clicker_id != target_user_id:
        await query.answer("❌ Este no es tu inventario. Escribe /inventario para abrir el tuyo.", show_alert=True)
        return

    user_name = query.from_user.username or query.from_user.first_name

    if accion == "nav":
        direccion = partes[3]
        estado = estado_inv_usuario.get(clicker_id, {"index": 0, "filtro": "TODAS"})
        if direccion == "next":
            estado["index"] += 1
        elif direccion == "prev":
            estado["index"] -= 1
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
            await context.bot.send_photo(
                chat_id=query.message.chat_id,
                photo=carta["foto"],
                caption=f"✨ **@{user_name} MUESTRA SU CARTA:**\n\n"
                        f"🎴 **{carta['nombre']}** (`{carta['id']}`)\n"
                        f"📊 Rareza: {info_rareza}\n"
                        f"🔢 Copias acumuladas: **x{copias}**",
                parse_mode="Markdown"
            )
            await query.answer("📢 ¡Carta compartida con el grupo!")
        return

    # Actualiza la vista existente sin reenviar un mensaje nuevo
    foto, caption, reply_markup = generar_vista_inventario(clicker_id, user_name)
    if foto:
        try:
            from telegram import InputMediaPhoto
            await query.edit_message_media(
                media=InputMediaPhoto(media=foto, caption=caption, parse_mode="Markdown"),
                reply_markup=reply_markup
            )
        except Exception as e:
            logging.error(f"Error editando mensaje de inventario: {e}")
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

    info_rareza = RAREZAS[carta["rareza"]]["estrellas"]

    await query.answer(f"🎉 ¡Felicidades! Has reclamado a {carta['nombre']}")
    await query.edit_message_caption(
        caption=f"✅ **CARTA RECLAMADA**\n\n"
                f"🎴 **{carta['nombre']}** ({info_rareza})\n"
                f"👤 Dueño actual: @{user.username or user.first_name}",
        reply_markup=None
    )

async def dar_carta(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await auto_borrar_comando(update)
    user = update.effective_user
    chat_id = update.effective_chat.id

    if user.id != ADMIN_ID:
        return

    if not update.message.reply_to_message:
        msg = await context.bot.send_message(chat_id, "⚠️ **Modo de uso:** Responde al mensaje del usuario y escribe `/dar ID_CARTA`.")
        await asyncio.sleep(5)
        try: await msg.delete()
        except: pass
        return

    args = context.args
    if not args:
        msg = await context.bot.send_message(chat_id, "⚠️ Indica el ID de la carta. Ejemplo: `/dar c1`")
        await asyncio.sleep(5)
        try: await msg.delete()
        except: pass
        return

    carta_id = args[0]
    carta = next((c for c in CARTAS if c["id"] == carta_id), None)
    if not carta:
        msg = await context.bot.send_message(chat_id, f"❌ No existe ninguna carta con el ID `{carta_id}`.")
        await asyncio.sleep(5)
        try: await msg.delete()
        except: pass
        return

    target_user = update.message.reply_to_message.from_user

    if target_user.id not in inventarios:
        inventarios[target_user.id] = []

    inventarios[target_user.id].append(carta)
    info_rareza = RAREZAS[carta["rareza"]]["estrellas"]

    await context.bot.send_message(
        chat_id,
        f"🎁 **¡CARTA OTORGADA!**\n\n"
        f"Se ha añadido **{carta['nombre']}** ({info_rareza}) al inventario de @{target_user.username or target_user.first_name}."
    )

async def quitar_carta(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await auto_borrar_comando(update)
    user = update.effective_user
    chat_id = update.effective_chat.id

    if user.id != ADMIN_ID:
        return

    if not update.message.reply_to_message:
        msg = await context.bot.send_message(chat_id, "⚠️ **Modo de uso:** Responde al mensaje del usuario y escribe `/quitar ID_CARTA`.")
        await asyncio.sleep(5)
        try: await msg.delete()
        except: pass
        return

    args = context.args
    if not args:
        msg = await context.bot.send_message(chat_id, "⚠️ Indica el ID de la carta. Ejemplo: `/quitar c1`")
        await asyncio.sleep(5)
        try: await msg.delete()
        except: pass
        return

    carta_id = args[0]
    target_user = update.message.reply_to_message.from_user

    if target_user.id not in inventarios or not inventarios[target_user.id]:
        msg = await context.bot.send_message(chat_id, f"❌ @{target_user.username or target_user.first_name} no tiene cartas en su inventario.")
        await asyncio.sleep(5)
        try: await msg.delete()
        except: pass
        return

    user_cards = inventarios[target_user.id]
    carta_a_remover = next((c for c in user_cards if c["id"] == carta_id), None)

    if not carta_a_remover:
        msg = await context.bot.send_message(chat_id, f"❌ El usuario no posee la carta con ID `{carta_id}`.")
        await asyncio.sleep(5)
        try: await msg.delete()
        except: pass
        return

    user_cards.remove(carta_a_remover)
    await context.bot.send_message(
        chat_id,
        f"🗑️ Se ha removido la carta **{carta_a_remover['nombre']}** del inventario de @{target_user.username or target_user.first_name}."
    )

# ==============================================================================
# 5. INICIALIZACIÓN DEL BOT
# ==============================================================================
if __name__ == "__main__":
    TOKEN = os.environ.get("TELEGRAM_TOKEN")
    if not TOKEN:
        print("Error: Falta la variable de entorno TELEGRAM_TOKEN.")
    else:
        app = ApplicationBuilder().token(TOKEN).build()

        app.add_handler(CommandHandler("start", start))
        app.add_handler(CommandHandler("drop", drop))
        app.add_handler(CommandHandler("inventario", inventario))
        app.add_handler(CommandHandler("dar", dar_carta))
        app.add_handler(CommandHandler("quitar", quitar_carta))
        
        # Callbacks para reclamo de cartas y panel interactivo del inventario
        app.add_handler(CallbackQueryHandler(claim_callback, pattern="^claim_"))
        app.add_handler(CallbackQueryHandler(inventario_callback, pattern="^inv_"))

        # Manejador de contador de mensajes de grupo
        app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), manejar_mensajes_grupo))

        print("🤖 Bot listo con inventario visual e interactivo desplegado...")
        app.run_polling()
