"""Запись класса JVM, таблицы констант и кода методов."""

from struct import pack


def u2(value):
    return pack(">H", value)


def u4(value):
    return pack(">I", value)


class ConstantPool:
    def __init__(self):
        self.entries = []
        self.indices = {}

    def _entry(self, tag, payload):
        key = (tag, payload)
        if key not in self.indices:
            if len(self.entries) == 65534:
                raise ValueError("Слишком много констант для одного класса JVM")
            self.entries.append(bytes((tag,)) + payload)
            self.indices[key] = len(self.entries)
        return self.indices[key]

    def utf8(self, text):
        # Имена и строки, которые эмиттер кладёт в .class, состоят из ASCII.
        encoded = text.encode("ascii")
        if len(encoded) > 65535:
            raise ValueError("Слишком длинная строка в таблице констант JVM")
        return self._entry(1, u2(len(encoded)) + encoded)

    def integer(self, value):
        return self._entry(3, pack(">i", value))

    def class_ref(self, name):
        return self._entry(7, u2(self.utf8(name)))

    def string(self, text):
        return self._entry(8, u2(self.utf8(text)))

    def method_ref(self, owner, name, descriptor):
        signature = self._entry(12, u2(self.utf8(name)) + u2(self.utf8(descriptor)))
        return self._entry(10, u2(self.class_ref(owner)) + u2(signature))

    def encode(self):
        return u2(len(self.entries) + 1) + b"".join(self.entries)


class Code:
    def __init__(self):
        self.data = bytearray()
        self.labels = {}
        self.jumps = []

    def emit(self, opcode, operands=b""):
        self.data.append(opcode)
        self.data.extend(operands)

    def local(self, opcode, slot):
        if slot < 256:
            self.emit(opcode, bytes((slot,)))
        else:
            self.emit(0xC4, bytes((opcode,)) + u2(slot))  # wide

    def label(self, label):
        self.labels[label] = len(self.data)

    def jump(self, opcode, target, *, wide=False):
        offset = len(self.data)
        size = 4 if wide else 2
        self.jumps.append((offset, size, target))
        self.emit(opcode, bytes(size))

    def finish(self):
        if len(self.data) >= 65536:
            raise ValueError("Метод JVM превышает предел в 65 535 байт")
        for offset, size, label in self.jumps:
            distance = self.labels[label] - offset
            self.data[offset + 1:offset + 1 + size] = distance.to_bytes(size, "big", signed=True)
        return bytes(self.data)


class ClassFile:
    def __init__(self, name):
        self.pool = ConstantPool()
        self.this_class = self.pool.class_ref(name)
        self.super_class = self.pool.class_ref("java/lang/Object")
        self.code_name = self.pool.utf8("Code")
        self.methods = []

    def add_method(self, name, descriptor, code, max_stack, max_locals, *, access=0x0009):
        if max_locals > 65535 or len(self.methods) == 65535:
            raise ValueError("Превышен предел числа локальных слотов или методов JVM")
        body = u2(max_stack) + u2(max_locals) + u4(len(code)) + code + bytes(4)
        header = (u2(access) + u2(self.pool.utf8(name)) + u2(self.pool.utf8(descriptor))
                  + u2(1))  # один атрибут Code
        self.methods.append(header + u2(self.code_name) + u4(len(body)) + body)

    def encode(self):
        # Версия 49 позволяет JVM проверить переходы по типам без StackMapTable.
        header = bytes.fromhex("CA FE BA BE") + u2(0) + u2(49) + self.pool.encode()
        # public final super, без интерфейсов и полей.
        declaration = u2(0x0031) + u2(self.this_class) + u2(self.super_class) + bytes(4)
        return header + declaration + u2(len(self.methods)) + b"".join(self.methods) + u2(0)
