#include <stdio.h>

int main(int argc, char* argv[])
{
    printf("Hello from %s\n", argv[0]);
#ifdef WIN32
    getchar();
#endif
    return 0;
}
