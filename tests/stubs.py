"""Stand-ins for aiohttp and pyrogram so the whole app can be imported and tested offline."""
import sys
import types


def _install_aiohttp():
    web = types.ModuleType("aiohttp.web")

    class Resp:
        def __init__(self, body=None, status=200, headers=None, text=None, content_type=None, charset=None, data=None):
            self.status, self.headers = status, dict(headers or {})
            self.body, self.text, self.data = body, text, data
            self.content_type, self.cookies_set = content_type, []

        def set_cookie(self, *a, **k):
            self.cookies_set.append((a, k))

        def del_cookie(self, *a, **k):
            pass

    class StreamResponse(Resp):
        def __init__(self, status=200, headers=None):
            super().__init__(status=status, headers=headers)
            self.chunks = []
            self.eof = False

        async def prepare(self, request):
            return self

        async def write(self, chunk):
            self.chunks.append(chunk)

        async def write_eof(self):
            self.eof = True

    class HTTPException(Exception):
        def __init__(self, location=None, **kw):
            super().__init__(location)
            self.location = location

    web.Response, web.StreamResponse = Resp, StreamResponse
    web.json_response = lambda data, status=200, headers=None, **kw: Resp(data=data, status=status, headers=headers)
    web.HTTPException = HTTPException
    for n in ("HTTPNotFound", "HTTPFound", "HTTPMethodNotAllowed"):
        setattr(web, n, type(n, (HTTPException,), {}))
    web.middleware = lambda f: f
    web.Application = lambda **kw: types.SimpleNamespace(router=types.SimpleNamespace(**{
        m: (lambda *a, **k: None) for m in ("add_get", "add_post", "add_patch", "add_delete", "add_static", "add_route")}))
    mod = types.ModuleType("aiohttp")
    mod.web = web
    sys.modules["aiohttp"], sys.modules["aiohttp.web"] = mod, web


class _Any:
    """Absorbs any call, attribute or operator (used for pyrogram filters)."""
    def __call__(self, *a, **k):
        return _Any()

    def __getattr__(self, name):
        return _Any()

    __and__ = __or__ = __rand__ = __ror__ = lambda self, o: _Any()
    __invert__ = lambda self: _Any()


class _Button:
    def __init__(self, text, callback_data=None, url=None, **kw):
        self.text, self.callback_data, self.url = text, callback_data, url


class _Markup:
    def __init__(self, rows):
        self.inline_keyboard = rows


def _install_pyrogram():
    pg = types.ModuleType("pyrogram")

    def decorator(*a, **k):
        return lambda f: f

    class Client:
        on_message = staticmethod(decorator)
        on_callback_query = staticmethod(decorator)
        on_inline_query = staticmethod(decorator)
        on_chat_join_request = staticmethod(decorator)

        def __init__(self, *a, **k):
            pass

    types_mod = types.ModuleType("pyrogram.types")
    types_mod.InlineKeyboardButton, types_mod.InlineKeyboardMarkup = _Button, _Markup
    for n in ("ChatPermissions", "InlineQueryResultCachedDocument"):
        setattr(types_mod, n, _Any())
    enums = types.ModuleType("pyrogram.enums")
    enums.ChatType = types.SimpleNamespace(PRIVATE="PRIVATE", GROUP="GROUP", SUPERGROUP="SUPERGROUP", CHANNEL="CHANNEL")
    enums.ParseMode = types.SimpleNamespace(HTML="html")
    pg.Client, pg.filters, pg.enums, pg.types, pg.idle = Client, _Any(), enums, types_mod, None
    sys.modules.update({"pyrogram": pg, "pyrogram.types": types_mod, "pyrogram.enums": enums})


def install():
    if "aiohttp" not in sys.modules or not hasattr(sys.modules["aiohttp"], "web"):
        try:
            import aiohttp  # noqa: F401  (use the real one when it exists)
        except ImportError:
            _install_aiohttp()
    try:
        import pyrogram  # noqa: F401
    except ImportError:
        _install_pyrogram()
