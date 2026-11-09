import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStreamReader;
import java.lang.reflect.InvocationTargetException;
import java.lang.reflect.Method;
import java.lang.reflect.Modifier;
import java.nio.charset.StandardCharsets;
import java.util.StringJoiner;

/** Запускает один public static метод. Аргументы приходят по одному на строку. */
public final class FunnyRunner {
    private FunnyRunner() {}

    public static void main(String[] args) {
        try {
            Method method = findMethod(args[0], args[1]);
            Object[] inputs = readArguments(method.getParameterTypes());
            Object result = method.invoke(null, inputs);
            Class<?> resultType = method.getReturnType();
            if (resultType == int[].class || resultType == Object[].class) {
                System.out.println(render(result));
            } else {
                System.out.println("[" + render(result) + "]");
            }
        } catch (InvocationTargetException error) {
            Throwable cause = error.getCause();
            System.err.println("runtime [" + errorCode(cause) + "]: " + cause);
            System.exit(1);
        } catch (ReflectiveOperationException | LinkageError | IOException | IllegalArgumentException error) {
            System.err.println("jvm: " + error);
            System.exit(2);
        }
    }

    private static Method findMethod(String className, String methodName)
            throws ReflectiveOperationException {
        for (Method method : Class.forName(className).getDeclaredMethods()) {
            if (Modifier.isPublic(method.getModifiers()) && method.getName().equals(methodName)) {
                return method;
            }
        }
        throw new NoSuchMethodException(className + "." + methodName);
    }

    private static Object[] readArguments(Class<?>[] types) throws IOException {
        BufferedReader input = new BufferedReader(new InputStreamReader(System.in, StandardCharsets.UTF_8));
        Object[] args = new Object[types.length];
        for (int index = 0; index < types.length; index++) {
            String line = input.readLine();
            if (line == null) {
                throw new IOException("Missing argument " + index);
            }
            if (types[index] == int.class) {
                args[index] = Integer.valueOf(line);
            } else {
                String[] parts = line.isEmpty() ? new String[0] : line.split(",");
                int[] values = new int[parts.length];
                for (int item = 0; item < values.length; item++) {
                    values[item] = Integer.parseInt(parts[item]);
                }
                args[index] = ImmutableIntArray.of(values);
            }
        }
        return args;
    }

    private static String render(Object value) {
        StringJoiner items = new StringJoiner(",", "[", "]");
        if (value instanceof ImmutableIntArray) {
            ImmutableIntArray array = (ImmutableIntArray) value;
            for (int index = 0; index < array.length(); index++) {
                items.add(Integer.toString(array.get(index)));
            }
        } else if (value instanceof int[]) {
            for (int item : (int[]) value) {
                items.add(Integer.toString(item));
            }
        } else if (value instanceof Object[]) {
            for (Object item : (Object[]) value) {
                items.add(render(item));
            }
        } else {
            return value.toString();
        }
        return items.toString();
    }

    private static String errorCode(Throwable error) {
        if (error instanceof AssertionError) {
            String message = error.getMessage();
            return message != null && message.startsWith("assume ") ? "assumption_failed" : "assertion_failed";
        }
        if (error instanceof ArithmeticException) return "division_by_zero";
        if (error instanceof ArrayIndexOutOfBoundsException) return "array_bounds";
        if (error instanceof IllegalStateException) return "uninitialized";
        if (error instanceof StackOverflowError) return "recursion_limit";
        return "jvm_exception";
    }
}
