"""Message templates."""

WELCOME = ("👋 Hello {mention}!\n\nI am a file search bot. Send me a name in this chat or in a group "
           "and I will find the files for you.")
HELP = ("<b>Help</b>\n\n• Send a name to search.\n• Use the buttons to filter by quality, language, season, year.\n"
        "• /plan - premium plans\n• /myplan - your plan\n• /request name - ask for a missing file")
ABOUT = "<b>About</b>\n\nAuto filter bot with a streaming website.\nSite: {site}"
NEW_USER_LOG = "#NewUser\n\nID: <code>{id}</code>\nName: {mention}"
NEW_GROUP_LOG = "#NewGroup\n\nTitle: {title}\nID: <code>{id}</code>\nMembers: {count}\nAdded by: {by}"
RESTART_LOG = "♻️ Bot restarted.\n{extra}"
OFFLINE_LOG = "⚠️ Bot was offline for about {minutes} minutes."
NO_RESULT = "❌ I could not find <b>{query}</b>. Check the spelling or send a request."
DID_YOU_MEAN = "Did you mean one of these?"
SEARCH_EXPIRED = "This search expired. Please search again."
NOT_YOURS = "This is not your search. Send your own search."
RESULTS_HEADER = "Found <b>{total}</b> files for <b>{query}</b>"
JOIN_FIRST = "To use this bot you must join our channel first."
JOIN_REQ_SENT = "Send the join request, then press Try Again."
VERIFY_NEEDED = ("You need to verify once a day to get files.\n\nTap the button, finish the short step, "
                 "and come back. Premium users skip this.")
VERIFY_OK = "✅ Verified for today. You can now get files."
VERIFY_BAD = "❌ This verification link is invalid or expired."
SHORT_NEEDED = "Tap the button to unlock your file. Premium users skip this."
BANNED = "You are banned. Reason: {reason}"
PLAN = "<b>Premium plans</b>\n\n{text}\n\nAfter paying, send the screenshot to the owner."
MYPLAN_NONE = "You have no active premium plan."
MYPLAN_ON = "Premium active. Time left: <b>{left}</b>"
REFERRAL_INFO = ("Invite friends with your link:\n<code>{link}</code>\n\nEvery {count} new users who join through it "
                 "give you {reward} of premium.\nYour progress: {have}/{count}")
REFERRAL_DONE = "🎉 Referral reward! You got {reward} of premium."
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
WELCOME_GROUP = "Welcome {mention} to <b>{title}</b>!"
FILE_NOT_FOUND = "File not found. It may have been removed."
STREAM_BTN = "▶️ Stream / Download"
