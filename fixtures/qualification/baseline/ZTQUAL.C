#include <stdio.h>

int main(void)
{
    int value = 6 * 7;
    if (value != 42)
        return 8;
    printf("ZTQUAL BASELINE PASS %d\n", value);
    return 0;
}
