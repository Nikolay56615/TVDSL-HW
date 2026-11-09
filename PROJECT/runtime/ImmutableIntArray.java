/** Массив Funny. Входные данные копируются, обновление возвращает новый массив. */
public final class ImmutableIntArray {
    private final int[] data;

    private ImmutableIntArray(int[] data) {
        this.data = data;
    }

    public static ImmutableIntArray of(int... elems) {
        return copyOf(elems);
    }

    public static ImmutableIntArray copyOf(int[] source) {
        return new ImmutableIntArray(source.clone());
    }

    public int length() {
        return data.length;
    }

    public int get(int index) {
        return data[index];
    }

    public ImmutableIntArray with(int index, int value) {
        int[] updated = data.clone();
        updated[index] = value;
        return new ImmutableIntArray(updated);
    }
}
