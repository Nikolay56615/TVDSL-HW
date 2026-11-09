/** Служебные операции, вызываемые из сгенерированного байт-кода. */
public final class FunnyRuntime {
    private FunnyRuntime() {}

    public static AssertionError specFailure(String kind, String position) {
        return new AssertionError(kind + " at " + position);
    }

    public static void requireDefined(int defined, String location) {
        if (defined == 0) {
            throw new IllegalStateException(location);
        }
    }

    public static ImmutableIntArray copyArray(ImmutableIntArray source) {
        int[] values = new int[source.length()];
        for (int index = 0; index < values.length; index++) {
            values[index] = source.get(index);
        }
        return ImmutableIntArray.copyOf(values);
    }
}
