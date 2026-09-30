/* Brute-force the 32-bit account ID that encrypted a Capcom RE Engine DSSS save.
 *
 * Exported for savebridge/dsss.py (ctypes). See that file for the format.
 * A candidate ID is right when the SplitMix64 stream it starts reproduces the
 * 8 known mask bytes of the first slice header. 2^32 candidates, all cores.
 *
 * Build: native\build.cmd (MSVC), output savebridge\_native\dsss_find.dll
 */
#include <stdint.h>
#include <windows.h>

static uint64_t splitmix(uint64_t s)
{
    s += 0x9E3779B97F4A7C15ull;
    s = (s ^ (s >> 30)) * 0xBF58476D1CE4E5B9ull;
    s = (s ^ (s >> 27)) * 0x94D049BB133111EBull;
    return s ^ (s >> 31);
}

static uint64_t parse_id(uint32_t id, int variant)
{
    uint64_t sid = 0x0110000100000000ull | id;
    switch (variant) {
    case 0: return sid;
    case 1: return 0xFFFFFFFF00000000ull | (uint32_t)~id;
    case 2: return ~sid;
    default: {
        uint64_t x = sid ^ 0x1A3B5C7DD0C2B4A8ull;
        return ~((x >> 32) | (x << 32));
    }
    }
}

typedef struct {
    uint64_t state, mask;
    int variant;
    uint32_t first, step;
    volatile LONG64 *found;
} job_t;

static DWORD WINAPI worker(LPVOID p)
{
    job_t *j = (job_t *)p;
    for (uint64_t id = j->first; id <= 0xFFFFFFFFull; id += j->step) {
        if ((id & 0xFFFF) == 0 && *j->found >= 0) break;
        uint64_t s = j->state + parse_id((uint32_t)id, j->variant);
        for (int i = 0; i < 16; i++) s = splitmix(s);
        int ok = 1;
        for (int i = 0; i < 8 && ok; i++) {
            s = splitmix(s);
            ok = (uint8_t)s == (uint8_t)(j->mask >> (8 * i));
        }
        if (ok) { InterlockedExchange64(j->found, (LONG64)id); break; }
    }
    return 0;
}

__declspec(dllexport) int64_t dsss_find_id(uint64_t state, uint64_t mask, int variant)
{
    volatile LONG64 found = -1;
    DWORD n = GetActiveProcessorCount(ALL_PROCESSOR_GROUPS);
    if (n < 1) n = 1;
    if (n > 256) n = 256;
    job_t jobs[256];
    HANDLE threads[256];
    for (DWORD i = 0; i < n; i++) {
        jobs[i] = (job_t){state, mask, variant, i, n, &found};
        threads[i] = CreateThread(NULL, 0, worker, &jobs[i], 0, NULL);
    }
    for (DWORD i = 0; i < n; i += MAXIMUM_WAIT_OBJECTS)
        WaitForMultipleObjects(min(n - i, MAXIMUM_WAIT_OBJECTS), threads + i, TRUE, INFINITE);
    for (DWORD i = 0; i < n; i++) CloseHandle(threads[i]);
    return found;
}
