# Токены языка Funny.
# Формат строки:  <вид> <ИМЯ> = <регулярное выражение>     вид: token | skip | error
# Порядок строк = приоритет: при совпадении одинаковой длины побеждает верхнее правило.

# --- распознаётся и выбрасывается ------------------------------------------
skip  WS        = [ \t\r\n]+
skip  COMMENT   = //[^\r\n]*

# --- ключевые слова: стоят ВЫШЕ IDENT, иначе IDENT их заслонит --------------
token FUNCTION  = function
token RETURNS   = returns
token REQUIRES  = requires
token ENSURES   = ensures
token USES      = uses
token IF        = if
token ELSE      = else
token WHILE     = while
token INVARIANT = invariant
token ASSERT    = assert
token ASSUME    = assume
token TRUE      = true
token FALSE     = false
token NOT       = not
token AND       = and
token OR        = or
token FORALL    = forall
token EXISTS    = exists
token TYPE_INT  = int
token LENGTH    = length

# --- идентификаторы и числа --------------------------------------------------
token IDENT     = [A-Za-z_][A-Za-z0-9_]*
token INT       = 0|[1-9][0-9]*
# Число с ведущим нулём (00, 01, 007) - не INT. Без этого правила сканер молча
# разрезал бы "01" на INT("0") INT("1"); с ним выдаётся одна понятная ошибка.
error BAD_INT   = 0[0-9]+

# --- операторы ---------------------------------------------------------------
token PLUS      = \+
token MINUS     = -
token STAR      = \*
token SLASH     = /
token EQ        = ==
token NE        = !=
token LE        = <=
token GE        = >=
token LT        = <
token GT        = >
token ASSIGN    = =
token ARROW     = ->
token FATARROW  = =>

# --- разделители -------------------------------------------------------------
token LPAREN    = \(
token RPAREN    = \)
token LBRACKET  = \[
token RBRACKET  = \]
token LBRACE    = \{
token RBRACE    = \}
token COMMA     = ,
token SEMI      = ;
token COLON     = :
token BAR       = \|
