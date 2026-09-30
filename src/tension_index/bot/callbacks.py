from aiogram.filters.callback_data import CallbackData


class LangCb(CallbackData, prefix="lang"):
    code: str


class CountryCb(CallbackData, prefix="cty"):
    code: str


class MenuCb(CallbackData, prefix="m"):
    action: str  # notify | country | lang | refresh | about | home
