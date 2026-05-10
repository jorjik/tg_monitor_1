from aiogram.fsm.state import State, StatesGroup


class TopicForm(StatesGroup):
    waiting_name = State()
    waiting_search_terms = State()
    waiting_manual_chat = State()  # ввод @username для ручного добавления
    waiting_manual_chat_file = State()


class KeywordForm(StatesGroup):
    waiting_keyword = State()
    waiting_confirm_keywords = State()


class GeoFilterForm(StatesGroup):
    waiting_add_word = State()  # ввод нового слова в фильтр


class HistoryForm(StatesGroup):
    waiting_interval = State()


class BillingAdminForm(StatesGroup):
    waiting_name = State()
    waiting_stars = State()
    waiting_days = State()
    waiting_trial_days = State()


class AdminUserForm(StatesGroup):
    waiting_search = State()
    waiting_custom_days = State()
