"""Python 3.10+ | GitHub -> Bot-Hosting
Install: pip install -r requirements.txt
Start: python main.py
Set BOT_TOKEN in hosting environment (never commit the token).
Optional: DATA_FILE=/persistent/path/bot_data.json
Runtime creates bot_data.json automatically; preserve it across deployments.
Admin: @kuzey_marketing. In target group send /hedef to bind its actual chat ID.
"""
import asyncio
import copy
import json
import logging
import os
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import urlparse

from telegram import InlineKeyboardButton as B, InlineKeyboardMarkup as K, Update
from telegram.error import TelegramError, BadRequest
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, MessageHandler, filters

ADMIN = 'kuzey_marketing'
DATA_FILE = Path(os.environ.get('DATA_FILE', 'bot_data.json'))
DEFAULT = dict(sites=[], posts=[], target='@fikoreis', hours=4.0, enabled=False,
               mode='cycle', cursor=0, next_at=0, sent=0, last_at=0, error='', serial=0)
db = copy.deepcopy(DEFAULT)
guard = asyncio.Lock()
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')
logging.getLogger('httpx').setLevel(logging.WARNING)


def save():
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = DATA_FILE.with_suffix('.tmp')
    with tmp.open('w', encoding='utf-8') as f:
        json.dump(db, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, DATA_FILE)


def load():
    if DATA_FILE.exists():
        with DATA_FILE.open(encoding='utf-8') as f:
            db.update(json.load(f))


def ident():
    db['serial'] += 1
    return db['serial']


def admin(update):
    u = update.effective_user
    return bool(u and (u.username or '').lower() == ADMIN)


def private_admin(update):
    return admin(update) and update.effective_chat.type == 'private'


def keyboard(rows):
    return K([[B(label, callback_data=data) for label, data in row] for row in rows])


def url(value):
    p = urlparse(value.strip())
    if p.scheme not in ('https', 'http') or not p.hostname or p.username or p.password:
        raise ValueError('Geçerli bir https:// veya http:// bağlantısı yaz.')
    return value.strip()


def stamp(value):
    if not value:
        return '—'
    return datetime.fromtimestamp(value, timezone(timedelta(hours=3))).strftime('%d.%m %H:%M')


async def panel(update, text, rows):
    if update.callback_query:
        try:
            await update.callback_query.edit_message_text(text, reply_markup=keyboard(rows))
        except BadRequest as e:
            if 'Message is not modified' not in str(e):
                raise
    else:
        await update.effective_message.reply_text(text, reply_markup=keyboard(rows))


async def home(update, context):
    context.user_data.clear()
    if not private_admin(update):
        return await sites_public(update, context)
    await panel(update,
        '━━━ KUZEY • KONTROL MERKEZİ ━━━\n\n'
        '📝 İçerik stüdyosu  ·  🌐 Site vitrini\n'
        '⏱ Planlı yayın  ·  📣 Telegram dağıtımı\n\n'
        f"Post: {len(db['posts'])}   |   Site: {len(db['sites'])}\n"
        f"Otomatik yayın: {'🟢 Açık' if db['enabled'] else '⚪ Kapalı'}\n"
        f"Hedef: {db['target']}\n\nBir bölüm seç:",
        [[('📝 Post stüdyosu', 'posts:0'), ('🌐 Site yönetimi', 'sites:0')],
         [('⏱ Otomatik yayın', 'auto'), ('📣 Yayın hedefi', 'target')],
         [('📊 Yayın raporu', 'status'), ('👁 Site vitrinini gör', 'public:0')],
         [('❔ Kullanım rehberi', 'help')]])


async def sites_public(update, context, page=0):
    items = db['sites']
    page = max(0, min(page, max(0, (len(items)-1)//10)))
    rows = [[B('🌐 ' + s['name'], url=s['url'])] for s in items[page*10:page*10+10]]
    nav = []
    if page:
        nav.append(B('‹ Önceki', callback_data=f'public:{page-1}'))
    if (page+1)*10 < len(items):
        nav.append(B('Sonraki ›', callback_data=f'public:{page+1}'))
    if nav:
        rows.append(nav)
    if private_admin(update):
        rows.append([B('⚙️ Kontrol merkezi', callback_data='home')])
    text = ('━━━ KUZEY • SİTE VİTRİNİ ━━━\n\n'
            '🔗 Güncel bağlantılarımıza aşağıdan ulaşabilirsin.\n'
            'Gitmek istediğin siteyi seç 👇' if items else
            '🌐 Site vitrini hazırlanıyor. Bağlantılar yakında burada!')
    if update.callback_query:
        try:
            await update.callback_query.edit_message_text(text, reply_markup=K(rows))
        except BadRequest as e:
            if 'Message is not modified' not in str(e):
                raise
    else:
        await update.effective_message.reply_text(text, reply_markup=K(rows))


async def listing(update, kind, page=0):
    items = db[kind]
    page = max(0, min(page, max(0, (len(items)-1)//8)))
    rows = [[('➕ Yeni post' if kind == 'posts' else '➕ Site ekle', f'new:{kind}')]]
    for i, item in enumerate(items[page*8:page*8+8], page*8+1):
        name = item.get('name') or item['text'][:35] or 'Görselli post'
        mark = '🟢 ' if kind == 'posts' and item['active'] else ''
        rows.append([(f'{i}. {mark}{name}', f'item:{kind}:{item["id"]}')])
    nav = []
    if page:
        nav.append(('‹ Önceki', f'{kind}:{page-1}'))
    if (page+1)*8 < len(items):
        nav.append(('Sonraki ›', f'{kind}:{page+1}'))
    if nav:
        rows.append(nav)
    rows.append([('⌂ Kontrol merkezi', 'home')])
    await panel(update, f"{'📝 POST STÜDYOSU' if kind == 'posts' else '🌐 SİTE YÖNETİMİ'}\n\n"
                f'Toplam {len(items)} kayıt · Sayfa {page+1}\nBir kayıt seç veya yenisini ekle.', rows)


def find(kind, sid):
    return next((x for x in db[kind] if x['id'] == int(sid)), None)


async def detail(update, kind, item):
    sid = item['id']
    if kind == 'sites':
        text = f"🌐 {item['name']}\n\n{item['url']}\n\nButon sırasını oklarla değiştirebilirsin."
        rows = [[('⬆️ Yukarı', f'move:{sid}:-1'), ('⬇️ Aşağı', f'move:{sid}:1')]]
    else:
        text = (f"📝 POST #{sid}\n\n{item['text'][:400]}\n\n"
                f"Görsel: {'Var' if item['photo'] else 'Yok'} · Buton: {len(item['buttons'])}\n"
                f"Otomatik sıra: {'Dahil' if item['active'] else 'Hariç'}")
        rows = [[('👁 Önizle', f'preview:{sid}'), ('📤 Yayınla', f'ask_send:{sid}')],
                [('🔄 Otomatik sıraya al / çıkar', f'toggle:{sid}')]]
    rows += [[('✏️ Düzenle', f'edit:{kind}:{sid}'), ('🗑 Sil', f'ask_delete:{kind}:{sid}')],
             [('‹ Liste', f'{kind}:0'), ('⌂ Ana menü', 'home')]]
    await panel(update, text, rows)


async def deliver(bot, chat, post):
    markup = K([[B(b['name'], url=b['url'])] for b in post['buttons']]) if post['buttons'] else None
    if post['photo']:
        await bot.send_photo(chat_id=chat, photo=post['photo'], caption=post['text'] or None, reply_markup=markup)
    else:
        await bot.send_message(chat_id=chat, text=post['text'], reply_markup=markup)


async def publish(bot, post):
    await deliver(bot, db['target'], post)
    db['sent'] += 1
    db['last_at'] = time.time()
    db['error'] = ''
    save()


async def automatic(context):
    async with guard:
        if not db['enabled'] or time.time() < db['next_at']:
            return
        items = [p for p in db['posts'] if p['active']]
        if not items:
            db['enabled'] = False
            db['error'] = 'Otomatik sıra boş olduğu için yayın durdu.'
            save()
            return
        index = db['cursor'] % len(items) if db['mode'] == 'cycle' else 0
        try:
            await publish(context.bot, items[index])
        except TelegramError as e:
            db['error'] = f'Yayın başarısız: {type(e).__name__}. Hedefi ve bot yetkilerini kontrol et.'
            # Avoid repeatedly attempting a broken target every few seconds.
            db['next_at'] = time.time() + 300
        else:
            db['cursor'] = (index + 1) % len(items)
            db['next_at'] = time.time() + db['hours'] * 3600
        save()


async def auto_panel(update):
    await panel(update, '⏱ OTOMATİK YAYIN\n\n'
                f"Durum: {'🟢 Açık' if db['enabled'] else '⚪ Kapalı'}\n"
                f"Aralık: {db['hours']:g} saat\n"
                f"Mod: {'Sırayla paylaş' if db['mode'] == 'cycle' else 'İlk aktif postu tekrarla'}\n"
                f"Aktif post: {sum(p['active'] for p in db['posts'])}\n"
                f"Sonraki: {stamp(db['next_at']) if db['enabled'] else '—'} (Türkiye)\n\n"
                'Başlatınca ilk yayın seçtiğin süre sonunda yapılır.',
                [[(f'{h} saat', f'hours:{h}') for h in (1, 2, 4)],
                 [(f'{h} saat', f'hours:{h}') for h in (6, 12, 24)],
                 [('✍️ Özel süre', 'custom_hours')],
                 [('🔁 Sırayla', 'mode:cycle'), ('🔂 İlk aktif post', 'mode:repeat')],
                 [('▶️ Başlat', 'enable'), ('⏸ Durdur', 'disable')],
                 [('⌂ Kontrol merkezi', 'home')]])


async def prompt(update, context, state, text):
    context.user_data['state'] = state
    await panel(update, text, [[('✖️ İptal / Ana menü', 'home')]])


async def start_draft(update, context, kind, item=None):
    context.user_data.clear()
    context.user_data['editing'] = item['id'] if item else None
    context.user_data['draft'] = copy.deepcopy(item) if item else {}
    if kind == 'sites':
        await prompt(update, context, 'site_name', '🌐 SİTE EDİTÖRÜ · 1/2\n\nButon üzerinde görünecek site adını yaz (en fazla 50 karakter).')
    else:
        await prompt(update, context, 'post_photo', '📝 POST EDİTÖRÜ · 1/3\n\nBir fotoğraf gönder. Görselsiz post için - yaz.\nDüzenlerken mevcut görseli korumak için = yaz.')


async def callback(update, context):
    q = update.callback_query
    action = q.data.split(':')
    if action[0] == 'public':
        await q.answer()
        return await sites_public(update, context, int(action[1]))
    if not private_admin(update):
        return await q.answer('Bu panel yalnızca yöneticinin özel sohbetinde açılır.', show_alert=True)
    await q.answer()
    op = action[0]
    if op == 'home':
        return await home(update, context)
    if op in ('posts', 'sites'):
        context.user_data.clear()
        return await listing(update, op, int(action[1]))
    if op in ('new', 'edit'):
        item = find(action[1], action[2]) if op == 'edit' else None
        if op == 'edit' and not item:
            return await listing(update, action[1])
        return await start_draft(update, context, action[1], item)
    if op in ('item', 'ask_delete', 'delete'):
        kind, sid = action[1:3]
        item = find(kind, sid)
        if not item:
            return await listing(update, kind)
        if op == 'item':
            return await detail(update, kind, item)
        if op == 'ask_delete':
            return await panel(update, '🗑 Bu kayıt kalıcı olarak silinsin mi?',
                               [[('Evet, sil', f'delete:{kind}:{sid}'), ('Vazgeç', f'item:{kind}:{sid}')]])
        db[kind].remove(item)
        save()
        return await listing(update, kind)
    if op == 'move':
        item = find('sites', action[1])
        if not item:
            return await listing(update, 'sites')
        i = db['sites'].index(item)
        j = max(0, min(len(db['sites'])-1, i+int(action[2])))
        db['sites'][i], db['sites'][j] = db['sites'][j], db['sites'][i]
        save()
        return await detail(update, 'sites', item)
    if op in ('preview', 'toggle', 'ask_send', 'send'):
        item = find('posts', action[1])
        if not item:
            return await listing(update, 'posts')
        if op == 'preview':
            await deliver(context.bot, update.effective_chat.id, item)
        elif op == 'toggle':
            item['active'] = not item['active']
            save()
        elif op == 'ask_send':
            return await panel(update, f"📤 Post #{item['id']} şu hedefe yayınlansın mı?\n{db['target']}",
                               [[('📤 Yayınla', f'send:{item["id"]}'), ('Vazgeç', f'item:posts:{item["id"]}')]])
        else:
            async with guard:
                await publish(context.bot, item)
            await panel(update, '✅ Post hedefe paylaşıldı.', [[('‹ Posta dön', f'item:posts:{item["id"]}')]])
            return
        return await detail(update, 'posts', item)
    if op == 'auto':
        context.user_data.clear()
        return await auto_panel(update)
    if op == 'hours':
        db['hours'] = float(action[1])
        if db['enabled']:
            db['next_at'] = time.time() + db['hours']*3600
        save()
        return await auto_panel(update)
    if op == 'custom_hours':
        return await prompt(update, context, 'hours', '⏱ Kaç saatte bir?\n0.25 ile 720 arasında yaz. Örnek: 1.5 = 90 dakika.')
    if op == 'mode':
        db['mode'] = action[1]
        db['cursor'] = 0
        save()
        return await auto_panel(update)
    if op in ('enable', 'disable'):
        if op == 'enable' and not any(p['active'] for p in db['posts']):
            return await panel(update, 'Önce otomatik sıraya dahil bir post oluştur.', [[('📝 Postlar', 'posts:0'), ('‹ Geri', 'auto')]])
        db['enabled'] = op == 'enable'
        db['next_at'] = time.time() + db['hours']*3600 if db['enabled'] else 0
        save()
        return await auto_panel(update)
    if op == 'target':
        return await prompt(update, context, 'target', f"📣 YAYIN HEDEFİ\n\nMevcut: {db['target']}\n\n@kanaladi veya -100 ile başlayan sohbet ID'si yaz.\nGrup için botu ekleyip grubun içinde /hedef yazman da yeterli.")
    if op == 'status':
        return await panel(update, f"📊 YAYIN RAPORU\n\nBaşarılı yayın: {db['sent']}\nSon yayın: {stamp(db['last_at'])}\n"
                           f"Sonraki: {stamp(db['next_at']) if db['enabled'] else '—'}\nSaatler: Türkiye\n"
                           f"Son hata: {db['error'] or 'Yok'}", [[('🔄 Yenile', 'status'), ('⌂ Ana menü', 'home')]])
    if op == 'help':
        return await panel(update, '❔ KULLANIM REHBERİ\n\n'
                           '1. Gruba botu ekle ve /hedef yaz. Kanallar için hedefi panelden gir.\n'
                           '2. Post stüdyosunda görsel, metin ve butonlarını ekle.\n'
                           '3. Önizle, hemen yayınla veya otomatik sıraya dahil et.\n'
                           '4. Otomatik yayında aralığı seç ve Başlat’a bas.\n'
                           '5. Site yönetiminden bağlantıları ve sıralarını düzenle.\n\n'
                           '/site veya !site → Site vitrini\n/start → Ana menü\n/iptal → İşlemi bırak\n\n'
                           'Bot kapalıyken yayın yapılamaz. Yeniden açıldığında gecikmiş yayın bir kez gönderilir.\n'
                           'Düzenleme ekranı mevcut içeriği yeniden oluşturur; kaydedene kadar eski kayıt korunur.',
                           [[('⌂ Kontrol merkezi', 'home')]])
    if op == 'draft_save':
        draft = context.user_data.get('draft')
        if context.user_data.get('state') != 'post_review' or not draft:
            return await home(update, context)
        old = find('posts', context.user_data['editing']) if context.user_data.get('editing') else None
        if old:
            old.update(draft)
            item = old
        else:
            item = dict(draft, id=ident(), active=True)
            db['posts'].append(item)
        save()
        context.user_data.clear()
        return await detail(update, 'posts', item)
    if op == 'draft_preview':
        if context.user_data.get('state') == 'post_review':
            await deliver(context.bot, update.effective_chat.id, context.user_data['draft'])


async def text_input(update, context):
    msg = update.effective_message
    if (msg.text or '').strip().lower() == '!site':
        return await sites_public(update, context)
    if not private_admin(update):
        return
    state = context.user_data.get('state')
    text = (msg.text or '').strip()
    draft = context.user_data.setdefault('draft', {})
    try:
        if state == 'site_name':
            if not 1 <= len(text) <= 50:
                raise ValueError('Site adı 1–50 karakter olmalı.')
            draft['name'] = text
            return await prompt(update, context, 'site_url', '🌐 SİTE EDİTÖRÜ · 2/2\n\nSite bağlantısını https:// ile birlikte yaz.')
        if state == 'site_url':
            draft['url'] = url(text)
            old = find('sites', context.user_data['editing']) if context.user_data.get('editing') else None
            if old:
                old.update(draft)
                item = old
            else:
                item = dict(draft, id=ident())
                db['sites'].append(item)
            save()
            context.user_data.clear()
            return await detail(update, 'sites', item)
        if state == 'post_photo':
            if msg.photo:
                draft['photo'] = msg.photo[-1].file_id
            elif text == '-':
                draft['photo'] = None
            elif text == '=' and 'photo' in draft:
                pass
            else:
                raise ValueError('Fotoğraf gönder, görselsiz için - veya mevcut görsel için = yaz.')
            return await prompt(update, context, 'post_text', '📝 POST EDİTÖRÜ · 2/3\n\nPost metnini yaz.\nGörselli postta en fazla 1024, metin postunda 4096 karakter.\nGörselli postta metinsiz devam için - yaz.')
        if state == 'post_text':
            if not msg.text:
                raise ValueError('Metin mesajı gönder.')
            value = '' if text == '-' and draft.get('photo') else text
            limit = 1024 if draft.get('photo') else 4096
            if len(value) > limit or (not value and not draft.get('photo')):
                raise ValueError(f'Metin 1–{limit} karakter olmalı.')
            draft['text'] = value
            return await prompt(update, context, 'post_buttons', '📝 POST EDİTÖRÜ · 3/3\n\nHer satıra bir buton yaz (en fazla 12):\n\nSiteye Git | https://ornek.com\nİletişim | https://t.me/kuzey_marketing\n\nButonsuz devam için - yaz.')
        if state == 'post_buttons':
            buttons = []
            if text != '-':
                lines = text.splitlines()
                if not 1 <= len(lines) <= 12:
                    raise ValueError('En fazla 12 buton ekleyebilirsin.')
                for line in lines:
                    if '|' not in line:
                        raise ValueError('Her satır: Buton Adı | https://baglanti.com')
                    name, link = line.split('|', 1)
                    if not 1 <= len(name.strip()) <= 50:
                        raise ValueError('Buton adı 1–50 karakter olmalı.')
                    buttons.append(dict(name=name.strip(), url=url(link)))
            draft['buttons'] = buttons
            context.user_data['state'] = 'post_review'
            return await panel(update, '✅ POST TASLAĞI HAZIR\n\nÖnizlemeyi kontrol et, ardından kaydet. Kaydetmek postu gruba göndermez.',
                               [[('👁 Önizle', 'draft_preview'), ('💾 Kaydet', 'draft_save')], [('✖️ Vazgeç', 'home')]])
        if state == 'hours':
            hours = float(text.replace(',', '.'))
            if not 0.25 <= hours <= 720:
                raise ValueError('0.25 ile 720 arasında bir sayı yaz.')
            db['hours'] = hours
            if db['enabled']:
                db['next_at'] = time.time() + hours*3600
            save()
            context.user_data.clear()
            return await auto_panel(update)
        if state == 'target':
            if text.startswith('@') and text[1:].isascii() and text[1:].replace('_', '').isalnum():
                target = text
            elif text.startswith('-100') and text[1:].isdigit():
                target = int(text)
            else:
                raise ValueError('@kanaladi veya -100 ile başlayan sohbet ID’si yaz.')
            chat = await context.bot.get_chat(target)
            if chat.type not in ('group', 'supergroup', 'channel'):
                raise ValueError('Hedef bir grup veya kanal olmalı.')
            db['target'] = chat.id
            save()
            context.user_data.clear()
            return await panel(update, f'✅ Hedef kaydedildi: {chat.title}', [[('⌂ Ana menü', 'home')]])
        await msg.reply_text('Menüden işlem seçmek için /start yaz. İşlemi iptal etmek için /iptal.')
    except (ValueError, TelegramError) as e:
        message = str(e) if isinstance(e, ValueError) else 'Hedefe erişilemedi. Botun üyeliğini ve hedef adresini kontrol et.'
        await msg.reply_text('⚠️ ' + message)


async def bind_target(update, context):
    if not admin(update):
        return
    if update.effective_chat.type not in ('group', 'supergroup'):
        return await update.effective_message.reply_text('Bu komutu yayın yapılacak grubun içinde yaz. Kanal için özel mesajdaki Yayın hedefi menüsünü kullan.')
    db['target'] = update.effective_chat.id
    save()
    await update.effective_message.reply_text('✅ Bu grup yayın hedefi olarak kaydedildi. Postları botun özel mesajındaki panelden yönetebilirsin.')


async def on_error(update, context):
    logging.getLogger(__name__).error('İşlem başarısız (%s)', type(context.error).__name__)
    if update and update.effective_message:
        try:
            await update.effective_message.reply_text('⚠️ İşlem tamamlanamadı. Botun hedefe erişimini ve mesaj gönderme yetkisini kontrol et; ardından tekrar dene.')
        except TelegramError:
            pass


async def setup(app):
    await app.bot.delete_webhook(drop_pending_updates=False)
    await app.bot.set_my_commands([('start', 'Ana menü'), ('site', 'Site vitrini'), ('iptal', 'İşlemi iptal et')])
    app.job_queue.run_repeating(automatic, interval=15, first=3, name='automatic-publisher')


def main():
    token = "9083299031:AAHdYrltN0wWXs8Eo0S4uDAYwmaKcpPapws"
    if not token:
        raise SystemExit('BOT_TOKEN eksik. Hosting ortam değişkenlerine BotFather tokenini ekle.')
    load()  # Invalid database stops startup instead of silently losing records.
    app = Application.builder().token(token).concurrent_updates(False).post_init(setup).build()
    app.add_handler(CommandHandler(['start', 'iptal'], home))
    app.add_handler(CommandHandler('site', sites_public))
    app.add_handler(CommandHandler('hedef', bind_target))
    app.add_handler(CallbackQueryHandler(callback))
    app.add_handler(MessageHandler((filters.TEXT | filters.PHOTO) & ~filters.COMMAND, text_input))
    app.add_error_handler(on_error)
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    main()

