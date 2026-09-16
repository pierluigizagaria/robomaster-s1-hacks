/* Freestanding ARMv7 Thumb hook. No vendor code, imports, allocation or IO.
 * The config and code are immutable while reachable, except the aligned lease.
 * Scope: dji_sys event 003f0012 to app host 0200, chassis C205/C209 only.
 */
typedef unsigned char u8;
typedef unsigned short u16;
typedef unsigned int u32;
struct config { u32 original; volatile u32 until; u32 magic[2]; };
__asm__(".text\n.balign 4\n.global warning_config\nwarning_config:\n.space 16\n");

static u16 word(const u8 *p) { return p[0] | ((u16)p[1] << 8); }

__attribute__((used)) int warning_hook(void *handle, const u8 *event) {
    struct config *cfg;
    __asm__("adr %0, warning_config" : "=r"(cfg));
    int (*send)(void *, const u8 *) = (void *)cfg->original;
    u32 until = cfg->until;
    if (!until || !event || *(const u32 *)event != 0x003f0012 || word(event + 4) != 0x0200)
        return send(handle, event);
    u32 ts[2];
    register u32 r0 __asm__("r0") = 1; /* CLOCK_MONOTONIC */
    register u32 r1 __asm__("r1") = (u32)ts;
    register u32 r7 __asm__("r7") = 263; /* ARM EABI clock_gettime */
    __asm__ volatile("svc 0" : "+r"(r0) : "r"(r1), "r"(r7) : "memory", "cc");
    if (r0 || until <= ts[0] || until - ts[0] > 3)
        return send(handle, event);
    u32 length = *(const u32 *)(event + 12);
    if (!length || length > 1008) return send(handle, event);
    const u8 *p = event + 16;
    u32 at = 1;
    /* Fully validate before filtering. No early suppression of malformed input. */
    for (u32 i = 0; i < p[0]; ++i) {
        if (at + 3 > length) return send(handle, event);
        u32 prior = 1;
        for (u32 j = 0; j < i; ++j) {
            if (word(p + prior) == word(p + at)) return send(handle, event);
            prior += 3 + 2 * p[prior + 2];
        }
        at += 3 + 2 * p[at + 2];
        if (at > length) return send(handle, event);
    }
    if (at != length) return send(handle, event);
    u8 copy[1040];
    for (u32 i = 0; i < 17; ++i) copy[i] = event[i];
    u32 out = 17;
    at = 1;
    for (u32 i = 0; i < p[0]; ++i) {
        u16 module = word(p + at);
        u32 count = p[at + 2];
        copy[out++] = p[at++];
        copy[out++] = p[at++];
        u32 count_at = out++;
        copy[count_at] = 0;
        ++at;
        for (u32 j = 0; j < count; ++j) {
            u16 code = word(p + at);
            if (module != 0x0300 || (code != 0xc205 && code != 0xc209)) {
                copy[out++] = p[at];
                copy[out++] = p[at + 1];
                ++copy[count_at];
            }
            at += 2;
        }
    }
    *(u32 *)(copy + 12) = out - 16;
    return send(handle, copy);
}
