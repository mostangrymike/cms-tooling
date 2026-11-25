/* CMSED 0.3: a CMS-record stream editor for GCCCMS/PDPCLIB. */
/* Adds GNU/POSIX commands, ranges, blocks, richer BRE and options. */
#if defined(CMSED_HOST)
#include <stdio.h>
#include <string.h>
extern FILE *popen(const char *, const char *);
extern int pclose(FILE *);
#else
typedef struct cms_file FILE;
extern FILE *fopen(const char *, const char *);
extern int fclose(FILE *);
extern int fgetc(FILE *);
extern int fputc(int, FILE *);
extern int fputs(const char *, FILE *);
extern int printf(const char *, ...);
extern int sprintf(char *, const char *, ...);
extern int puts(const char *);
extern int remove(const char *);
extern int rename(const char *, const char *);
extern int system(const char *);
extern int strcmp(const char *, const char *);
extern int strncmp(const char *, const char *, unsigned long);
#endif

enum {
    MAX_COMMANDS = 128,
    MAX_SCRIPT_LINE = 1024,
    MAX_RECORD = 4096,
    MAX_STRING = 512,
    MAX_TEXT = 1024,
    MAX_APPEND = 8192,
    MAX_CAPTURES = 9,
    MAX_INPUT_FILES = 16,
    MAX_BLOCK_DEPTH = 32
};

enum {
    CMD_SUBSTITUTE = 1, CMD_DELETE, CMD_PRINT, CMD_QUIT,
    CMD_TRANSLATE, CMD_HOLD, CMD_APPEND_HOLD, CMD_GET_HOLD,
    CMD_APPEND_GET, CMD_EXCHANGE, CMD_BRANCH, CMD_TEST,
    CMD_TEST_NOT, CMD_LABEL, CMD_APPEND, CMD_INSERT, CMD_CHANGE,
    CMD_READ_FILE, CMD_WRITE_FILE, CMD_READ_LINE, CMD_WRITE_LINE,
    CMD_NEXT, CMD_APPEND_NEXT, CMD_PRINT_FIRST, CMD_DELETE_FIRST,
    CMD_LINE_NUMBER, CMD_LIST, CMD_FILENAME, CMD_ZAP, CMD_VERSION,
    CMD_QUIT_NOPRINT,
    CMD_BLOCK_START, CMD_BLOCK_END, CMD_EXEC
};

enum {
    ADDR_ALL = 0, ADDR_LINE, ADDR_REGEX, ADDR_LAST, ADDR_STEP,
    ADDR_PLUS, ADDR_MULT
};

typedef struct {
    int kind;
    int address_kind;
    int address_line;
    int address_step;
    int end_kind;
    int end_line;
    int has_end;
    int address_not;
    int range_active;
    int range_zero;
    int range_stop;
    int addr_icase;
    int addr_multiline;
    int global;
    int substitute_print;
    int sub_occurrence;
    int sub_icase;
    int sub_multiline;
    int sub_exec;
    int list_width;
    int branch_target;
    int block_end;
    int exit_code;
    FILE *write_file;
    FILE *sub_write_file;
    FILE *read_file;
    char address[MAX_STRING];
    char end_address[MAX_STRING];
    char pattern[MAX_STRING];
    char replacement[MAX_STRING];
    char text[MAX_TEXT];
    char second_text[MAX_STRING];
    char label[MAX_STRING];
    char write_name[MAX_STRING];
    char sub_write_name[MAX_STRING];
} SedCommand;

typedef struct {
    int start[MAX_CAPTURES + 1];
    int end[MAX_CAPTURES + 1];
    int count;
} MatchState;

static SedCommand commands[MAX_COMMANDS];
static int command_count;
static int quiet_mode;
static int separate_files;
#define SED_VERSION_MAJOR 4
#define SED_VERSION_MINOR 10
#define SED_VERSION_PATCH 0

static int nul_mode;
static int in_place;
static int ere_mode;
static int last_substitution;
static int quit_global;
static int exit_status;
static int error_flag;
static char hold_space[MAX_RECORD];
static FILE *output_stream;
static char last_parsed_regex[MAX_STRING];
static int rx_icase;
static int rx_multiline;
static int list_width = 70;
static int sandbox_mode;
static int posix_mode;
static int script_read_error;
#define GNU_BRE (!posix_mode || ere_mode)

static char input_ids[MAX_INPUT_FILES][MAX_STRING];
static FILE *input_preopened[MAX_INPUT_FILES];
static unsigned long file_counts[MAX_INPUT_FILES];
static int input_count;
static int input_pos;
static FILE *input_stream;
static char current_filename[MAX_STRING];
static unsigned long line_number;
static unsigned long total_lines;
static int record_sep = '\n';

static int parse_pending_kind;
static int parse_pending_index;
static int parse_stack[MAX_BLOCK_DEPTH];
static int parse_depth;

static int text_length(const char *text) {
    int length = 0;
    while (text[length]) length++;
    return length;
}

static void text_copy(char *to, const char *from, int size) {
    int i = 0;
    while (from[i] && i < size - 1) {
        to[i] = from[i];
        i++;
    }
    to[i] = 0;
}

static int is_digit(char c) {
    return c >= '0' && c <= '9';
}

static int parse_uint(const char *text) {
    int value = 0;
    if (!text || !*text) return -1;
    while (*text) {
        if (!is_digit(*text)) return -1;
        value = value * 10 + (*text++ - '0');
        if (value > 1000000) return -1;
    }
    return value;
}

static int version_newer(const char *text) {
    int parts[3] = { 0, 0, 0 };
    int i = 0;
    if (!text || !is_digit(*text)) return 1;
    while (i < 3 && is_digit(*text)) {
        while (is_digit(*text))
            parts[i] = parts[i] * 10 + (*text++ - '0');
        i++;
        if (*text != '.') break;
        text++;
        if (!is_digit(*text)) return 1;
    }
    if (parts[0] != SED_VERSION_MAJOR) return parts[0] > SED_VERSION_MAJOR;
    if (parts[1] != SED_VERSION_MINOR) return parts[1] > SED_VERSION_MINOR;
    return parts[2] > SED_VERSION_PATCH;
}

static int is_space(char c) {
    return c == ' ' || c == '\t' || c == '\r';
}

static int is_alpha(char c) {
    return (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z');
}

static int is_word(char c) {
    return is_alpha(c) || is_digit(c) || c == '_';
}

static char lower_char(char c) {
    if (c >= 'A' && c <= 'Z') return (char)(c - 'A' + 'a');
    return c;
}

static char upper_char(char c) {
    if (c >= 'a' && c <= 'z') return (char)(c - 'a' + 'A');
    return c;
}

static int utf8_length(const char *text) {
#if defined(CMSED_HOST)
    unsigned char c = (unsigned char)text[0];
    int n, i;
    if (c < 0x80) return 1;
    if (c >= 0xC2 && c <= 0xDF) n = 2;
    else if (c >= 0xE0 && c <= 0xEF) n = 3;
    else if (c >= 0xF0 && c <= 0xF4) n = 4;
    else return 1;
    for (i = 1; i < n; i++)
        if (((unsigned char)text[i] & 0xC0) != 0x80) return 1;
    return n;
#else
    (void)text;
    return 1;
#endif
}

static int chars_equal(char a, char b) {
    if (rx_icase) return lower_char(a) == lower_char(b);
    return a == b;
}

static void skip_space(const char **text) {
    while (is_space(**text)) (*text)++;
}

static int read_delimited(const char **input, char delimiter, char *out) {
    int used = 0;
    const char *text = *input;
    while (*text && *text != delimiter) {
        if (*text == '\\' && text[1] == delimiter) {
            if (used < MAX_STRING - 1) out[used++] = *text;
            text++;
        }
        if (used < MAX_STRING - 1) out[used++] = *text;
        text++;
    }
    if (*text != delimiter) return 0;
    out[used] = 0;
    *input = text + 1;
    return 1;
}

/* Escape decoding for y, replacement text and simple regex atoms. */
static int decode_escape(const char **text, char *out) {
    const char *p = *text;
    int value, digits;
    char c;
    if (*p != '\\' || !p[1]) {
        if (!*p) return 0;
        *out = *p;
        *text = p + 1;
        return 1;
    }
    p++;
    c = *p++;
    if (c == 'n') *out = '\n';
    else if (c == 't') *out = '\t';
    else if (c == 'r') *out = '\r';
    else if (c == 'f') *out = '\f';
    else if (c == 'v') *out = '\v';
    else if (c == 'a') *out = '\a';
    else if (c == 'b') *out = '\b';
    else if (c == 'x') {
        value = 0;
        digits = 0;
        while (digits < 2) {
            char h = *p;
            if (h >= '0' && h <= '9') h = (char)(h - '0');
            else if (h >= 'a' && h <= 'f') h = (char)(h - 'a' + 10);
            else if (h >= 'A' && h <= 'F') h = (char)(h - 'A' + 10);
            else break;
            value = value * 16 + h;
            p++;
            digits++;
        }
        if (!digits) {
            *out = 'x';
        } else *out = (char)value;
    } else if (c >= '0' && c <= '7') {
        value = c - '0';
        digits = 1;
        while (digits < 3 && *p >= '0' && *p <= '7') {
            value = value * 8 + (*p++ - '0');
            digits++;
        }
        *out = (char)value;
    } else {
        *out = c;
    }
    *text = p;
    return 1;
}

static int regex_class(const char *name, int length, char c) {
    int lower = lower_char(c);
    if (length == 5 && name[0] == 'a' && name[1] == 'l' &&
        name[2] == 'p') return is_alpha(c);
    if (length == 5 && name[0] == 'a' && name[1] == 'l' &&
        name[2] == 'n') return is_alpha(c) || is_digit(c);
    if (length == 5 && name[0] == 'b' && name[1] == 'l')
        return c == ' ' || c == '\t';
    if (length == 5 && name[0] == 'c' && name[1] == 'n')
        return (unsigned char)c < 32 || c == 127;
    if (length == 5 && name[0] == 'd' && name[1] == 'i')
        return is_digit(c);
    if (length == 5 && name[0] == 'g' && name[1] == 'r')
        return c > ' ' && c != 127;
    if (length == 5 && name[0] == 'l' && name[1] == 'o')
        return (unsigned char)c >= 'a' && c <= 'z';
    if (length == 5 && name[0] == 'p' && name[1] == 'r')
        return c >= ' ' && c != 127;
    if (length == 5 && name[0] == 'p' && name[1] == 'u')
        return c > ' ' && c != 127 && !is_alpha(c) && !is_digit(c);
    if (length == 5 && name[0] == 's' && name[1] == 'p')
        return c == ' ' || c == '\t' || c == '\r' || c == '\n' ||
               c == '\f' || c == '\v';
    if (length == 5 && name[0] == 'u' && name[1] == 'p')
        return (unsigned char)c >= 'A' && c <= 'Z';
    if (length == 4 && name[0] == 'w')
        return is_word(c);
    if (length == 6 && name[0] == 'x' && name[1] == 'd')
        return is_digit(c) || (lower >= 'a' && lower <= 'f');
    return 0;
}

static int class_length(const char *p) {
    int i = 1;
    if (p[i] == '^') i++;
    if (p[i] == ']') i++;
    while (p[i]) {
        if (p[i] == '[' && (p[i + 1] == ':' || p[i + 1] == '.' ||
                            p[i + 1] == '=')) {
            char marker = p[i + 1];
            i += 2;
            while (p[i] && !(p[i] == marker && p[i + 1] == ']')) i++;
            if (p[i]) i += 2;
            continue;
        }
        if (p[i] == '\\' && p[i + 1]) {
            i += 2;
            continue;
        }
        if (p[i] == ']') return i + 1;
        i++;
    }
    return 0;
}

static int class_match(const char *p, char c, int *used) {
    int i = 1, neg = 0, hit = 0;
    if (p[i] == '^') { neg = 1; i++; }
    if (p[i] == ']') {
        if (chars_equal(c, ']')) hit = 1;
        i++;
    }
    while (p[i] && p[i] != ']') {
        if (p[i] == '[' && p[i + 1] == ':') {
            int start = i + 2;
            int end = start;
            while (p[end] && !(p[end] == ':' && p[end + 1] == ']'))
                end++;
            if (p[end] == ':') {
                if (regex_class(p + start, end - start, c)) hit = 1;
                i = end + 2;
                continue;
            }
        }
        if (p[i] == '[' && (p[i + 1] == '.' || p[i + 1] == '=')) {
            char marker = p[i + 1];
            int start = i + 2;
            int end = start;
            while (p[end] && !(p[end] == marker && p[end + 1] == ']'))
                end++;
            if (p[end] == marker) {
                if (end == start + 1 && chars_equal(c, p[start])) hit = 1;
                i = end + 2;
                continue;
            }
        }
        {
            char first = p[i++];
            char last = first;
            if (p[i] == '-' && p[i + 1] && p[i + 1] != ']') {
                i++;
                last = p[i++];
            }
            if (rx_icase) {
                char test = lower_char(c);
                char lo = lower_char(first);
                char hi = lower_char(last);
                if (test >= lo && test <= hi) hit = 1;
            } else if (c >= first && c <= last) hit = 1;
        }
    }
    if (p[i] != ']') {
        *used = 1;
        return chars_equal(c, '[');
    }
    *used = i + 1;
    return neg ? !hit : hit;
}

static int atom_length(const char *p) {
    int i, depth;
    if (p[0] == '\\') {
        if (p[1] == '(') {
            depth = 1;
            i = 2;
            while (p[i]) {
                if (p[i] == '\\' && p[i + 1] == '(') {
                    depth++;
                    i += 2;
                } else if (p[i] == '\\' && p[i + 1] == ')') {
                    depth--;
                    i += 2;
                    if (!depth) return i;
                } else if (p[i] == '[') {
                    int n = class_length(p + i);
                    i += n ? n : 1;
                } else i++;
            }
            return 0;
        }
        if (p[1] == 'x' && p[2] && p[3]) return 4;
        return p[1] ? 2 : 1;
    }
    if (p[0] == '[') {
        int n = class_length(p);
        return n ? n : 1;
    }
    return 1;
}

static int match_pattern(const char *, const char *, const char *,
                         int *, MatchState *);
static int match_sequence(const char *, const char *, const char *,
                          int *, MatchState *, int);

static int match_atom(const char *atom, int alen, const char *text,
                      const char *base, int *consumed, MatchState *ms,
                      int at_start) {
    int used, i, group, start;
    char c;
    if (alen <= 0) return 0;
    if (atom[0] == '\\' && atom[1] == '(') {
        char body[MAX_STRING];
        int n = alen - 4;
        MatchState tmp;
        if (n < 0 || n >= MAX_STRING) return 0;
        for (i = 0; i < n; i++) body[i] = atom[i + 2];
        body[n] = 0;
        group = ms->count + 1;
        if (group > MAX_CAPTURES) return 0;
        tmp = *ms;
        tmp.count = group;
        start = (int)(text - base);
        tmp.start[group] = start;
        tmp.end[group] = -1;
        if (!match_pattern(body, text, base, consumed, &tmp)) return 0;
        tmp.end[group] = start + *consumed;
        *ms = tmp;
        return 1;
    }
    if (atom[0] == '\\' && atom[1] >= '1' && atom[1] <= '9') {
        group = atom[1] - '0';
        if (group > ms->count || ms->start[group] < 0 ||
            ms->end[group] < ms->start[group]) return 0;
        used = ms->end[group] - ms->start[group];
        for (i = 0; i < used; i++)
            if (!chars_equal(base[ms->start[group] + i], text[i]))
                return 0;
        *consumed = used;
        return 1;
    }
    if (atom[0] == '\\' && atom[1]) {
        if (atom[1] == 'w' || atom[1] == 'W' ||
            atom[1] == 's' || atom[1] == 'S') {
            int hit;
            if (atom[1] == 'w' || atom[1] == 'W')
                hit = is_word(*text);
            else
                hit = (*text == ' ' || *text == '\t' ||
                       *text == '\r' || *text == '\n' ||
                       *text == '\f' || *text == '\v');
            if (atom[1] == 'W' || atom[1] == 'S') hit = !hit;
            *consumed = 1;
            return *text && hit;
        }
        if (atom[1] == '`' || atom[1] == '\'') {
            *consumed = 0;
            if (atom[1] == '`') return text == base;
            return *text == 0;
        }
        if (atom[1] == 'b' || atom[1] == 'B' ||
            atom[1] == '<' || atom[1] == '>') {
            int before = text > base && is_word(text[-1]);
            int after = is_word(*text);
            int at_boundary = before != after;
            if (atom[1] == 'b') {
                *consumed = 0;
                return at_boundary;
            }
            if (atom[1] == 'B') {
                *consumed = 0;
                return !at_boundary;
            }
            if (atom[1] == '<') {
                *consumed = 0;
                return !before && after;
            }
            *consumed = 0;
            return before && !after;
        }
        if (atom[1] == 'n') c = '\n';
        else if (atom[1] == 't') c = '\t';
        else if (atom[1] == 'r') c = '\r';
        else if (atom[1] == 'f') c = '\f';
        else if (atom[1] == 'v') c = '\v';
        else if (atom[1] == 'x') {
            int value = 0, digits = 0;
            for (i = 2; i < alen; i++) {
                char h = atom[i];
                if (h >= '0' && h <= '9') h = (char)(h - '0');
                else if (h >= 'a' && h <= 'f') h = (char)(h - 'a' + 10);
                else if (h >= 'A' && h <= 'F') h = (char)(h - 'A' + 10);
                else break;
                value = value * 16 + h;
                digits++;
            }
            c = (char)value;
            if (!digits) return 0;
        } else c = atom[1];
        *consumed = 1;
        return *text && chars_equal(c, *text);
    }
    if (atom[0] == '[') {
        if (!*text) return 0;
        if (!class_match(atom, *text, &used)) return 0;
        *consumed = utf8_length(text);
        return 1;
    }
    if (atom[0] == '.') {
        if (!*text) return 0;
        *consumed = utf8_length(text);
        return 1;
    }
    if (atom[0] == '^' && alen == 1) {
        if (!at_start) {
            *consumed = 1;
            return *text && chars_equal('^', *text);
        }
        *consumed = 0;
        if (text == base) return 1;
        return rx_multiline && text > base && text[-1] == '\n';
    }
    *consumed = 1;
    return *text && chars_equal(atom[0], *text);
}

static int match_repeat(const char *atom, int alen, const char *rest,
                        const char *text, const char *base,
                        int minimum, int maximum, int *end,
                        MatchState *ms) {
    MatchState before = *ms;
    MatchState scratch = *ms;
    int count = 0, pos = 0, consumed, k, i, tail;
    while ((maximum < 0 || count < maximum) && text[pos]) {
        if (!match_atom(atom, alen, text + pos, base, &consumed,
                        &scratch, 0)) break;
        if (consumed <= 0) break;
        pos += consumed;
        count++;
        if (count > MAX_RECORD) break;
    }
    if (count < minimum) return 0;
    for (k = count; k >= minimum; k--) {
        MatchState trial = before;
        int p = 0, ok = 1;
        for (i = 0; i < k; i++) {
            if (!match_atom(atom, alen, text + p, base, &consumed,
                            &trial, 0)) {
                ok = 0;
                break;
            }
            if (consumed < 0) { ok = 0; break; }
            p += consumed;
        }
        if (!ok) continue;
        if (match_sequence(rest, text + p, base, &tail, &trial, 0)) {
            *end = p + tail;
            *ms = trial;
            return 1;
        }
    }
    *ms = before;
    return 0;
}

static int parse_interval(const char *q, int *length, int *minimum,
                          int *maximum) {
    const char *p = q + 2;
    int lo = 0, hi = 0, digits = 0;
    while (is_digit(*p)) {
        digits = 1;
        if (lo < 100000) lo = lo * 10 + (*p - '0');
        p++;
    }
    if (!digits) return 0;
    hi = lo;
    if (*p == ',') {
        p++;
        if (!is_digit(*p)) hi = -1;
        else {
            hi = 0;
            while (is_digit(*p)) {
                if (hi < 100000) hi = hi * 10 + (*p - '0');
                p++;
            }
        }
    }
    if (!(p[0] == '\\' && p[1] == '}')) return 0;
    *minimum = lo;
    *maximum = hi;
    *length = (int)(p + 2 - q);
    return 1;
}

static int match_sequence(const char *pattern, const char *text,
                          const char *base, int *end, MatchState *ms,
                          int at_start) {
    const char *p = pattern;
    int pos = 0, first = at_start, alen, consumed;
    while (*p) {
        const char *rest;
        int minimum = 0, maximum = 0, quant = 0, qlen = 0;
        alen = atom_length(p);
        if (alen <= 0) return 0;
        rest = p + alen;
        if (*rest == '*') {
            quant = 1; minimum = 0; maximum = -1; qlen = 1;
        } else if (GNU_BRE && rest[0] == '\\' && rest[1] == '+') {
            quant = 1; minimum = 1; maximum = -1; qlen = 2;
        } else if (GNU_BRE && rest[0] == '\\' && rest[1] == '?') {
            quant = 1; minimum = 0; maximum = 1; qlen = 2;
        } else if (GNU_BRE && rest[0] == '\\' && rest[1] == '{') {
            if (!parse_interval(rest, &qlen, &minimum, &maximum))
                return 0;
            quant = 1;
        }
        if (quant) rest += qlen;
        if (alen == 1 && p[0] == '$' && *rest == 0) {
            if (text[pos] != 0 &&
                !(rx_multiline && text[pos] == '\n')) return 0;
        } else if (quant) {
            if (!match_repeat(p, alen, rest, text + pos, base,
                              minimum, maximum, &consumed, ms))
                return 0;
            pos += consumed;
            *end = pos;
            return 1;
        } else {
            if (!match_atom(p, alen, text + pos, base, &consumed,
                            ms, first))
                return 0;
            pos += consumed;
        }
        p = rest;
        first = 0;
    }
    *end = pos;
    return 1;
}

static int match_pattern(const char *pattern, const char *text,
                         const char *base, int *end, MatchState *ms) {
    int starts[64], lengths[64], count = 0, i = 0, start = 0;
    int depth = 0, best = -1, best_end = -1;
    MatchState best_state;
    while (pattern[i]) {
        if (pattern[i] == '\\') {
            if (pattern[i + 1] == '(') depth++;
            else if (pattern[i + 1] == ')') depth--;
            else if (GNU_BRE && depth == 0 && pattern[i + 1] == '|') {
                if (count < 64) {
                    starts[count] = start;
                    lengths[count] = i - start;
                    count++;
                }
                i += 2;
                start = i;
                continue;
            }
            i += 2;
            continue;
        }
        if (pattern[i] == '[') {
            int n = class_length(pattern + i);
            i += n ? n : 1;
            continue;
        }
        i++;
    }
    if (count == 0) {
        return match_sequence(pattern, text, base, end, ms, 1);
    }
    if (count < 64) {
        starts[count] = start;
        lengths[count] = i - start;
        count++;
    }
    for (i = 0; i < count; i++) {
        char alt[MAX_STRING];
        MatchState trial = *ms;
        int n = lengths[i];
        int e;
        if (n >= MAX_STRING) continue;
        {
            int j;
            for (j = 0; j < n; j++) alt[j] = pattern[starts[i] + j];
            alt[n] = 0;
        }
        if (match_sequence(alt, text, base, &e, &trial, 1)) {
            if (e > best_end) {
                best_end = e;
                best = i;
                best_state = trial;
            }
        }
    }
    if (best < 0) return 0;
    *end = best_end;
    *ms = best_state;
    return 1;
}

static int find_match_at(const char *pattern, const char *line,
                         int offset, int *start, int *length,
                         MatchState *ms) {
    int len = text_length(line);
    int anchored = pattern[0] == '^';
    int pos;
    for (pos = offset; pos <= len; pos++) {
        MatchState trial;
        int i, end;
        if (anchored && !rx_multiline && pos > 0) break;
        for (i = 0; i <= MAX_CAPTURES; i++) {
            trial.start[i] = -1;
            trial.end[i] = -1;
        }
        trial.count = 0;
        if (match_pattern(pattern, line + pos, line, &end, &trial)) {
            *start = pos;
            *length = end;
            *ms = trial;
            return 1;
        }
    }
    return 0;
}

static int find_match(const char *pattern, const char *line,
                      int *start, int *length, MatchState *ms) {
    return find_match_at(pattern, line, 0, start, length, ms);
}

static int find_nth_char(const char *text, char c) {
    int i = 0;
    while (text[i] && text[i] != c) i++;
    return text[i] == c ? i : -1;
}

static int append_char(char *out, int used, char c) {
    if (used >= MAX_RECORD - 1) return -1;
    out[used] = c;
    out[used + 1] = 0;
    return used + 1;
}

static int append_string(char *out, int used, const char *text, int count) {
    int i;
    for (i = 0; i < count; i++) {
        used = append_char(out, used, text[i]);
        if (used < 0) return -1;
    }
    return used;
}

static int append_case(char *out, int used, const char *text, int count,
                       int *mode, int *next) {
    int i;
    for (i = 0; i < count; i++) {
        char c = text[i];
        if (*next == 1) c = upper_char(c);
        else if (*next == 2) c = lower_char(c);
        else if (*mode == 1) c = upper_char(c);
        else if (*mode == 2) c = lower_char(c);
        *next = 0;
        used = append_char(out, used, c);
        if (used < 0) return -1;
    }
    return used;
}

static int do_substitute(char *line, SedCommand *cmd) {
    char result[MAX_RECORD];
    MatchState ms;
    int used = 0, pos = 0, start = 0, length = 0, occ = 0, changed = 0;
    int len = text_length(line), i, r, target, old_icase, old_multi;
    int last_end = -1, after_nonempty = 0;
    int case_mode = 0, case_next = 0;
    old_icase = rx_icase;
    old_multi = rx_multiline;
    rx_icase = cmd->sub_icase;
    rx_multiline = cmd->sub_multiline;
    target = cmd->sub_occurrence;
    result[0] = 0;
    while (pos <= len) {
        if (!find_match_at(cmd->pattern, line, pos, &start, &length, &ms))
            break;
        if (start < pos) break;
        if (start > pos) {
            used = append_string(result, used, line + pos, start - pos);
            if (used < 0) goto too_long;
            pos = start;
            after_nonempty = 0;
        }
        if (length == 0 && after_nonempty && start == last_end) {
            if (pos < len) {
                used = append_char(result, used, line[pos++]);
                if (used < 0) goto too_long;
            } else break;
            after_nonempty = 0;
            continue;
        }
        if (target > 0 && occ + 1 < target) {
            used = append_string(result, used, line + pos,
                                start + length - pos);
            if (used < 0) goto too_long;
            pos = start + length;
            last_end = pos;
            after_nonempty = length > 0;
            occ++;
            continue;
        }
        used = append_string(result, used, line + pos, start - pos);
        if (used < 0) goto too_long;
        for (r = 0; cmd->replacement[r]; r++) {
            char c = cmd->replacement[r];
            if (c == '&') {
                used = append_case(result, used, line + start, length,
                                   &case_mode, &case_next);
                if (used < 0) goto too_long;
            } else if (c == '\\' && cmd->replacement[r + 1]) {
                char next = cmd->replacement[++r];
                if (next == 'U') case_mode = 1;
                else if (next == 'L') case_mode = 2;
                else if (next == 'E') case_mode = 0;
                else if (next == 'u') case_next = 1;
                else if (next == 'l') case_next = 2;
                else if (next >= '1' && next <= '9') {
                    int group = next - '0';
                    if (group <= ms.count && ms.start[group] >= 0 &&
                        ms.end[group] >= ms.start[group]) {
                        used = append_case(result, used,
                                           line + ms.start[group],
                                           ms.end[group] - ms.start[group],
                                           &case_mode, &case_next);
                        if (used < 0) goto too_long;
                    }
                } else if (next == 'n') {
                    used = append_case(result, used, "\n", 1,
                                       &case_mode, &case_next);
                } else if (next == 't') {
                    used = append_case(result, used, "\t", 1,
                                       &case_mode, &case_next);
                } else if (next == 'r') {
                    used = append_case(result, used, "\r", 1,
                                       &case_mode, &case_next);
                } else if (next == 'x') {
                    char decoded;
                    const char *ptr = cmd->replacement + r - 1;
                    decode_escape(&ptr, &decoded);
                    used = append_case(result, used, &decoded, 1,
                                       &case_mode, &case_next);
                    r = (int)(ptr - cmd->replacement) - 1;
                } else {
                    used = append_case(result, used, &next, 1,
                                       &case_mode, &case_next);
                }
                if (used < 0) goto too_long;
            } else {
                used = append_case(result, used, &c, 1,
                                   &case_mode, &case_next);
                if (used < 0) goto too_long;
            }
        }
        changed = 1;
        occ++;
        pos = start + length;
        last_end = pos;
        after_nonempty = length > 0;
        if (!cmd->global && target <= 0) break;
        if (target > 0 && !cmd->global && occ >= target) break;
        if (length == 0) {
            if (pos < len) {
                used = append_char(result, used, line[pos++]);
                if (used < 0) goto too_long;
            } else break;
        }
    }
    for (i = pos; i < len; i++) {
        used = append_char(result, used, line[i]);
        if (used < 0) goto too_long;
    }
    if (!changed) {
        rx_icase = old_icase;
        rx_multiline = old_multi;
        return 0;
    }
    text_copy(line, result, MAX_RECORD);
    if (cmd->sub_write_file) {
        char buf[MAX_RECORD];
        text_copy(buf, line, MAX_RECORD);
        fputs(buf, cmd->sub_write_file);
        fputc(record_sep, cmd->sub_write_file);
    }
    rx_icase = old_icase;
    rx_multiline = old_multi;
    return 1;
too_long:
    rx_icase = old_icase;
    rx_multiline = old_multi;
    return -1;
}

static void init_command(SedCommand *command) {
    command->kind = 0;
    command->address_kind = ADDR_ALL;
    command->address_line = 0;
    command->address_step = 0;
    command->end_kind = ADDR_ALL;
    command->end_line = 0;
    command->has_end = 0;
    command->address_not = 0;
    command->range_active = 0;
    command->range_zero = 0;
    command->range_stop = 0;
    command->addr_icase = 0;
    command->addr_multiline = 0;
    command->global = 0;
    command->substitute_print = 0;
    command->sub_occurrence = 0;
    command->sub_icase = 0;
    command->sub_multiline = 0;
    command->sub_exec = 0;
    command->list_width = 0;
    command->branch_target = -1;
    command->block_end = -1;
    command->exit_code = 0;
    command->write_file = 0;
    command->sub_write_file = 0;
    command->read_file = 0;
    command->address[0] = 0;
    command->end_address[0] = 0;
    command->pattern[0] = 0;
    command->replacement[0] = 0;
    command->text[0] = 0;
    command->second_text[0] = 0;
    command->label[0] = 0;
    command->write_name[0] = 0;
    command->sub_write_name[0] = 0;
}

static int parse_address(const char **cursor, int *kind, int *number,
                         int *step, char *pattern, int *icase,
                         int *multiline) {
    const char *text = *cursor;
    int value = 0;
    (void)icase;
    (void)multiline;
    if (*text == '$') {
        *kind = ADDR_LAST;
        *number = 0;
        *cursor = text + 1;
        return 1;
    }
    if (is_digit(*text)) {
        *kind = ADDR_LINE;
        while (is_digit(*text)) {
            if (value > 200000000) value = 200000000;
            else value = value * 10 + (*text - '0');
            text++;
        }
        *number = value;
        if (*text == '~') {
            int stepval = 0, digits = 0;
            text++;
            while (is_digit(*text)) {
                digits = 1;
                if (stepval > 200000000) stepval = 200000000;
                else stepval = stepval * 10 + (*text - '0');
                text++;
            }
            if (!digits || stepval <= 0) return 0;
            *kind = ADDR_STEP;
            *step = stepval;
        }
        *cursor = text;
        return 1;
    }
    if (*text == '/' || (*text == '\\' && text[1])) {
        char delimiter = *text == '\\' ? text[1] : '/';
        *kind = ADDR_REGEX;
        text += (*text == '\\') ? 2 : 1;
        if (!read_delimited(&text, delimiter, pattern)) return 0;
        *number = 0;
        *cursor = text;
        return 1;
    }
    return 0;
}

static int end_segment(const char **text) {
    skip_space(text);
    if (!**text || **text == ';' || **text == '}') return 1;
    return 0;
}

static void ere_to_bre(char *out, const char *in) {
    int i = 0, j = 0, in_class = 0;
    while (in[i]) {
        if (in_class) {
            out[j++] = in[i];
            if (in[i] == '\\' && in[i + 1]) out[j++] = in[++i];
            else if (in[i] == ']') in_class = 0;
            i++;
            continue;
        }
        if (in[i] == '[') {
            in_class = 1;
            out[j++] = in[i++];
            if (in[i] == '^') out[j++] = in[i++];
            if (in[i] == ']') out[j++] = in[i++];
            continue;
        }
        if (in[i] == '\\' && in[i + 1]) {
            char c = in[i + 1];
            if (c == '(' || c == ')' || c == '|' || c == '+' ||
                c == '?' || c == '{' || c == '}')
                out[j++] = c;
            else {
                out[j++] = in[i];
                out[j++] = in[i + 1];
            }
            i += 2;
            continue;
        }
        if (in[i] == '(' || in[i] == ')' || in[i] == '|' ||
            in[i] == '+' || in[i] == '?' || in[i] == '{' ||
            in[i] == '}') {
            out[j++] = '\\';
            out[j++] = in[i++];
            continue;
        }
        out[j++] = in[i++];
    }
    out[j] = 0;
}

static int regex_groups(const char *pattern) {
    int groups = 0, i = 0;
    while (pattern[i]) {
        if (pattern[i] == '\\' && pattern[i + 1]) {
            if (pattern[i + 1] == '(') groups++;
            i += 2;
            continue;
        }
        if (pattern[i] == '[') {
            int n = class_length(pattern + i);
            i += n ? n : 1;
            continue;
        }
        i++;
    }
    return groups;
}

static int validate_regex(const char *pattern) {
    int depth = 0, i = 0, groups;
    groups = regex_groups(pattern);
    while (pattern[i]) {
        if (pattern[i] == '[') {
            int n = class_length(pattern + i);
            if (n <= 0) return 0;
            i += n;
            continue;
        }
        if (pattern[i] != '\\') { i++; continue; }
        if (!pattern[i + 1]) return 0;
        if (pattern[i + 1] == '(') depth++;
        else if (pattern[i + 1] == ')') {
            depth--;
            if (depth < 0) return 0;
        } else if (pattern[i + 1] == '{') {
            int length, minimum, maximum;
            if (!parse_interval(pattern + i, &length, &minimum, &maximum))
                return 0;
            i += length;
            continue;
        } else if (pattern[i + 1] >= '1' && pattern[i + 1] <= '9') {
            if (pattern[i + 1] - '0' > groups) return 0;
        }
        i += 2;
    }
    return depth == 0;
}

static int validate_replacement(const char *replacement, int groups) {
    int i = 0;
    while (replacement[i]) {
        if (replacement[i] != '\\' || !replacement[i + 1]) {
            i++;
            continue;
        }
        if (replacement[i + 1] >= '1' && replacement[i + 1] <= '9') {
            if (replacement[i + 1] - '0' > groups) return 0;
        }
        i += 2;
    }
    return 1;
}

static int compile_regex(char *pattern) {
    if (ere_mode && pattern[0]) {
        char converted[MAX_STRING];
        ere_to_bre(converted, pattern);
        text_copy(pattern, converted, MAX_STRING);
    }
    if (pattern[0] && !validate_regex(pattern)) return 0;
    return 1;
}

static int resolve_empty_regex(char *pattern) {
    if (!pattern[0]) {
        if (!last_parsed_regex[0]) return 0;
        text_copy(pattern, last_parsed_regex, MAX_STRING);
    } else text_copy(last_parsed_regex, pattern, MAX_STRING);
    return 1;
}

static int parse_script_record(const char *line, int script_line) {
    const char *text = line;
    for (;;) {
        SedCommand command;
        int has_address = 0, has_end = 0, c;
        while (is_space(*text)) text++;
        if (!*text) return 1;
        if (*text == '#') return 1;
        if (*text == ';') { text++; continue; }
        if (*text == '}') {
            if (parse_depth <= 0) return 0;
            init_command(&command);
            command.kind = CMD_BLOCK_END;
            parse_depth--;
            commands[parse_stack[parse_depth]].block_end = command_count;
            commands[command_count++] = command;
            text++;
            continue;
        }
        if (command_count >= MAX_COMMANDS) return 0;
        init_command(&command);
        if (is_digit(*text) || *text == '$' || *text == '/' ||
            (*text == '\\' && text[1])) {
            has_address = 1;
            if (!parse_address(&text, &command.address_kind,
                               &command.address_line, &command.address_step,
                               command.address, &command.addr_icase,
                               &command.addr_multiline)) return 0;
            while (*text == 'I' || *text == 'M') {
                if (*text == 'I') command.addr_icase = 1;
                else command.addr_multiline = 1;
                text++;
            }
            if (*text == ',') {
                text++;
                if (*text == '+' || *text == '~') {
                    int sign = *text == '~' ? ADDR_MULT : ADDR_PLUS;
                    int value = 0, digits = 0;
                    text++;
                    while (is_digit(*text)) {
                        digits = 1;
                        value = value * 10 + *text++ - '0';
                    }
                    if (!digits) return 0;
                    command.end_kind = sign;
                    command.end_line = value;
                } else if (!parse_address(&text, &command.end_kind,
                                          &command.end_line,
                                          &command.address_step,
                                          command.end_address,
                                          &command.addr_icase,
                                          &command.addr_multiline)) {
                    return 0;
                }
                has_end = command.has_end = 1;
            }
            if (command.address_kind == ADDR_REGEX) {
                if (!compile_regex(command.address)) return 0;
                if (!resolve_empty_regex(command.address)) return 0;
            }
            if (command.end_kind == ADDR_REGEX) {
                if (!compile_regex(command.end_address)) return 0;
                if (!resolve_empty_regex(command.end_address)) return 0;
            }
            if (command.address_kind == ADDR_LINE &&
                command.address_line == 0) {
                if (!has_end || command.end_kind != ADDR_REGEX) return 0;
                command.range_zero = 1;
                command.range_active = 1;
            }
        }
        if (has_address && *text == '!') {
            command.address_not = 1;
            text++;
        }
        skip_space(&text);
        if (*text == '{') {
            command.kind = CMD_BLOCK_START;
            if (parse_depth >= MAX_BLOCK_DEPTH) return 0;
            commands[command_count] = command;
            parse_stack[parse_depth++] = command_count;
            command_count++;
            text++;
            continue;
        }
        if (*text == ':') {
            int n = 0;
            text++;
            skip_space(&text);
            while (*text && !is_space(*text) && *text != ';' &&
                   *text != '}' && n < MAX_STRING - 1)
                command.label[n++] = *text++;
            command.label[n] = 0;
            if (!command.label[0]) return 0;
            command.kind = CMD_LABEL;
            commands[command_count++] = command;
            if (!end_segment(&text)) return 0;
            continue;
        }
        if (!*text) return 0;
        c = *text++;
        if (c == 'd' || c == 'p' || c == 'q' || c == 'Q' ||
            c == 'h' || c == 'H' || c == 'g' || c == 'G' || c == 'x' ||
            c == '=' || c == 'l' || c == 'F' || c == 'z' ||
            c == 'n' || c == 'N' || c == 'P' || c == 'D') {
            if (c == 'q' || c == 'Q') {
                while (is_space(*text)) text++;
                while (is_digit(*text))
                    command.exit_code = command.exit_code * 10 +
                                        *text++ - '0';
            }
            if (c == 'd') command.kind = CMD_DELETE;
            else if (c == 'p') command.kind = CMD_PRINT;
            else if (c == 'q') command.kind = CMD_QUIT;
            else if (c == 'Q') command.kind = CMD_QUIT_NOPRINT;
            else if (c == 'h') command.kind = CMD_HOLD;
            else if (c == 'H') command.kind = CMD_APPEND_HOLD;
            else if (c == 'g') command.kind = CMD_GET_HOLD;
            else if (c == 'G') command.kind = CMD_APPEND_GET;
            else if (c == 'x') command.kind = CMD_EXCHANGE;
            else if (c == '=') command.kind = CMD_LINE_NUMBER;
            else if (c == 'l') command.kind = CMD_LIST;
            else if (c == 'F') command.kind = CMD_FILENAME;
            else if (c == 'z') command.kind = CMD_ZAP;
            else if (c == 'n') command.kind = CMD_NEXT;
            else if (c == 'N') command.kind = CMD_APPEND_NEXT;
            else if (c == 'P') command.kind = CMD_PRINT_FIRST;
            else command.kind = CMD_DELETE_FIRST;
            if (c == 'l') {
                skip_space(&text);
                while (is_digit(*text))
                    command.list_width = command.list_width * 10 +
                                         *text++ - '0';
                if (!command.list_width) command.list_width = 0;
            }
            if (!end_segment(&text)) return 0;
        } else if (c == 's') {
            char delimiter;
            delimiter = *text++;
            if (!delimiter || is_space(delimiter)) return 0;
            if (!read_delimited(&text, delimiter, command.pattern)) return 0;
            if (!read_delimited(&text, delimiter, command.replacement))
                return 0;
            for (;;) {
                if (*text == 'g') { command.global = 1; text++; }
                else if (*text == 'p') { command.substitute_print = 1; text++; }
                else if (*text == 'i' || *text == 'I') {
                    command.sub_icase = 1; text++;
                } else if (*text == 'm' || *text == 'M') {
                    command.sub_multiline = 1; text++;
                } else if (*text == 'e') { command.sub_exec = 1; text++; }
                else if (is_digit(*text)) {
                    while (is_digit(*text))
                        command.sub_occurrence = command.sub_occurrence * 10 +
                                                 *text++ - '0';
                } else break;
            }
            if (*text == 'w') {
                text++;
                skip_space(&text);
                text_copy(command.sub_write_name, text, MAX_STRING);
                command.kind = CMD_SUBSTITUTE;
                if (!compile_regex(command.pattern)) return 0;
                if (!resolve_empty_regex(command.pattern)) return 0;
                if (!command.pattern[0] ||
                    !validate_replacement(command.replacement,
                                          regex_groups(command.pattern)))
                    return 0;
                commands[command_count++] = command;
                return 1;
            }
            if (!end_segment(&text)) return 0;
            command.kind = CMD_SUBSTITUTE;
            if (!compile_regex(command.pattern)) return 0;
            if (!resolve_empty_regex(command.pattern)) return 0;
            if (!validate_replacement(command.replacement,
                                      regex_groups(command.pattern)))
                return 0;
        } else if (c == 'y') {
            char delimiter;
            char source[MAX_STRING], dest[MAX_STRING];
            int si = 0, di = 0;
            const char *sp, *dp;
            char decoded;
            delimiter = *text++;
            if (!delimiter || is_space(delimiter)) return 0;
            if (!read_delimited(&text, delimiter, command.pattern)) return 0;
            if (!read_delimited(&text, delimiter, command.replacement))
                return 0;
            sp = command.pattern;
            while (*sp && si < MAX_STRING - 1) {
                decode_escape(&sp, &decoded);
                source[si++] = decoded;
            }
            source[si] = 0;
            dp = command.replacement;
            while (*dp && di < MAX_STRING - 1) {
                decode_escape(&dp, &decoded);
                dest[di++] = decoded;
            }
            dest[di] = 0;
            if (si != di) return 0;
            text_copy(command.pattern, source, MAX_STRING);
            text_copy(command.replacement, dest, MAX_STRING);
            command.kind = CMD_TRANSLATE;
            if (!end_segment(&text)) return 0;
        } else if (c == 'b' || c == 't' || c == 'T') {
            int n = 0;
            command.kind = c == 'b' ? CMD_BRANCH :
                           c == 't' ? CMD_TEST : CMD_TEST_NOT;
            skip_space(&text);
            while (*text && !is_space(*text) && *text != ';' &&
                   *text != '}' && n < MAX_STRING - 1)
                command.label[n++] = *text++;
            command.label[n] = 0;
            if (!end_segment(&text)) return 0;
        } else if (c == 'a' || c == 'i' || c == 'c') {
            command.kind = c == 'a' ? CMD_APPEND :
                           c == 'i' ? CMD_INSERT : CMD_CHANGE;
            skip_space(&text);
            if (*text == '\\' && text[1] == 0) {
                parse_pending_kind = command.kind;
                parse_pending_index = command_count;
                command.text[0] = 0;
                commands[command_count++] = command;
                return 1;
            }
            if (*text == '\\') text++;
            text_copy(command.text, text, MAX_TEXT);
            commands[command_count++] = command;
            return 1;
        } else if (c == 'v') {
            int n = 0;
            command.kind = CMD_VERSION;
            skip_space(&text);
            while (text[n] && text[n] != ';' && text[n] != ' ' &&
                   text[n] != '\t' && n < MAX_STRING - 1) {
                command.text[n] = text[n];
                n++;
            }
            command.text[n] = 0;
            commands[command_count++] = command;
            return 1;
        } else if (c == 'r' || c == 'w' || c == 'R' || c == 'W') {
            skip_space(&text);
            command.kind = c == 'r' ? CMD_READ_FILE :
                           c == 'w' ? CMD_WRITE_FILE :
                           c == 'R' ? CMD_READ_LINE : CMD_WRITE_LINE;
            text_copy(command.text, text, MAX_STRING);
            if (!command.text[0]) return 0;
            commands[command_count++] = command;
            return 1;
        } else if (c == 'e') {
            skip_space(&text);
            command.kind = CMD_EXEC;
            text_copy(command.text, text, MAX_TEXT);
            commands[command_count++] = command;
            return 1;
        } else {
            return 0;
        }
        commands[command_count++] = command;
        (void)script_line;
    }
}

static int append_pending_line(const char *line, int length) {
    SedCommand *command;
    int used, i, more = 0;
    if (parse_pending_kind == 0) return 0;
    if (parse_pending_index < 0 || parse_pending_index >= command_count)
        return 0;
    command = &commands[parse_pending_index];
    if (length > 0 && line[length - 1] == '\\') {
        length--;
        more = 1;
    }
    used = text_length(command->text);
    if (used && used < MAX_TEXT - 1) command->text[used++] = '\n';
    i = 0;
    while (i < length && (line[i] == ' ' || line[i] == '\t')) i++;
    for (; i < length && used < MAX_TEXT - 1; i++)
        command->text[used++] = line[i];
    command->text[used] = 0;
    if (!more) parse_pending_kind = 0;
    return 1;
}

static int read_script_line(FILE *script, char *out, int size) {
    int c, used = 0;
    while ((c = fgetc(script)) != -1) {
        if (c == '\n') {
            out[used] = 0;
            return 1;
        }
        if (c == '\r') continue;
        if (used >= size - 1) return 0;
        out[used++] = (char)c;
    }
    if (!used) return 0;
    out[used] = 0;
    return 1;
}

static int load_script_stream(FILE *script);

static int take_script_line(char *line, int line_no) {
    int n = text_length(line);
    if (parse_pending_kind) return append_pending_line(line, n);
    if (n == 2 && line[0] == '#' && line[1] == 'n' && line_no == 1)
        quiet_mode = 1;
    if (!parse_script_record(line, line_no)) {
        printf("sed: bad script at line %d\n", line_no);
        return 0;
    }
    return 1;
}

static int finish_script(void) {
    if (parse_pending_kind) {
        puts("sed: unterminated a/i/c text");
        return 0;
    }
    return 1;
}

static int load_script_string(const char *text) {
    char line[MAX_SCRIPT_LINE];
    int used = 0, line_no = 0;
    for (;;) {
        if (*text == '\n' || !*text) {
            line[used] = 0;
            line_no++;
            if (!take_script_line(line, line_no)) return 0;
            used = 0;
            if (!*text) break;
            text++;
            continue;
        }
        if (*text == '\r') { text++; continue; }
        if (used >= MAX_SCRIPT_LINE - 1) return 0;
        line[used++] = *text++;
    }
    return finish_script();
}

static int load_script_stream(FILE *script) {
    char line[MAX_SCRIPT_LINE];
    int line_no = 0;
    while (read_script_line(script, line, sizeof line)) {
        line_no++;
        if (!take_script_line(line, line_no)) return 0;
    }
    return finish_script();
}

static int load_script(const char *fileid) {
    FILE *script = fopen(fileid, "r");
    int ok;
    if (!script) {
        script_read_error = 1;
        return 0;
    }
    ok = load_script_stream(script);
    if (fclose(script) != 0) ok = 0;
    return ok;
}

static int resolve_branches(void) {
    int i, j;
    if (parse_depth != 0) return 0;
    for (i = 0; i < command_count; i++) {
        SedCommand *command = &commands[i];
        if (command->kind != CMD_BRANCH && command->kind != CMD_TEST &&
            command->kind != CMD_TEST_NOT) continue;
        command->branch_target = command_count;
        if (!command->label[0]) continue;
        for (j = 0; j < command_count; j++) {
            if (commands[j].kind == CMD_LABEL &&
                text_length(command->label) ==
                text_length(commands[j].label)) {
                int k = 0;
                while (command->label[k] &&
                       command->label[k] == commands[j].label[k]) k++;
                if (!command->label[k]) break;
            }
        }
        if (j == command_count) return 0;
        command->branch_target = j;
    }
    return 1;
}

static int reset_for_file(void) {
    int i;
    line_number = 0;
    for (i = 0; i < command_count; i++) {
        if (commands[i].range_zero) commands[i].range_active = 1;
        else commands[i].range_active = 0;
    }
    return 1;
}

static int regex_address(const SedCommand *command, const char *pattern,
                         const char *line) {
    int start, length;
    MatchState ms;
    int old_icase = rx_icase, old_multi = rx_multiline;
    int found;
    rx_icase = command->addr_icase;
    rx_multiline = command->addr_multiline;
    found = find_match(pattern, line, &start, &length, &ms);
    rx_icase = old_icase;
    rx_multiline = old_multi;
    return found;
}

static int start_address_matches(const SedCommand *command,
                                 const char *line) {
    if (command->address_kind == ADDR_ALL) return 1;
    if (command->address_kind == ADDR_LINE)
        return line_number == (unsigned long)command->address_line;
    if (command->address_kind == ADDR_LAST)
        return line_number == total_lines;
    if (command->address_kind == ADDR_STEP) {
        if (line_number < (unsigned long)command->address_line) return 0;
        return ((line_number - command->address_line) %
                command->address_step) == 0;
    }
    return regex_address(command, command->address, line);
}

static int end_address_matches(const SedCommand *command,
                               const char *line) {
    if (command->end_kind == ADDR_LINE)
        return line_number >= (unsigned long)command->end_line;
    if (command->end_kind == ADDR_LAST)
        return line_number >= total_lines;
    if (command->end_kind == ADDR_PLUS || command->end_kind == ADDR_MULT)
        return line_number >= (unsigned long)command->range_stop;
    if (command->end_kind == ADDR_REGEX)
        return regex_address(command, command->end_address, line);
    return 0;
}

static void set_range_stop(SedCommand *command) {
    if (command->end_kind == ADDR_PLUS) {
        command->range_stop = (int)line_number + command->end_line;
    } else if (command->end_kind == ADDR_MULT) {
        int n = command->end_line;
        if (n <= 0) n = 1;
        command->range_stop =
            (int)(((line_number + n - 1) / n) * n);
        if (command->range_stop <= (int)line_number)
            command->range_stop += n;
    }
}

static int address_matches(SedCommand *command, const char *line) {
    int matched = 0;
    if (command->address_kind == ADDR_ALL) return 1;
    if (!command->has_end) {
        matched = start_address_matches(command, line);
    } else if (command->range_zero && command->range_active) {
        if (end_address_matches(command, line)) {
            command->range_active = 0;
        }
        matched = 1;
    } else if (command->range_active) {
        matched = 1;
        if (end_address_matches(command, line))
            command->range_active = 0;
    } else if (start_address_matches(command, line)) {
        matched = 1;
        set_range_stop(command);
        if (end_address_matches(command, line))
            command->range_active = 0;
        else
            command->range_active = 1;
    }
    return command->address_not ? !matched : matched;
}

static void write_text(const char *text) {
    if (output_stream) fputs(text, output_stream);
    else printf("%s", text);
}

static void write_char(char c) {
    if (output_stream) fputc(c, output_stream);
    else printf("%c", c);
}

static void write_newline(void) {
    if (output_stream) fputc(record_sep, output_stream);
    else printf("%c", record_sep);
}

static void emit_text(const char *text, int terminated) {
    const char *p = text;
    if (nul_mode) {
        write_text(text);
        if (terminated) write_char(record_sep);
        return;
    }
    for (;;) {
        const char *q = p;
        char chunk[MAX_RECORD];
        int n;
        while (*q && *q != '\n') q++;
        n = (int)(q - p);
        if (n >= MAX_RECORD) n = MAX_RECORD - 1;
        {
            int i;
            for (i = 0; i < n; i++) chunk[i] = p[i];
            chunk[n] = 0;
        }
        write_text(chunk);
        if (*q == '\n') {
            write_newline();
            p = q + 1;
            continue;
        }
        break;
    }
    if (terminated) write_newline();
}

static void output_record(const char *line, int terminated) {
    emit_text(line, terminated);
}

static int output_stream_open;

static FILE *open_write(const char *name) {
    FILE *stream;
    if (!name[0]) return 0;
#if defined(CMSED_HOST)
    if (!strcmp(name, "/dev/stdout")) return stdout;
    if (!strcmp(name, "/dev/stderr")) return stderr;
#endif
    stream = fopen(name, "w");
    return stream;
}

static int prepare_write_files(void) {
    int i;
    if (sandbox_mode) {
        for (i = 0; i < command_count; i++) {
            SedCommand *command = &commands[i];
            if (command->kind == CMD_WRITE_FILE ||
                command->kind == CMD_WRITE_LINE ||
                (command->kind == CMD_SUBSTITUTE &&
                 command->sub_write_name[0])) {
                puts("sed: e/r/w commands disabled in sandbox mode");
                exit_status = 1;
                return 0;
            }
        }
    }
    for (i = 0; i < command_count; i++) {
        SedCommand *command = &commands[i];
        if (command->kind == CMD_WRITE_FILE) {
            command->write_file = open_write(command->text);
            if (!command->write_file) {
                printf("sed: cannot open output %s\n", command->text);
                return 0;
            }
        } else if (command->kind == CMD_WRITE_LINE) {
            command->write_file = open_write(command->text);
            if (!command->write_file) {
                printf("sed: cannot open output %s\n", command->text);
                return 0;
            }
        } else if (command->kind == CMD_SUBSTITUTE &&
                   command->sub_write_name[0]) {
            command->sub_write_file = open_write(command->sub_write_name);
            if (!command->sub_write_file) {
                printf("sed: cannot open output %s\n",
                       command->sub_write_name);
                return 0;
            }
        }
    }
    output_stream_open = 1;
    return 1;
}

static void close_write_files(void) {
    int i;
    for (i = 0; i < command_count; i++) {
        if (commands[i].write_file) {
#if defined(CMSED_HOST)
            if (commands[i].write_file != stdout &&
                commands[i].write_file != stderr)
#endif
            fclose(commands[i].write_file);
            commands[i].write_file = 0;
        }
        if (commands[i].sub_write_file) fclose(commands[i].sub_write_file);
        if (commands[i].read_file) fclose(commands[i].read_file);
        commands[i].sub_write_file = 0;
        commands[i].read_file = 0;
    }
    output_stream_open = 0;
}

static int append_block(char *buffer, int used, const char *text) {
    int n = text_length(text);
    if (used + n + 2 >= MAX_APPEND) return -1;
    if (used) buffer[used++] = '\n';
    text_copy(buffer + used, text, MAX_APPEND - used);
    used += n;
    if (!n || text[n - 1] != '\n') buffer[used++] = '\n';
    buffer[used] = 0;
    return used;
}

static int append_file_text(char *buffer, int used, const char *name) {
    FILE *file = fopen(name, "r");
    int c;
    if (!file) return used;
    while ((c = fgetc(file)) != -1) {
        if (used + 1 >= MAX_APPEND) {
            fclose(file);
            puts("sed: appended text too long");
            return -1;
        }
#if !defined(CMSED_HOST)
        if (c == '\r') continue;
#endif
        buffer[used++] = (char)c;
    }
    buffer[used] = 0;
    fclose(file);
    if (used && buffer[used - 1] != '\n') {
        if (used + 1 >= MAX_APPEND) return -1;
        buffer[used++] = '\n';
        buffer[used] = 0;
    }
    return used;
}

static int append_read_line(char *buffer, int used, SedCommand *command) {
    int c;
    if (!command->read_file) command->read_file = fopen(command->text, "r");
    if (!command->read_file) return used;
    if (used + 1 >= MAX_APPEND) return -1;
    if (used) buffer[used++] = '\n';
    for (;;) {
        c = fgetc(command->read_file);
        if (c == -1) {
            if (used && buffer[used - 1] != '\n') {
                buffer[used++] = '\n';
            }
            buffer[used] = 0;
            fclose(command->read_file);
            command->read_file = 0;
            return used;
        }
#if !defined(CMSED_HOST)
        if (c == '\r') continue;
#endif
        if (used + 1 >= MAX_APPEND) return -1;
        buffer[used++] = (char)c;
        if (c == '\n') {
            buffer[used] = 0;
            return used;
        }
    }
}

static int list_escape_byte(unsigned char c) {
    if (c < 32 || c == 127) return 1;
#if defined(CMSED_HOST)
    if (c >= 128) return 1;
#endif
    return 0;
}

static void list_pattern(const char *line, int terminated, int width) {
    char out[MAX_RECORD * 2];
    int used = 0, i = 0, col = 0;
    if (width < 1) width = 70;
    while (line[i]) {
        unsigned char c = (unsigned char)line[i++];
        if (width > 1 && col >= width - 1) {
            out[used++] = '\\';
            out[used++] = '\n';
            col = 0;
        }
        if (c == '\\') {
            out[used++] = '\\';
            out[used++] = '\\';
            col += 2;
        } else if (c == '\n') {
            out[used++] = '\\';
            out[used++] = 'n';
            col += 2;
        } else if (c == '\t') {
            out[used++] = '\\';
            out[used++] = 't';
            col += 2;
        } else if (c == '\a') {
            out[used++] = '\\';
            out[used++] = 'a';
            col += 2;
        } else if (c == '\b') {
            out[used++] = '\\';
            out[used++] = 'b';
            col += 2;
        } else if (c == '\v') {
            out[used++] = '\\';
            out[used++] = 'v';
            col += 2;
        } else if (c == '\f') {
            out[used++] = '\\';
            out[used++] = 'f';
            col += 2;
        } else if (c == '\r') {
            out[used++] = '\\';
            out[used++] = 'r';
            col += 2;
        } else if (list_escape_byte(c)) {
            out[used++] = '\\';
            out[used++] = (char)('0' + ((c >> 6) & 7));
            out[used++] = (char)('0' + ((c >> 3) & 7));
            out[used++] = (char)('0' + (c & 7));
            col += 4;
        } else {
            out[used++] = (char)c;
            col++;
        }
        if (used >= MAX_RECORD * 2 - 4) break;
    }
    out[used++] = '$';
    out[used] = 0;
    emit_text(out, terminated);
}

static int host_exec_text(const char *text, char *out, int size) {
#if defined(CMSED_HOST)
    FILE *pipe = popen(text, "r");
    int c, used = 0;
    if (!pipe) return 0;
    while ((c = fgetc(pipe)) != -1) {
        if (used < size - 1) out[used++] = (char)c;
    }
    pclose(pipe);
    out[used] = 0;
    while (used > 0 && (out[used - 1] == '\n' || out[used - 1] == '\r'))
        out[--used] = 0;
    return 1;
#else
    (void)text;
    (void)size;
    out[0] = 0;
    puts("sed: e command is not available on CMS");
    exit_status = 2;
    return 0;
#endif
}

static int input_read_record(char *out, int *terminated);

static int execute_cycle(char *pattern, int *terminated) {
    char appended[MAX_APPEND];
    int appended_used = 0, pc = 0, deleted = 0;
    last_substitution = 0;
    appended[0] = 0;
    while (pc < command_count && !quit_global) {
        SedCommand *command = &commands[pc];
        if (command->kind == CMD_BLOCK_END) {
            pc++;
            continue;
        }
        if (command->kind == CMD_LABEL) {
            pc++;
            continue;
        }
        if (command->kind == CMD_BLOCK_START) {
            if (!address_matches(command, pattern))
                pc = command->block_end + 1;
            else pc++;
            continue;
        }
        if (!address_matches(command, pattern)) {
            pc++;
            continue;
        }
        switch (command->kind) {
        case CMD_DELETE:
            deleted = 1;
            break;
        case CMD_PRINT:
            output_record(pattern, *terminated);
            break;
        case CMD_PRINT_FIRST: {
            char first[MAX_RECORD];
            int n = find_nth_char(pattern, '\n');
            if (n < 0) n = text_length(pattern);
            text_copy(first, pattern, n + 1);
            output_record(first, 1);
            break;
        }
        case CMD_DELETE_FIRST: {
            int n = find_nth_char(pattern, '\n');
            if (n >= 0) {
                text_copy(pattern, pattern + n + 1, MAX_RECORD);
                pc = 0;
                continue;
            }
            deleted = 1;
            break;
        }
        case CMD_QUIT:
            if (command->exit_code) exit_status = command->exit_code;
            quit_global = 1;
            break;
        case CMD_QUIT_NOPRINT:
            if (command->exit_code) exit_status = command->exit_code;
            quit_global = 1;
            deleted = 1;
            break;
        case CMD_SUBSTITUTE: {
            int r = do_substitute(pattern, command);
            if (r < 0) {
                puts("sed: output record too long");
                error_flag = 1;
                return 0;
            }
            if (r > 0) {
                last_substitution = 1;
                if (command->substitute_print)
                    output_record(pattern, *terminated);
                if (command->sub_exec) {
                    char executed[MAX_RECORD];
                    if (sandbox_mode) {
                        puts("sed: e/r/w commands disabled in sandbox mode");
                        exit_status = 1;
                        return 0;
                    }
                    if (host_exec_text(pattern, executed, MAX_RECORD))
                        text_copy(pattern, executed, MAX_RECORD);
                }
            }
            break;
        }
        case CMD_TRANSLATE: {
            int j, k, n = text_length(command->pattern);
            for (j = 0; pattern[j]; j++)
                for (k = 0; k < n; k++)
                    if (pattern[j] == command->pattern[k]) {
                        pattern[j] = command->replacement[k];
                        break;
                    }
            break;
        }
        case CMD_HOLD:
            text_copy(hold_space, pattern, MAX_RECORD);
            break;
        case CMD_APPEND_HOLD: {
            int n = text_length(hold_space);
            if (n < MAX_RECORD - 1) hold_space[n++] = '\n';
            text_copy(hold_space + n, pattern, MAX_RECORD - n);
            break;
        }
        case CMD_GET_HOLD:
            text_copy(pattern, hold_space, MAX_RECORD);
            break;
        case CMD_APPEND_GET: {
            int n = text_length(pattern);
            if (n < MAX_RECORD - 1) pattern[n++] = '\n';
            text_copy(pattern + n, hold_space, MAX_RECORD - n);
            break;
        }
        case CMD_EXCHANGE: {
            char temp[MAX_RECORD];
            text_copy(temp, pattern, MAX_RECORD);
            text_copy(pattern, hold_space, MAX_RECORD);
            text_copy(hold_space, temp, MAX_RECORD);
            break;
        }
        case CMD_INSERT:
            emit_text(command->text, 1);
            break;
        case CMD_APPEND:
            appended_used = append_block(appended, appended_used,
                                         command->text);
            if (appended_used < 0) {
                puts("sed: appended text too long");
                error_flag = 1;
                return 0;
            }
            break;
        case CMD_READ_FILE:
            if (sandbox_mode) {
                puts("sed: e/r/w commands disabled in sandbox mode");
                exit_status = 1;
                return 0;
            }
            appended_used = append_file_text(appended, appended_used,
                                             command->text);
            if (appended_used < 0) {
                error_flag = 1;
                return 0;
            }
            break;
        case CMD_READ_LINE:
            if (sandbox_mode) {
                puts("sed: e/r/w commands disabled in sandbox mode");
                exit_status = 1;
                return 0;
            }
            appended_used = append_read_line(appended, appended_used,
                                             command);
            if (appended_used < 0) {
                error_flag = 1;
                return 0;
            }
            break;
        case CMD_CHANGE:
            if (command->has_end && command->range_active) {
                deleted = 1;
                break;
            }
            emit_text(command->text, 1);
            deleted = 1;
            break;
        case CMD_WRITE_FILE:
            if (command->write_file) {
                fputs(pattern, command->write_file);
                fputc(record_sep, command->write_file);
            }
            break;
        case CMD_WRITE_LINE: {
            char first[MAX_RECORD];
            int n = find_nth_char(pattern, '\n');
            if (n < 0) n = text_length(pattern);
            text_copy(first, pattern, n + 1);
            if (command->write_file) {
                fputs(first, command->write_file);
                fputc(record_sep, command->write_file);
            }
            break;
        }
        case CMD_BRANCH:
            pc = command->branch_target;
            continue;
        case CMD_TEST:
            if (last_substitution) {
                last_substitution = 0;
                pc = command->branch_target;
                continue;
            }
            last_substitution = 0;
            break;
        case CMD_TEST_NOT:
            if (!last_substitution) {
                last_substitution = 0;
                pc = command->branch_target;
                continue;
            }
            last_substitution = 0;
            break;
        case CMD_NEXT:
            if (!quiet_mode) output_record(pattern, *terminated);
            if (appended_used) {
                emit_text(appended, 0);
                appended_used = 0;
                appended[0] = 0;
            }
            if (!input_read_record(pattern, terminated)) {
                quit_global = 1;
                return 1;
            }
            last_substitution = 0;
            break;
        case CMD_APPEND_NEXT: {
            char next[MAX_RECORD];
            int next_term = 0;
            if (!input_read_record(next, &next_term)) {
                if (!quiet_mode) output_record(pattern, *terminated);
                quit_global = 1;
                return 1;
            }
            {
                int n = text_length(pattern);
                if (n + 1 + text_length(next) >= MAX_RECORD) {
                    puts("sed: pattern space too long");
                    error_flag = 1;
                    return 0;
                }
                pattern[n++] = '\n';
                text_copy(pattern + n, next, MAX_RECORD - n);
            }
            *terminated = next_term;
            last_substitution = 0;
            break;
        }
        case CMD_LINE_NUMBER: {
            char number[32];
            sprintf(number, "%lu", line_number);
            emit_text(number, 1);
            break;
        }
        case CMD_LIST:
            list_pattern(pattern, *terminated,
                         command->list_width ? command->list_width :
                         list_width);
            break;
        case CMD_FILENAME:
            emit_text(current_filename, 1);
            break;
        case CMD_ZAP:
            pattern[0] = 0;
            break;
        case CMD_VERSION:
            if (command->text[0] && version_newer(command->text)) {
                puts("sed: expected newer version of sed");
                exit_status = 1;
                return 0;
            }
            break;
        case CMD_EXEC: {
            char executed[MAX_RECORD];
            if (sandbox_mode) {
                puts("sed: e/r/w commands disabled in sandbox mode");
                exit_status = 1;
                return 0;
            }
            if (command->text[0]) {
                if (host_exec_text(command->text, executed, MAX_RECORD))
                    emit_text(executed, 1);
            } else if (host_exec_text(pattern, executed, MAX_RECORD)) {
                text_copy(pattern, executed, MAX_RECORD);
            }
            break;
        }
        default:
            break;
        }
        if (deleted) break;
        pc++;
    }
    if (!deleted && !quiet_mode) output_record(pattern, *terminated);
    if (appended_used) emit_text(appended, 0);
    return 1;
}

static void close_input(void) {
    if (input_stream) fclose(input_stream);
    input_stream = 0;
}

static int open_next_input(void) {
    int index;
    close_input();
    if (input_pos >= input_count) return 0;
    index = input_pos++;
    if (input_preopened[index]) {
        input_stream = input_preopened[index];
        input_preopened[index] = 0;
    } else {
        input_stream = fopen(input_ids[index], "r");
    }
    if (!input_stream) {
        printf("sed: cannot open input %s\n", input_ids[index]);
        exit_status = 2;
        return 0;
    }
    text_copy(current_filename, input_ids[index], MAX_STRING);
    if (separate_files) {
        line_number = 0;
        total_lines = file_counts[index];
        reset_for_file();
    }
    return 1;
}

static int input_read_record(char *out, int *terminated) {
    if (!input_stream && !open_next_input()) return 0;
    for (;;) {
        int c, used = 0, got = 0;
        while ((c = fgetc(input_stream)) != -1) {
            got = 1;
            if (c == record_sep) {
                *terminated = 1;
                break;
            }
#if !defined(CMSED_HOST)
            if (record_sep == '\n' && c == '\r') continue;
#endif
            if (used >= MAX_RECORD - 1) {
                puts("sed: input record too long");
                exit_status = 2;
                error_flag = 1;
                return 0;
            }
            out[used++] = (char)c;
        }
        if (c == -1) {
            *terminated = 0;
            if (!got) {
                if (!open_next_input()) return 0;
                continue;
            }
        }
        out[used] = 0;
        line_number++;
        return 1;
    }
}

static int count_file_records(const char *fileid, unsigned long *count) {
    FILE *file = fopen(fileid, "r");
    int c, used = 0;
    if (!file) return 0;
    while ((c = fgetc(file)) != -1) {
        if (c == record_sep) {
            (*count)++;
            used = 0;
        } else {
#if !defined(CMSED_HOST)
            if (record_sep == '\n' && c == '\r') continue;
#endif
            used++;
            if (used >= MAX_RECORD) {
                fclose(file);
                return 0;
            }
        }
    }
    if (used) (*count)++;
    return fclose(file) == 0;
}

static int run_all(void) {
    char pattern[MAX_RECORD];
    int terminated;
    while (!quit_global) {
        if (!input_read_record(pattern, &terminated)) {
            if (error_flag) return 0;
            break;
        }
        if (!execute_cycle(pattern, &terminated)) return 0;
    }
    return 1;
}

#if !defined(CMSED_HOST)
static int make_file_id(char *out, const char *fn,
                        const char *ft, const char *fm) {
    int i = 0;
    while (*fn && i < 8) out[i++] = *fn++;
    out[i++] = ' ';
    while (*ft && i < 17) out[i++] = *ft++;
    out[i++] = ' ';
    while (*fm && i < 25) out[i++] = *fm++;
    out[i] = 0;
    return i;
}

static int copy_records(FILE *input, FILE *output) {
    int c;
    while ((c = fgetc(input)) != -1)
        if (fputc(c, output) == -1) return 0;
    return 1;
}

static int run_single_file(const char *fileid, FILE *output) {
    input_count = 1;
    input_pos = 0;
    input_preopened[0] = 0;
    text_copy(input_ids[0], fileid, MAX_STRING);
    file_counts[0] = total_lines;
    input_stream = 0;
    output_stream = output;
    if (!run_all()) return 0;
    close_input();
    output_stream = 0;
    return 1;
}

static int cms_in_place(const char *input_id, const char *filemode,
                        int *unused_a, int *unused_b) {
    char temp_id[32], backup_id[32], temp_name[8], backup_name[8];
    FILE *probe, *input, *output, *backup, *staged;
    int serial, ok;
    (void)unused_a;
    (void)unused_b;
    for (serial = 1; serial < 10000; serial++) {
        sprintf(temp_name, "S2T%04d", serial);
        sprintf(backup_name, "S2B%04d", serial);
        make_file_id(temp_id, temp_name, "SEDTMP", filemode);
        make_file_id(backup_id, backup_name, "SEDBAK", filemode);
        probe = fopen(temp_id, "r");
        if (probe) { fclose(probe); continue; }
        probe = fopen(backup_id, "r");
        if (probe) { fclose(probe); continue; }
        break;
    }
    if (serial >= 10000) {
        puts("sed: no unused CMS temporary ids");
        return 0;
    }
    output = fopen(temp_id, "w");
    if (!output) {
        printf("sed: cannot create temporary %s\n", temp_id);
        return 0;
    }
    ok = run_single_file(input_id, output);
    if (fclose(output) != 0) ok = 0;
    if (!ok) {
        remove(temp_id);
        return 0;
    }
    input = fopen(input_id, "r");
    backup = fopen(backup_id, "w");
    if (!input || !backup) {
        if (input) fclose(input);
        if (backup) fclose(backup);
        remove(temp_id);
        printf("sed: cannot preserve backup for %s\n", input_id);
        return 0;
    }
    ok = copy_records(input, backup);
    if (fclose(input) != 0) ok = 0;
    if (fclose(backup) != 0) ok = 0;
    if (!ok) {
        remove(temp_id);
        printf("sed: cannot write backup %s\n", backup_id);
        return 0;
    }
    staged = fopen(temp_id, "r");
    output = fopen(input_id, "w");
    if (!staged || !output) {
        if (staged) fclose(staged);
        if (output) fclose(output);
        printf("sed: cannot replace %s; backup is %s\n",
               input_id, backup_id);
        return 0;
    }
    ok = copy_records(staged, output);
    if (fclose(staged) != 0) ok = 0;
    if (fclose(output) != 0) ok = 0;
    if (!ok) {
        printf("sed: replacement failed; backup is %s\n", backup_id);
        remove(temp_id);
        return 0;
    }
    if (remove(temp_id) != 0)
        printf("sed: temporary retained as %s\n", temp_id);
    printf("sed: original backup kept as %s\n", backup_id);
    return 1;
}
#endif

#if defined(CMSED_HOST)
static int host_in_place(const char *path, const char *suffix) {
    char temp[MAX_STRING];
    FILE *input, *output;
    int ok;
    if (text_length(path) >= MAX_STRING - 8) {
        puts("sed: input path too long for -i");
        return 0;
    }
    sprintf(temp, "%s.sedtmp", path);
    input = fopen(path, "r");
    output = fopen(temp, "w");
    if (!input || !output) {
        if (input) fclose(input);
        if (output) fclose(output);
        remove(temp);
        printf("sed: cannot stage %s\n", path);
        return 0;
    }
    input_count = 1;
    input_pos = 0;
    input_preopened[0] = 0;
    text_copy(input_ids[0], path, MAX_STRING);
    file_counts[0] = total_lines;
    input_preopened[0] = input;
    input_stream = 0;
    output_stream = output;
    ok = run_all();
    if (input_stream) {
        if (fclose(input_stream) != 0) ok = 0;
        input_stream = 0;
    }
    if (fclose(output) != 0) ok = 0;
    output_stream = 0;
    if (!ok) {
        remove(temp);
        return 0;
    }
    if (suffix && suffix[0]) {
        char backup[MAX_STRING];
        sprintf(backup, "%s%s", path, suffix);
        remove(backup);
        if (rename(path, backup) != 0) {
            remove(temp);
            printf("sed: cannot create backup %s\n", backup);
            return 0;
        }
    }
    if (rename(temp, path) != 0) {
        remove(temp);
        printf("sed: cannot replace %s\n", path);
        return 0;
    }
    return 1;
}
#endif

static int usage(void) {
    puts("Usage: sed [-nrszuE] [-e command] [-f script] [script] [file ...]");
    return 1;
}

static void print_help(void) {
    puts("Usage: sed [OPTION]... {script} [input-file]...");
    puts("  -n, --quiet, --silent     suppress automatic printing");
    puts("  -e SCRIPT, --expression=SCRIPT");
    puts("  -f FILE, --file=FILE      read script from FILE (- for stdin)");
    puts("  -i[SUFFIX], --in-place[=SUFFIX]");
    puts("  -l N, --line-length=N     wrap length for the l command");
    puts("  -s, --separate            treat files separately");
    puts("  -z, --null-data           NUL record separator");
    puts("  -E, -r, --regexp-extended extended regular expressions");
    puts("  --posix, --sandbox, --follow-symlinks, --debug");
    puts("  --help, --version");
    puts("Commands: s y d p q Q n N P D = l F z h H g G x");
    puts("          b t T : a i c r R w W e v { }");
}

#if defined(CMSED_HOST)
static int host_main(int argc, char **argv) {
    const char *files[MAX_INPUT_FILES];
    char *suffix = 0;
    FILE *spool = 0;
    int file_count = 0, arg = 1, i, have_script = 0;
    int stdin_needed = 0, stdin_index = -1;
    command_count = 0;
    quiet_mode = 0;
    in_place = 0;
    separate_files = 0;
    nul_mode = 0;
    ere_mode = 0;
    hold_space[0] = 0;
    last_parsed_regex[0] = 0;
    while (arg < argc && argv[arg][0] == '-') {
        if (!strcmp(argv[arg], "--")) { arg++; break; }
        if (!strcmp(argv[arg], "--sandbox")) {
            sandbox_mode = 1;
            arg++;
        } else if (!strcmp(argv[arg], "--posix")) {
            posix_mode = 1;
            arg++;
        } else if (!strcmp(argv[arg], "-u") ||
                   !strcmp(argv[arg], "--follow-symlinks")) {
            arg++;
        } else if (!strcmp(argv[arg], "--debug") ||
                   !strcmp(argv[arg], "--unbuffered") ||
                   !strcmp(argv[arg], "--binary") ||
                   !strcmp(argv[arg], "-b")) {
            arg++;
        } else if (!strcmp(argv[arg], "--quiet") ||
                   !strcmp(argv[arg], "--silent")) {
            quiet_mode = 1;
            arg++;
        } else if (!strcmp(argv[arg], "--null-data")) {
            nul_mode = 1;
            arg++;
        } else if (!strcmp(argv[arg], "--separate")) {
            separate_files = 1;
            arg++;
        } else if (!strcmp(argv[arg], "--regexp-extended")) {
            ere_mode = 1;
            arg++;
        } else if (!strncmp(argv[arg], "--expression=", 13)) {
            if (!load_script_string(argv[arg] + 13)) {
                puts("sed: invalid -e script");
                return 1;
            }
            have_script = 1;
            arg++;
        } else if (!strcmp(argv[arg], "--expression")) {
            if (++arg >= argc || !load_script_string(argv[arg])) {
                puts("sed: invalid -e script");
                return 1;
            }
            have_script = 1;
            arg++;
        } else if (!strncmp(argv[arg], "--file=", 7)) {
            if (!load_script(argv[arg] + 7)) {
                puts("sed: cannot read -f script");
                return script_read_error ? 4 : 1;
            }
            have_script = 1;
            arg++;
        } else if (!strcmp(argv[arg], "--file")) {
            if (++arg >= argc) return usage();
            if (!strcmp(argv[arg], "-")) {
                if (!load_script_stream(stdin)) return 1;
            } else if (!load_script(argv[arg])) {
                puts("sed: cannot read -f script");
                return script_read_error ? 4 : 1;
            }
            have_script = 1;
            arg++;
        } else if (!strncmp(argv[arg], "--in-place=", 11)) {
            in_place = 1;
            suffix = argv[arg] + 11;
            arg++;
        } else if (!strcmp(argv[arg], "--in-place")) {
            in_place = 1;
            suffix = "";
            arg++;
        } else if (!strncmp(argv[arg], "--line-length=", 14)) {
            int width = parse_uint(argv[arg] + 14);
            if (width < 1) return usage();
            list_width = width;
            arg++;
        } else if (!strcmp(argv[arg], "--line-length")) {
            int width;
            if (++arg >= argc) return usage();
            width = parse_uint(argv[arg]);
            if (width < 1) return usage();
            list_width = width;
            arg++;
        } else if (!strcmp(argv[arg], "--help")) {
            print_help();
            return 0;
        } else if (!strcmp(argv[arg], "--version")) {
            puts("CMSED 0.4");
            return 0;
        } else if (!strcmp(argv[arg], "-n")) {
            quiet_mode = 1;
            arg++;
        } else if (!strcmp(argv[arg], "-s")) {
            separate_files = 1;
            arg++;
        } else if (!strcmp(argv[arg], "-z")) {
            nul_mode = 1;
            arg++;
        } else if (!strcmp(argv[arg], "-E") || !strcmp(argv[arg], "-r")) {
            ere_mode = 1;
            arg++;
        } else if (!strcmp(argv[arg], "-l") ||
                   (argv[arg][0] == '-' && argv[arg][1] == 'l' &&
                    argv[arg][2])) {
            int width;
            if (argv[arg][2]) width = parse_uint(argv[arg] + 2);
            else {
                if (++arg >= argc) return usage();
                width = parse_uint(argv[arg]);
            }
            if (width < 1) return usage();
            list_width = width;
            arg++;
        } else if (argv[arg][1] == 'i') {
            in_place = 1;
            suffix = argv[arg] + 2;
            arg++;
        } else if (!strcmp(argv[arg], "-e")) {
            if (++arg >= argc || !load_script_string(argv[arg])) {
                puts("sed: invalid -e script");
                return 1;
            }
            have_script = 1;
            arg++;
        } else if (!strcmp(argv[arg], "-f")) {
            if (++arg >= argc) return usage();
            if (!strcmp(argv[arg], "-")) {
                if (!load_script_stream(stdin)) return 1;
            } else if (!load_script(argv[arg])) {
                puts("sed: cannot read -f script");
                return script_read_error ? 4 : 1;
            }
            have_script = 1;
            arg++;
        } else {
            printf("sed: unsupported option %s\n", argv[arg]);
            return 1;
        }
    }
    if (!have_script) {
        if (arg >= argc) {
            puts("sed: no script supplied");
            return 1;
        }
        if (!load_script(argv[arg++])) {
            if (script_read_error) {
                puts("sed: cannot read script");
                return 4;
            }
            return 1;
        }
    }
    while (arg < argc) {
        if (file_count >= MAX_INPUT_FILES) {
            puts("sed: too many input files");
            return 4;
        }
        files[file_count++] = argv[arg++];
    }
    if (!file_count) files[file_count++] = "-";
    for (i = 0; i < file_count; i++)
        if (!strcmp(files[i], "-")) stdin_needed = 1;
    if (in_place && stdin_needed) {
        puts("sed: -i cannot edit standard input");
        return 4;
    }
    if (!resolve_branches()) {
        puts("sed: undefined branch label or unmatched block");
        return 4;
    }
    record_sep = nul_mode ? 0 : '\n';
    if (separate_files) {
        for (i = 0; i < file_count; i++) {
            if (!strcmp(files[i], "-")) {
                puts("sed: -s requires named input files");
                return 4;
            }
            if (!count_file_records(files[i], &file_counts[i])) {
                printf("sed: cannot read %s\n", files[i]);
                return 2;
            }
        }
    } else {
        unsigned long sum = 0;
        for (i = 0; i < file_count; i++) {
            if (!strcmp(files[i], "-")) continue;
            if (!count_file_records(files[i], &file_counts[i])) {
                printf("sed: cannot read %s\n", files[i]);
                return 2;
            }
            sum += file_counts[i];
        }
        total_lines = sum;
    }
    if (stdin_needed) {
        unsigned long count = 0;
        int c, used = 0;
        spool = tmpfile();
        if (!spool) {
            puts("sed: cannot spool standard input");
            return 8;
        }
        while ((c = fgetc(stdin)) != -1) {
            fputc(c, spool);
            if (c == record_sep) { count++; used = 0; }
#if defined(CMSED_HOST)
            else used++;
#else
            else if (!(record_sep == '\n' && c == '\r')) used++;
#endif
        }
        if (used) count++;
        rewind(spool);
        total_lines += count;
        for (i = 0; i < file_count; i++)
            if (!strcmp(files[i], "-")) {
                stdin_index = i;
                break;
            }
    }
    input_count = file_count;
    input_pos = 0;
    for (i = 0; i < file_count; i++) {
        input_preopened[i] = 0;
        text_copy(input_ids[i], files[i], MAX_STRING);
    }
    if (stdin_index >= 0) {
        input_preopened[stdin_index] = spool;
        file_counts[stdin_index] =
            separate_files ? 0 : 0;
    }
    if (!prepare_write_files()) {
        close_write_files();
        if (spool) fclose(spool);
        return exit_status ? exit_status : 4;
    }
    if (!in_place) {
        if (!run_all()) {
            close_write_files();
            if (spool) fclose(spool);
            return exit_status ? exit_status : 8;
        }
    } else {
        for (i = 0; i < file_count; i++) {
            if (!host_in_place(files[i], suffix)) {
                close_write_files();
                return 8;
            }
            if (quit_global) break;
        }
    }
    close_write_files();
    if (spool) fclose(spool);
    return exit_status ? exit_status : (error_flag ? 8 : 0);
}
#endif

int main(int argc, char **argv) {
#if defined(CMSED_HOST)
    return host_main(argc, argv);
#else
    char script_id[32], input_id[32];
    int arg, i, have_script = 0;
    command_count = 0;
    quiet_mode = 0;
    in_place = 0;
    separate_files = 0;
    nul_mode = 0;
    ere_mode = 0;
    hold_space[0] = 0;
    last_parsed_regex[0] = 0;
    arg = 1;
    while (arg < argc && argv[arg][0] == '-') {
        if (!argv[arg][1] || (argv[arg][1] == '-' && !argv[arg][2])) {
            arg++;
            break;
        }
        if (!strcmp(argv[arg], "--help")) {
            print_help();
            return 0;
        } else if (!strcmp(argv[arg], "--version")) {
            puts("CMSED 0.4");
            return 0;
        } else if (!strcmp(argv[arg], "--sandbox")) {
            sandbox_mode = 1;
            arg++;
        } else if (!strcmp(argv[arg], "--posix")) {
            posix_mode = 1;
            arg++;
        } else if (!strcmp(argv[arg], "--quiet") ||
                   !strcmp(argv[arg], "--silent")) {
            quiet_mode = 1;
            arg++;
        } else if (!strcmp(argv[arg], "--null-data")) {
            nul_mode = 1;
            arg++;
        } else if (!strcmp(argv[arg], "--separate")) {
            separate_files = 1;
            arg++;
        } else if (!strcmp(argv[arg], "--regexp-extended")) {
            ere_mode = 1;
            arg++;
        } else if (!strcmp(argv[arg], "--in-place")) {
            in_place = 1;
            arg++;
        } else if (!strncmp(argv[arg], "--line-length=", 14)) {
            int width = parse_uint(argv[arg] + 14);
            if (width < 1) return usage();
            list_width = width;
            arg++;
        } else if (!strcmp(argv[arg], "--unbuffered") ||
                   !strcmp(argv[arg], "--binary") ||
                   !strcmp(argv[arg], "--debug") ||
                   !strcmp(argv[arg], "--follow-symlinks")) {
            arg++;
        } else if (argv[arg][1] == 'l') {
            int width;
            if (argv[arg][2]) width = parse_uint(argv[arg] + 2);
            else {
                if (++arg >= argc) return usage();
                width = parse_uint(argv[arg]);
            }
            if (width < 1) return usage();
            list_width = width;
            arg++;
        } else if (!argv[arg][1] || argv[arg][1] == 'n') {
            quiet_mode = 1;
            arg++;
        } else if (argv[arg][1] == 's') {
            separate_files = 1;
            arg++;
        } else if (argv[arg][1] == 'z') {
            nul_mode = 1;
            arg++;
        } else if (argv[arg][1] == 'E' || argv[arg][1] == 'r') {
            ere_mode = 1;
            arg++;
        } else if (argv[arg][1] == 'i') {
            in_place = 1;
            arg++;
        } else if (argv[arg][1] == 'e' && !argv[arg][2]) {
            if (++arg >= argc || !load_script_string(argv[arg])) {
                puts("sed: invalid -e script");
                return 1;
            }
            have_script = 1;
            arg++;
        } else if (argv[arg][1] == 'f' && !argv[arg][2]) {
            if (arg + 3 >= argc) return usage();
            make_file_id(script_id, argv[arg + 1], argv[arg + 2],
                         argv[arg + 3]);
            if (!load_script(script_id)) {
                printf("sed: cannot read script %s\n", script_id);
                return script_read_error ? 4 : 1;
            }
            have_script = 1;
            arg += 4;
        } else {
            printf("sed: unsupported option %s\n", argv[arg]);
            return 1;
        }
    }
    if (!have_script) {
        if (arg + 2 >= argc) return usage();
        make_file_id(script_id, argv[arg], argv[arg + 1], argv[arg + 2]);
        if (!load_script(script_id)) {
            puts("sed: cannot read script");
            return script_read_error ? 4 : 1;
        }
        arg += 3;
    }
    if ((argc - arg) < 3 || (argc - arg) % 3 != 0) {
        puts("sed: input file ids must be fn ft fm triples");
        return 1;
    }
    input_count = (argc - arg) / 3;
    if (input_count > MAX_INPUT_FILES) {
        puts("sed: too many input files");
        return 4;
    }
    if (!resolve_branches()) {
        puts("sed: undefined branch label or unmatched block");
        return 4;
    }
    record_sep = nul_mode ? 0 : '\n';
    if (separate_files) {
        for (i = 0; i < input_count; i++) {
            int a = arg + i * 3;
            make_file_id(input_id, argv[a], argv[a + 1], argv[a + 2]);
            file_counts[i] = 0;
            if (!count_file_records(input_id, &file_counts[i])) {
                printf("sed: cannot count input %s\n", input_id);
                return 8;
            }
        }
    } else {
        total_lines = 0;
        for (i = 0; i < input_count; i++) {
            int a = arg + i * 3;
            make_file_id(input_id, argv[a], argv[a + 1], argv[a + 2]);
            file_counts[i] = 0;
            if (!count_file_records(input_id, &file_counts[i])) {
                printf("sed: cannot count input %s\n", input_id);
                return 8;
            }
            total_lines += file_counts[i];
        }
    }
    for (i = 0; i < input_count; i++) {
        int a = arg + i * 3;
        input_preopened[i] = 0;
        make_file_id(input_ids[i], argv[a], argv[a + 1], argv[a + 2]);
    }
    if (!prepare_write_files()) {
        close_write_files();
        return exit_status ? exit_status : 4;
    }
    if (!in_place) {
        if (!run_all()) {
            close_write_files();
            return exit_status ? exit_status : 8;
        }
    } else {
        for (i = 0; i < input_count; i++) {
            int a = arg + i * 3;
            if (!cms_in_place(input_ids[i], argv[a + 2], 0, 0)) {
                close_write_files();
                return 8;
            }
            if (quit_global) break;
        }
    }
    close_write_files();
    return exit_status ? exit_status : (error_flag ? 8 : 0);
#endif
}
