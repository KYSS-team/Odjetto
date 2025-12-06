from aiogram.fsm.state import State, StatesGroup


class AuthStates(StatesGroup):
    waiting_for_password = State()


class ManagerStates(StatesGroup):
    add_employee_name = State()
    add_employee_office = State()

    emp_search = State()
    emp_action_select = State()
    emp_edit_name = State()
    emp_edit_office = State()

    add_rest_name = State()
    rest_action_select = State()
    rest_delete_confirm = State()
    dish_name = State()
    dish_desc = State()
    dish_price = State()
    dish_id_to_delete = State()

    change_limit = State()


class OrderStates(StatesGroup):
    choose_date = State()
    choose_rest = State()
    choose_dish = State()
