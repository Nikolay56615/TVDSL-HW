# Проект Funny → JVM

Компилятор берёт исходник Funny, проверяет его средствами HW1–HW3,
строит и оптимизирует IR из HW4, затем записывает JVM-байт-код.
Один модуль порождает один `public final` класс. Каждая функция
становится методом `public static` с исходным именем.

## Сборка и запуск

Нужны Python 3.10+ и JDK 11+. `java` и `javac` берутся из `JAVA_HOME`
или `PATH`. Команды выполняются из корня TVDSL-HW.

```powershell
python -m PROJECT.funnyjvm build PROJECT/examples/arrays_and_tuple.funny --out PROJECT/build
python -m PROJECT.funnyjvm run HW4/examples/good_loop.funny --args '[10]'
python -m PROJECT.funnyjvm run PROJECT/examples/arrays_and_tuple.funny --args '[[4,2,7]]'
python -m PROJECT.funnyjvm run PROJECT/examples/arrays_and_tuple.funny --function minmax --args '[[4,2,7]]'
```

Три команды `run` выведут `[55]`, `[[2,7,7],5]` и `[2,7]`.
По умолчанию вызывается функция `main`, а имя класса — `FunnyModule`.
Задайте `--class Example` для другого имени. Флаг `--no-opt` доступен
для обеих команд и передаёт кодогенератору IR до оптимизаций.

`build` записывает класс модуля и три класса среды исполнения.
`run` собирает их во временном каталоге и запускает с `-Xverify:all`.
Выход `run` — JSON-список результатов в порядке объявления `returns`.
Например, `[12]` — одно число, `[[1,2]]` — один массив.

Команда `javap` показывает сигнатуры и фактически сгенерированные инструкции.
Второй пример запускает уже собранный класс, передавая массив одной строкой.

```powershell
javap -c -s -classpath PROJECT/build FunnyModule
'4,2,7' | java -Xverify:all -cp PROJECT/build FunnyRunner FunnyModule minmax
```

Если `javap` доступен только через `JAVA_HOME`, в PowerShell используйте
`& "$env:JAVA_HOME/bin/javap" -c -s -classpath PROJECT/build FunnyModule`.

## ABI и генерация

| Результат Funny | Тип JVM |
| --- | --- |
| Одно число | `int` |
| Один массив | `ImmutableIntArray` |
| Несколько чисел | `int[]` в порядке `returns` |
| Несколько результатов, среди которых есть массив | `Object[]`, числа упакованы в `Integer` |

Последняя строка — расширение ABI для случая, который нельзя представить
через `int[]`. Обычный кортеж чисел сохраняет ABI задания.

В `runtime/` лежит реализация интерфейса `ImmutableIntArray` из ТЗ.
Присваивание именованной переменной массива копирует элементы,
обновление вызывает `with` и создаёт новый массив. Входной массив
остается неизменным. `length` и чтение элемента вызывают соответствующие
методы массива.

`funnyjvm/backend.py` переводит инструкции HW4 в операции со стеком JVM.
На границах базовых блоков стек пуст. Параметры и используемые значения
IR получают локальные слоты. Раскраска HW4 остаётся доступной в анализе
IR, слоты в этом бэкенде назначаются отдельно по именам. Вызовы генерируются
через `invokestatic`, включая вызовы вперёд и рекурсию. Класс записывается
напрямую в версии формата 49.0, где JVM проверяет переходы выводом типов
без `StackMapTable`. См. [формат класса JVM](https://docs.oracle.com/javase/specs/jvms/se25/html/jvms-4.html#jvms-4.10).
`javac` собирает только Java-классы среды исполнения.

## Диагностика и ограничения

Ошибки исходника приходят из HW1–HW3 с позицией. Деление на ноль
и выход за границы массива бросают обычные исключения JVM.
Чтение неинициализированной переменной проверяется отдельным флагом
и вызывает `IllegalStateException` с именем и позицией.
Код завершения 1 означает ошибку исходника или исполнения,
код 2 — ошибку запуска, файлов или аргументов команды.

Контракты, инварианты, формулы и `assert/assume` проходят проверку типов.
Для генерации применяются ограничения JVM на число параметров, слотов
и размер метода.

## Проверки assert и assume на JVM

`--runtime-asserts` работает в командах `run` и `build`. Если условие
ложно, JVM бросает `AssertionError`, а `run` печатает вид проверки и её
позицию в исходнике. В примере `assert` проверяет первый элемент непустого
массива, а `assume` проверяет, что второй аргумент неотрицателен.

```powershell
python -m PROJECT.funnyjvm run PROJECT/examples/runtime_asserts.funny --runtime-asserts --args '[[3],4]'
python -m PROJECT.funnyjvm run PROJECT/examples/runtime_asserts.funny --runtime-asserts --args '[[],4]'
python -m PROJECT.funnyjvm run PROJECT/examples/runtime_asserts.funny --runtime-asserts --args '[[3],-1]'
python -m PROJECT.funnyjvm run PROJECT/examples/runtime_asserts.funny --args '[[3],-1]'
```

Результаты по порядку — `[5]`, `assertion_failed` на строке 4,
`assumption_failed` на строке 5 и `[0]`. Без флага предикаты этих
операторов пропускаются. Флаг поддерживает арифметику, чтение массивов,
логические операции и вызовы формул. Квантор внутри исполняемой проверки
вызывает диагностику при сборке. `requires`, `ensures` и `invariant`
проверяются при анализе программы.

## Проверка оптимизаций через Z3

Команда `validate` принимает JSON с двумя блоками IR, `before` и `after`,
и списком общих входных регистров `inputs`. Поддерживаются целые числа,
копирование, арифметика и завершающий `return`. Z3 ищет вход, на котором
результаты различаются или только один блок делит на ноль.

```powershell
python -m pip install z3-solver
python -m PROJECT.funnyjvm validate PROJECT/examples/translation/add_zero.json
python -m PROJECT.funnyjvm validate PROJECT/examples/translation/multiply_one.json
python -m PROJECT.funnyjvm validate PROJECT/examples/translation/bad_divide_zero.json --smt-out "$env:TEMP/divide.smt2"
```

Первые две команды `validate` дают `unsat` и код 0. Последняя даёт
`sat`, код 1 и вход `{"v:x": 0}`. На нуле исходный блок `0 / x` падает,
а упрощённый возвращает 0. Для `--smt-out` укажите файл в существующей
папке. Статус `unknown` и ошибки запуска дают код 2.
См. [Z3 для Python](https://github.com/Z3Prover/z3#python) и
[32-битные векторы в SMT-LIB](https://smt-lib.org/logics-all.shtml#QF_BV).

## Тесты

```powershell
python -m unittest discover -s PROJECT/tests -v
```

Тесты запускают на JVM байт-код до и после оптимизации, проверяют
сигнатуры через `javap`, копирование массивов, смешанные кортежи,
ошибки исходника и рантайма, а также длинные переходы и широкие слоты.
Эталонные программы из HW4 используются повторно.
Отдельные тесты покрывают проверки с флагом и без него, корректные
и ошибочные преобразования IR, переполнение и деление на ноль.
Тесты, которые запускают решатель, требуют `z3-solver`.
