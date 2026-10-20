"""Message templates (small caps style). {placeholders} are filled with str.format."""
from utils import sc

WELCOME = (
    "✨ <b>" + sc("welcome") + "</b> {mention} ✨\n\n"
    "<blockquote>" + sc("i can find any movie, series or file in seconds. just send me the name.") + "</blockquote>\n\n"
    "⚡ " + sc("lightning fast search") + "\n"
    "🎬 " + sc("watch online, no waiting") + "\n"
    "📥 " + sc("direct download links") + "\n"
    "🌐 " + sc("full website with shorts and videos") + "\n\n"
    "👇 " + sc("tap a button below or type a name to begin")
)
HELP = (
    "📖 <b>" + sc("how to use me") + "</b>\n\n"
    "1️⃣ " + sc("send a movie or series name") + "\n"
    "2️⃣ " + sc("use filters: quality, language, year, season") + "\n"
    "3️⃣ " + sc("tap a file to get it, or send all") + "\n\n"
    "<b>" + sc("commands") + "</b>\n"
    "• /plan — " + sc("premium plans") + "\n"
    "• /myplan — " + sc("your plan") + "\n"
    "• /refer — " + sc("invite and earn premium") + "\n"
    "• /request name — " + sc("ask for a missing file")
)
ABOUT = (
    "ℹ️ <b>" + sc("about") + "</b>\n\n"
    "<blockquote>" + sc("auto filter bot with a streaming website") + "</blockquote>\n\n"
    "🌐 " + sc("website") + ": {site}"
)
NEW_USER_LOG = "#NewUser\n\nID: <code>{id}</code>\nName: {mention}"
NEW_GROUP_LOG = "#NewGroup\n\nTitle: {title}\nID: <code>{id}</code>\nMembers: {count}\nAdded by: {by}"
RESTART_LOG = "♻️ Bot restarted.\n{extra}"
OFFLINE_LOG = "⚠️ Bot was offline for about {minutes} minutes."
NO_RESULT = "😕 <b>" + sc("nothing found for") + "</b> <code>{query}</code>\n\n" + sc("check the spelling or send a request.")
DID_YOU_MEAN = sc("did you mean one of these?")
SEARCH_EXPIRED = "This search expired. Please search again."
NOT_YOURS = "This is not your search. Send your own search."
RESULTS_HEADER = "🔎 <b>{total}</b> " + sc("files found for") + " <b>{query}</b>"
JOIN_FIRST = "🔒 <b>" + sc("join our channel to continue") + "</b>\n\n" + sc("tap the button below, join, then press try again.")
JOIN_REQ_SENT = sc("send the join request, then press try again.")
VERIFY_NEEDED = ("🛡 <b>" + sc("quick verification") + "</b>\n\n" + sc("verify once a day to unlock all files.") + "\n"
                 + sc("tap verify, finish the short step and come back.") + "\n\n💎 " + sc("premium users skip this."))
VERIFY_OK = "✅ <b>" + sc("verified for today!") + "</b> " + sc("enjoy your files.")
VERIFY_BAD = "❌ This verification link is invalid or expired."
SHORT_NEEDED = "🔗 <b>" + sc("your file is ready") + "</b>\n\n" + sc("tap get file to unlock it.") + "\n💎 " + sc("premium users skip this.")
BANNED = "You are banned. Reason: {reason}"
PLAN = "💎 <b>" + sc("premium plans") + "</b>\n\n{text}\n\n" + sc("after paying, send the screenshot to the owner.")
MYPLAN_NONE = "💎 " + sc("you have no active premium plan.")
MYPLAN_ON = "💎 " + sc("premium active.") + " ⏳ <b>{left}</b> " + sc("left")
REFERRAL_INFO = ("Invite friends with your link:\n<code>{link}</code>\n\nEvery {count} new users who join through it "
                 "give you {reward} of premium.\nYour progress: {have}/{count}")
REFERRAL_DONE = "🎉 <b>" + sc("referral reward!") + "</b> " + sc("you got") + " {reward} " + sc("of premium.")
REQUEST_SENT = "✅ Your request was sent."
REQUEST_CARD = "#Request\n\nUser: {mention} (<code>{uid}</code>)\nChat: {chat}\nRequest: <b>{text}</b>"
INDEX_ASK = "Send the link of the last message of the channel, or forward that message here."
INDEX_DONE = ("✅ Index finished\n\nTotal: <code>{total}</code>\nSaved: <code>{saved}</code>\n"
              "Duplicates: <code>{dupes}</code>\nUnsupported: <code>{skipped}</code>\nErrors: <code>{errors}</code>")
INDEX_PROGRESS = ("Indexing…\n\nTotal: <code>{total}</code>\nSaved: <code>{saved}</code>\n"
                  "Duplicates: <code>{dupes}</code>\nUnsupported: <code>{skipped}</code>\nErrors: <code>{errors}</code>")
ENRICH_PROGRESS = "Enriching videos… done {done}/{total}, failed {failed}"
STATS = ("<b>Stats</b>\n\nFiles: {files}\nVideos: {videos} (shorts {shorts}, long {longs})\nUsers: {users}\n"
         "Groups: {groups}\nPremium: {premium}\nBanned: {banned}\nViews: {views}\nActive streams: {streams}")
SETTINGS_TITLE = "Settings for <b>{title}</b>"
WELCOME_GROUP = "👋 " + sc("welcome") + " {mention} " + sc("to") + " <b>{title}</b>!"
FILE_NOT_FOUND = "⚠️ " + sc("file not found. it may have been removed.")
STREAM_BTN = "▶️ " + sc("stream / download")
