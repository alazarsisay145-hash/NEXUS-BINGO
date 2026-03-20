        self,
        distilled_parameters,
        execution_options or NO_OPTIONS,
    )
  File "/opt/render/project/src/.venv/lib/python3.14/site-packages/sqlalchemy/sql/elements.py", line 527, in _execute_on_connection
    return connection._execute_clauseelement(
Menu
           ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~^
        self, distilled_params, execution_options
        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    )
    ^
  File "/opt/render/project/src/.venv/lib/python3.14/site-packages/sqlalchemy/engine/base.py", line 1641, in _execute_clauseelement
    ret = self._execute_context(
        dialect,
    ...<8 lines>...
        cache_hit=cache_hit,
    )
  File "/opt/render/project/src/.venv/lib/python3.14/site-packages/sqlalchemy/engine/base.py", line 1846, in _execute_context
    return self._exec_single_context(
           ~~~~~~~~~~~~~~~~~~~~~~~~~^
        dialect, context, statement, parameters
        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    )
    ^
  File "/opt/render/project/src/.venv/lib/python3.14/site-packages/sqlalchemy/engine/base.py", line 1986, in _exec_single_context
    self._handle_dbapi_exception(
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~^
        e, str_statement, effective_parameters, cursor, context
        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    )
    ^
  File "/opt/render/project/src/.venv/lib/python3.14/site-packages/sqlalchemy/engine/base.py", line 2363, in _handle_dbapi_exception
    raise sqlalchemy_exception.with_traceback(exc_info[2]) from e
  File "/opt/render/project/src/.venv/lib/python3.14/site-packages/sqlalchemy/engine/base.py", line 1967, in _exec_single_context
    self.dialect.do_execute(
    ~~~~~~~~~~~~~~~~~~~~~~~^
        cursor, str_statement, effective_parameters, context
        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    )
    ^
  File "/opt/render/project/src/.venv/lib/python3.14/site-packages/sqlalchemy/engine/default.py", line 952, in do_execute
    cursor.execute(statement, parameters)
    ~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^
sqlalchemy.exc.OperationalError: (sqlite3.OperationalError) no such table: users
[SQL: SELECT users.id AS users_id, users.telegram_id AS users_telegram_id, users.username AS users_username, users.first_name AS users_first_name, users.last_name AS users_last_name, users.phone_number AS users_phone_number, users.balance AS users_balance, users.is_approved AS users_is_approved, users.is_banned AS users_is_banned, users.is_bot AS users_is_bot, users.registration_step AS users_registration_step, users.created_at AS users_created_at, users.last_active AS users_last_active, users.welcome_bonus_claimed AS users_welcome_bonus_claimed, users.total_games_played AS users_total_games_played, users.total_games_won AS users_total_games_won, users.total_deposited AS users_total_deposited, users.total_withdrawn AS users_total_withdrawn 
FROM users 
WHERE users.telegram_id = ?
 LIMIT ? OFFSET ?]
[parameters: (999999999, 1, 0)]
(Background on this error at: https://sqlalche.me/e/20/e3q8)
127.0.0.1 - - [20/Mar/2026:15:49:27 +0000] "POST /api/player/auth HTTP/1.1" 500 265 "https://nexus-bingo.onrender.com/" "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36"
