from aiogram.fsm.state import State, StatesGroup


class TopicForm(StatesGroup):
    waiting_name = State()
    waiting_search_terms = State()
    waiting_manual_chat = State()  # ввод @username для ручного добавления


class KeywordForm(StatesGroup):
    waiting_keyword = State()


class GeoFilterForm(StatesGroup):
    waiting_add_word = State()  # ввод нового слова в фильтр
