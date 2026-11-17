/* CMSAWK 0.7: C89 AWK interpreter for GCCCMS/PDPCLIB. */
/* Adds exponentiation and regex literals in expression position. */
/* printf numeric zero padding is supplied when PDPCLIB omits it. */
/* Command pipes require POPEN/PCLOSE, absent from this PDPCLIB runtime. */
/* Fixed tables and strings are bounded for CMS memory. */
typedef struct cms_file FILE;
extern FILE *fopen(const char *, const char *);
extern char *fgets(char *, int, FILE *);
extern int fclose(FILE *);
extern int puts(const char *);
extern int printf(const char *, ...);
extern int sprintf(char *, const char *, ...);
extern int fputs(const char *, FILE *);
extern int fflush(FILE *);
extern int fseek(FILE *, long, int);
extern int system(const char *);

enum {
    SOURCE_SIZE = 16384, MAX_RULES = 64, MAX_FUNCS = 24,
    MAX_VARS = 64, MAX_ARRAYS = 32, MAX_ITEMS = 64,
    MAX_STRING = 128, MAX_KEY = 64, MAX_RECORD = 1024,
    MAX_FIELDS = 64, MAX_PARAMS = 16, MAX_FRAMES = 12, MAX_IO = 8,
    MAX_INPUT_FILES = 16,
    MAX_APPEND_COPY = 65536,
    MAX_RX_NODES = 256, MAX_RX_CODE = 512,
    MAX_RX_STACK = MAX_RECORD + 16, MAX_RX_GROUPS = 9,
    TOK_ID = 256, TOK_NUM, TOK_STR, TOK_REGEX, TOK_SEMI,
    TOK_EQ, TOK_NE, TOK_LE, TOK_GE, TOK_AND, TOK_OR,
    TOK_INC, TOK_DEC, TOK_ADD_EQ, TOK_SUB_EQ, TOK_MUL_EQ,
    TOK_DIV_EQ, TOK_MOD_EQ, TOK_MATCH, TOK_NMATCH, TOK_APPEND, TOK_IN,
    CMS_SEEK_END = 2,
    V_EMPTY = 0, V_NUM, V_STR, V_ARRAY,
    RULE_ALL = 0, RULE_REGEX = 1, RULE_EXPR = 2,
    RULE_BEGIN = 3, RULE_END = 4,
    FLOW_NONE = 0, FLOW_BREAK, FLOW_CONTINUE, FLOW_NEXT,
    FLOW_EXIT, FLOW_RETURN
};

enum {
    RX_EMPTY = 1, RX_CHAR, RX_ANY, RX_CLASS, RX_BOL, RX_EOL,
    RX_BACKREF, RX_SEQ, RX_ALT, RX_GROUP, RX_STAR, RX_PLUS,
    RX_OPTIONAL, RX_RANGE,
    RXI_CHAR = 1, RXI_ANY, RXI_CLASS, RXI_BOL, RXI_EOL,
    RXI_BACKREF, RXI_SPLIT, RXI_SAVE_START, RXI_SAVE_END, RXI_MATCH
};

typedef struct {
    int kind;
    double number;
    char text[MAX_STRING];
    int array_id;
    int ref_kind;
    int ref_index;
    int ref_entry;
} Value;

typedef struct {
    int used;
    char key[MAX_KEY];
    Value value;
} ArrayItem;

typedef struct {
    int used;
    int count;
    ArrayItem item[MAX_ITEMS];
} AwkArray;

typedef struct {
    int used;
    char name[MAX_STRING];
    int array_id;
    Value value;
    int alias_kind;
    int alias_index;
} AwkVar;

typedef struct {
    int kind;
    int pattern_start;
    int body_start;
    int body_end;
    char pattern[MAX_STRING];
} AwkRule;

typedef struct {
    int used;
    char name[MAX_STRING];
    int param_count;
    char param[MAX_PARAMS][MAX_STRING];
    int body_start;
    int body_end;
} AwkFunction;

typedef struct {
    int kind;
    int start;
    int end;
    double number;
    char text[MAX_STRING];
} Token;

typedef struct {
    int pos;
    Token token;
    int regex_next;
} ParserState;

typedef struct {
    AwkVar var[MAX_PARAMS];
    int count;
    int flow;
    Value result;
} CallFrame;

typedef struct {
    int kind;
    int left;
    int right;
    int value;
    int minimum;
    int maximum;
} RxNode;

typedef struct {
    int op;
    int x;
    int y;
    int value;
} RxInstruction;

typedef struct {
    int pc;
    int pos;
    int start[MAX_RX_GROUPS + 1];
    int end[MAX_RX_GROUPS + 1];
} RxState;

static char source[SOURCE_SIZE];
static int source_length;
static unsigned char newline_sep[SOURCE_SIZE];
static int source_pos;
static Token token;
static int regex_next;
static AwkRule rules[MAX_RULES];
static int rule_count;
static AwkFunction functions[MAX_FUNCS];
static int function_count;
static AwkVar globals[MAX_VARS];
static int global_count;
static AwkArray arrays[MAX_ARRAYS];
static int array_count;
static CallFrame frames[MAX_FRAMES];
static int frame_depth;
static int flow_state;
static unsigned long nr;
static unsigned long fnr;
static int nf;
static int field_start[MAX_FIELDS];
static int field_length[MAX_FIELDS];
static char field_text[MAX_FIELDS][MAX_STRING];
static char record[MAX_RECORD];
static int record_length;
static int error_flag;
static int execute_enabled = 1;
static int print_context;
static int regex_icase;
static unsigned long random_seed = 1UL;
static FILE *data_stream;
static int input_index;
static FILE *io_stream[MAX_IO];
static char io_name[MAX_IO][MAX_STRING];
static char io_mode[MAX_IO];
static char append_copy[MAX_APPEND_COPY];
static RxNode rx_nodes[MAX_RX_NODES];
static RxInstruction rx_code[MAX_RX_CODE];
static RxState rx_stack[MAX_RX_STACK];
static char rx_pattern[MAX_STRING];
static int rx_node_count;
static int rx_code_count;
static int rx_parse_pos;
static int rx_group_count;
static int rx_parse_error;
static int rx_capture_start[MAX_RX_GROUPS + 1];
static int rx_capture_end[MAX_RX_GROUPS + 1];
static void format_output(const char *, Value *, int, char *, int);
static int assign_field(int, Value);
static int assign_nf(Value);
static void split_fields(void);
static int next_main_line(char *);
static void set_global(const char *, Value);

static int slen(const char *s) {
    int n = 0;
    while (s[n]) n++;
    return n;
}

static void scopy(char *to, const char *from, int limit) {
    int i = 0;
    while (from[i] && i < limit - 1) {
        to[i] = from[i];
        i++;
    }
    to[i] = 0;
}

static int seq(const char *a, const char *b) {
    int i = 0;
    while (a[i] && b[i] && a[i] == b[i]) i++;
    return a[i] == 0 && b[i] == 0;
}

static FILE *open_append_copy(const char *);

static FILE *open_io(const char *name, char mode) {
    int i, free_slot = -1;
    const char *access = mode == 'r' ? "r" : mode == 'a' ? "a" : "w";
    for (i = 0; i < MAX_IO; i++) {
        if (!io_stream[i]) {
            if (free_slot < 0) free_slot = i;
            continue;
        }
        if (seq(io_name[i], name)) return io_stream[i];
    }
    if (free_slot < 0) {
        error_flag = 1;
        return 0;
    }
    io_stream[free_slot] = mode == 'a' ? fopen(name, "a") :
                                          fopen(name, access);
    if (!io_stream[free_slot] && mode == 'a') {
        FILE *probe = fopen(name, "r+");
        if (probe) {
            if (fseek(probe, 0L, CMS_SEEK_END) == 0)
                io_stream[free_slot] = probe;
            else fclose(probe);
        }
        if (!io_stream[free_slot])
            io_stream[free_slot] = open_append_copy(name);
    }
    if (!io_stream[free_slot]) return 0;
    scopy(io_name[free_slot], name, MAX_STRING);
    io_mode[free_slot] = mode;
    return io_stream[free_slot];
}

static int close_io(const char *name) {
    int i, found = 0, rc = 0;
    for (i = 0; i < MAX_IO; i++) {
        if (io_stream[i] && seq(io_name[i], name)) {
            fflush(io_stream[i]);
            if (fclose(io_stream[i]) != 0) rc = -1;
            io_stream[i] = 0;
            io_name[i][0] = 0;
            io_mode[i] = 0;
            found = 1;
        }
    }
    return found ? rc : -1;
}

static void close_all_io(void) {
    int i;
    for (i = 0; i < MAX_IO; i++) {
        if (io_stream[i]) {
            fflush(io_stream[i]);
            fclose(io_stream[i]);
            io_stream[i] = 0;
        }
    }
}

static FILE *open_append_copy(const char *name) {
    FILE *input, *output;
    char line[MAX_RECORD];
    int used = 0, i, n;
    input = fopen(name, "r");
    if (!input) return fopen(name, "w");
    while (fgets(line, sizeof line, input)) {
        n = slen(line);
        if (used + n >= MAX_APPEND_COPY) {
            fclose(input);
            error_flag = 1;
            return 0;
        }
        for (i = 0; i < n; i++) append_copy[used++] = line[i];
    }
    if (fclose(input) != 0) return 0;
    append_copy[used] = 0;
    output = fopen(name, "w");
    if (!output) return 0;
    if (used && fputs(append_copy, output) < 0) {
        fclose(output);
        return 0;
    }
    return output;
}

static int is_space(char c) {
    return c == ' ' || c == '\t' || c == '\r' || c == '\n' ||
           c == '\v' || c == '\f';
}

static int is_alpha(char c) {
    return (c >= 'A' && c <= 'I') || (c >= 'J' && c <= 'R') ||
           (c >= 'S' && c <= 'Z') || (c >= 'a' && c <= 'i') ||
           (c >= 'j' && c <= 'r') || (c >= 's' && c <= 'z');
}

static int is_digit(char c) {
    return c >= '0' && c <= '9';
}

static void token_text(Token *t, const char *s, int n) {
    int i;
    if (n >= MAX_STRING) n = MAX_STRING - 1;
    for (i = 0; i < n; i++) t->text[i] = s[i];
    t->text[n] = 0;
}

static void lex_next(void) {
    int start, n;
    char c;
    while (source_pos < source_length) {
        c = source[source_pos];
        if (c == '\n') {
            if (!newline_sep[source_pos]) {
                source_pos++;
                continue;
            }
            break;
        }
        if (is_space(c)) {
            source_pos++;
            continue;
        }
        if (c == '#') {
            while (source_pos < source_length &&
                   source[source_pos] != '\n') source_pos++;
            continue;
        }
        break;
    }
    token.start = source_pos;
    token.text[0] = 0;
    token.number = 0;
    if (source_pos >= source_length) {
        token.kind = 0;
        token.end = source_pos;
        return;
    }
    c = source[source_pos++];
    if (c == '\n' || c == ';') {
        while (source_pos < source_length &&
               (source[source_pos] == '\n' || source[source_pos] == ';'))
            source_pos++;
        token.kind = TOK_SEMI;
        token.end = source_pos;
        return;
    }
    if (regex_next && c == '/') {
        int escaped = 0;
        start = source_pos;
        while (source_pos < source_length) {
            c = source[source_pos++];
            if (!escaped && c == '/') break;
            if (escaped) escaped = 0;
            else if (c == '\\') escaped = 1;
        }
        token.kind = TOK_REGEX;
        token_text(&token, source + start, source_pos - start - 1);
        regex_next = 0;
        token.end = source_pos;
        return;
    }
    regex_next = 0;
    if (is_alpha(c) || c == '_') {
        start = source_pos - 1;
        while (source_pos < source_length &&
               (is_alpha(source[source_pos]) || is_digit(source[source_pos]) ||
                source[source_pos] == '_')) source_pos++;
        n = source_pos - start;
        token.kind = TOK_ID;
        token_text(&token, source + start, n);
        if (seq(token.text, "in")) token.kind = TOK_IN;
        token.end = source_pos;
        return;
    }
    if (is_digit(c) || (c == '.' && is_digit(source[source_pos]))) {
        double value = 0;
        double place = 0.1;
        int exponent = 0, exponent_sign = 1;
        int fraction = 0;
        start = source_pos - 1;
        if (c != '.') value = c - '0';
        else fraction = 1;
        while (source_pos < source_length) {
            c = source[source_pos];
            if (is_digit(c)) {
                source_pos++;
                if (fraction) {
                    value += (c - '0') * place;
                    place *= 0.1;
                } else value = value * 10 + (c - '0');
            } else if (c == '.' && !fraction) {
                fraction = 1;
                source_pos++;
            } else break;
        }
        if (source_pos < source_length &&
            (source[source_pos] == 'e' || source[source_pos] == 'E')) {
            source_pos++;
            if (source_pos < source_length &&
                (source[source_pos] == '+' || source[source_pos] == '-')) {
                if (source[source_pos] == '-') exponent_sign = -1;
                source_pos++;
            }
            while (source_pos < source_length &&
                   is_digit(source[source_pos]) && exponent < 100) {
                exponent = exponent * 10 + source[source_pos++] - '0';
            }
            while (exponent-- > 0) {
                if (exponent_sign > 0) value *= 10;
                else value /= 10;
            }
        }
        token.kind = TOK_NUM;
        token.number = value;
        token_text(&token, source + start, source_pos - start);
        token.end = source_pos;
        return;
    }
    if (c == '"') {
        n = 0;
        while (source_pos < source_length) {
            c = source[source_pos++];
            if (c == '"') break;
            if (c == '\\' && source_pos < source_length) {
                c = source[source_pos++];
                if (c == 'n') c = '\n';
                else if (c == 't') c = '\t';
                else if (c != '\\' && c != '"') {
                    error_flag = 1;
                    break;
                }
            }
            if (n < MAX_STRING - 1) token.text[n++] = c;
        }
        token.text[n] = 0;
        token.kind = TOK_STR;
        token.end = source_pos;
        return;
    }
    token.kind = (unsigned char)c;
    if (source_pos < source_length) {
        char d = source[source_pos];
        if (c == '=' && d == '=') token.kind = TOK_EQ;
        else if (c == '!' && d == '=') token.kind = TOK_NE;
        else if (c == '<' && d == '=') token.kind = TOK_LE;
        else if (c == '>' && d == '=') token.kind = TOK_GE;
        else if (c == '&' && d == '&') token.kind = TOK_AND;
        else if (c == '|' && d == '|') token.kind = TOK_OR;
        else if (c == '+' && d == '+') token.kind = TOK_INC;
        else if (c == '-' && d == '-') token.kind = TOK_DEC;
        else if (c == '+' && d == '=') token.kind = TOK_ADD_EQ;
        else if (c == '-' && d == '=') token.kind = TOK_SUB_EQ;
        else if (c == '*' && d == '=') token.kind = TOK_MUL_EQ;
        else if (c == '/' && d == '=') token.kind = TOK_DIV_EQ;
        else if (c == '%' && d == '=') token.kind = TOK_MOD_EQ;
        else if (c == '!' && d == '~') token.kind = TOK_NMATCH;
        else if (c == '~') token.kind = TOK_MATCH;
        else if (c == '>' && d == '>') token.kind = TOK_APPEND;
        if (token.kind != (unsigned char)c) source_pos++;
    }
    if (token.kind == TOK_MATCH || token.kind == TOK_NMATCH) regex_next = 1;
    token.end = source_pos;
}

static ParserState save_parser(void) {
    ParserState s;
    s.pos = source_pos;
    s.token = token;
    s.regex_next = regex_next;
    return s;
}

static void restore_parser(ParserState s) {
    source_pos = s.pos;
    token = s.token;
    regex_next = s.regex_next;
}

static void set_parser(int pos) {
    source_pos = pos;
    regex_next = 0;
    lex_next();
}

static int accept(int kind) {
    if (token.kind != kind) return 0;
    lex_next();
    return 1;
}

static int require(int kind) {
    if (accept(kind)) return 1;
    error_flag = 1;
    return 0;
}

static void skip_semis(void) {
    while (accept(TOK_SEMI)) {}
}

/* A newline ends a statement unless it follows a token that cannot end one
   (an operator, a comma, an opening brace) or sits inside parentheses or
   brackets.  The interpreter replays the lexer for every rule, so the
   decision is precomputed once per load instead of tracked as lexer state. */
static int statement_continues(int k) {
    switch (k) {
    case 0: case '{': case '(': case '[': case ',': case ';': case TOK_SEMI:
    case '=': case TOK_EQ: case TOK_NE: case '<': case '>': case TOK_LE:
    case TOK_GE: case TOK_AND: case TOK_OR: case TOK_MATCH: case TOK_NMATCH:
    case TOK_IN: case TOK_APPEND: case TOK_ADD_EQ: case TOK_SUB_EQ:
    case TOK_MUL_EQ: case TOK_DIV_EQ: case TOK_MOD_EQ: case '+': case '-':
    case '*': case '/': case '%': case '!': case '?': case ':': case '&':
    case '|': case '~':
        return 1;
    }
    return 0;
}

static void classify_newlines(void) {
    int i, depth = 0, prev = 0, prev_end = 0;
    for (i = 0; i < SOURCE_SIZE; i++) newline_sep[i] = 0;
    source_pos = 0;
    token.kind = 0;
    regex_next = 0;
    lex_next();
    while (token.kind) {
        for (i = prev_end; i < token.start; i++)
            if (source[i] == '\n')
                newline_sep[i] =
                    (unsigned char)(depth == 0 && !statement_continues(prev));
        if (token.kind == '(' || token.kind == '[') depth++;
        else if ((token.kind == ')' || token.kind == ']') && depth > 0) depth--;
        prev = token.kind;
        prev_end = token.end;
        lex_next();
    }
    for (i = prev_end; i < source_length; i++)
        if (source[i] == '\n')
            newline_sep[i] =
                (unsigned char)(depth == 0 && !statement_continues(prev));
}

static Value empty_value(void) {
    Value v;
    int i;
    v.kind = V_EMPTY;
    v.number = 0;
    v.text[0] = 0;
    v.array_id = -1;
    v.ref_kind = 0;
    v.ref_index = -1;
    v.ref_entry = -1;
    for (i = 1; i < MAX_STRING; i++) v.text[i] = 0;
    return v;
}

static Value number_value(double n) {
    Value v = empty_value();
    v.kind = V_NUM;
    v.number = n;
    return v;
}

static Value string_value(const char *s) {
    Value v = empty_value();
    v.kind = V_STR;
    scopy(v.text, s, MAX_STRING);
    return v;
}

static int number_string(const char *s, double *out) {
    int i = 0, sign = 1, digits = 0;
    int exponent = 0, exponent_sign = 1;
    double n = 0, place = 0.1;
    while (is_space(s[i])) i++;
    if (s[i] == '-') { sign = -1; i++; }
    else if (s[i] == '+') i++;
    while (is_digit(s[i])) {
        digits = 1;
        n = n * 10 + s[i++] - '0';
    }
    if (s[i] == '.') {
        i++;
        while (is_digit(s[i])) {
            digits = 1;
            n += (s[i++] - '0') * place;
            place *= 0.1;
        }
    }
    if (s[i] == 'e' || s[i] == 'E') {
        i++;
        if (s[i] == '-') { exponent_sign = -1; i++; }
        else if (s[i] == '+') i++;
        if (!is_digit(s[i])) return 0;
        while (is_digit(s[i]) && exponent < 100)
            exponent = exponent * 10 + s[i++] - '0';
        while (exponent-- > 0) {
            if (exponent_sign > 0) n *= 10;
            else n /= 10;
        }
    }
    while (is_space(s[i])) i++;
    if (!digits || s[i]) return 0;
    *out = sign * n;
    return 1;
}

static double as_number(Value v) {
    double n;
    if (v.kind == V_NUM) return v.number;
    if (v.kind == V_STR && number_string(v.text, &n)) return n;
    return 0;
}

static void as_string(Value v, char *out) {
    if (v.kind == V_STR || v.kind == V_EMPTY) scopy(out, v.text, MAX_STRING);
    else if (v.kind == V_NUM) sprintf(out, "%.10g", v.number);
    else scopy(out, "", MAX_STRING);
}

static int truth(Value v) {
    if (v.kind == V_EMPTY) return 0;
    if (v.kind == V_STR) return v.text[0] != 0;
    if (v.kind == V_ARRAY) return 1;
    return v.number != 0;
}

static int find_global(const char *name, int create) {
    int i;
    for (i = 0; i < global_count; i++)
        if (seq(globals[i].name, name)) return i;
    if (!create || global_count >= MAX_VARS) return -1;
    i = global_count++;
    globals[i].used = 1;
    scopy(globals[i].name, name, MAX_STRING);
    globals[i].array_id = -1;
    globals[i].value = empty_value();
    globals[i].alias_kind = 0;
    globals[i].alias_index = -1;
    return i;
}

static int find_local(const char *name, int create) {
    int i;
    CallFrame *f;
    if (frame_depth <= 0) return -1;
    f = &frames[frame_depth - 1];
    for (i = 0; i < f->count; i++)
        if (seq(f->var[i].name, name)) return i;
    if (!create || f->count >= MAX_PARAMS) return -1;
    i = f->count++;
    f->var[i].used = 1;
    scopy(f->var[i].name, name, MAX_STRING);
    f->var[i].array_id = -1;
    f->var[i].value = empty_value();
    f->var[i].alias_kind = 0;
    f->var[i].alias_index = -1;
    return i;
}

static AwkVar *resolve_var(const char *name, int create,
                           int *scope, int *index) {
    int i;
    if (frame_depth > 0) {
        i = find_local(name, 0);
        if (i >= 0) {
            *scope = frame_depth;
            *index = i;
            return &frames[frame_depth - 1].var[i];
        }
    }
    i = find_global(name, create);
    if (i < 0) return 0;
    *scope = 0;
    *index = i;
    return &globals[i];
}

static AwkVar *ref_var(int scope, int index) {
    if (scope > 0 && scope <= frame_depth)
        return &frames[scope - 1].var[index];
    if (scope == 0 && index >= 0 && index < global_count)
        return &globals[index];
    return 0;
}

static int new_array(void) {
    int i;
    if (array_count >= MAX_ARRAYS) return -1;
    i = array_count++;
    arrays[i].used = 1;
    arrays[i].count = 0;
    return i;
}

static int ensure_array(AwkVar *v) {
    if (v->array_id >= 0) return v->array_id;
    if (v->alias_kind) {
        AwkVar *alias = ref_var(v->alias_kind == 2 ?
                               frame_depth - 1 : 0, v->alias_index);
        if (alias && alias->array_id >= 0) {
            v->array_id = alias->array_id;
            return v->array_id;
        }
        if (alias) {
            alias->array_id = new_array();
            v->array_id = alias->array_id;
            return v->array_id;
        }
    }
    v->array_id = new_array();
    return v->array_id;
}

static int array_item(int aid, const char *key, int create) {
    int i;
    int free_slot = -1;
    if (aid < 0 || aid >= array_count) return -1;
    for (i = 0; i < arrays[aid].count; i++) {
        if (arrays[aid].item[i].used &&
            seq(arrays[aid].item[i].key, key)) return i;
        if (!arrays[aid].item[i].used && free_slot < 0) free_slot = i;
    }
    if (!create) return -1;
    if (free_slot >= 0) i = free_slot;
    else {
        if (arrays[aid].count >= MAX_ITEMS) return -1;
        i = arrays[aid].count++;
    }
    arrays[aid].item[i].used = 1;
    scopy(arrays[aid].item[i].key, key, MAX_KEY);
    arrays[aid].item[i].value = empty_value();
    return i;
}

static int ref_kind_array(void) {
    return 2;
}

static Value get_variable(const char *name) {
    Value v = empty_value();
    AwkVar *var;
    int scope, index;
    var = resolve_var(name, 1, &scope, &index);
    if (!var) {
        error_flag = 1;
        return v;
    }
    v = var->array_id >= 0 ? empty_value() : var->value;
    v.ref_kind = 1;
    v.ref_index = index;
    v.ref_entry = scope;
    v.array_id = var->array_id;
    if (var->array_id >= 0) v.kind = V_ARRAY;
    return v;
}

static void current_subsep(char *out) {
    AwkVar *var;
    int scope, index;
    char def[2];
    var = resolve_var("SUBSEP", 0, &scope, &index);
    if (var && var->value.kind != V_EMPTY) {
        as_string(var->value, out);
        return;
    }
    def[0] = '\034';
    def[1] = 0;
    scopy(out, def, MAX_STRING);
}

static Value get_element(const char *name, const char *key, int create) {
    Value v = empty_value();
    AwkVar *var;
    int scope, index, aid, entry;
    var = resolve_var(name, 1, &scope, &index);
    if (!var) return v;
    aid = ensure_array(var);
    entry = array_item(aid, key, create);
    if (entry < 0) return v;
    v = arrays[aid].item[entry].value;
    v.ref_kind = ref_kind_array();
    v.ref_index = aid;
    v.ref_entry = entry;
    return v;
}

static void assign_ref(Value ref, Value value) {
    AwkVar *var;
    if (ref.ref_kind == 1) {
        var = ref_var(ref.ref_entry, ref.ref_index);
        if (var) {
            var->value = value;
            if (ref.ref_entry == 0 && seq(var->name, "FS"))
                split_fields();
        }
    } else if (ref.ref_kind == 3) {
        assign_field(ref.ref_index, value);
    } else if (ref.ref_kind == 4) {
        assign_nf(value);
    } else if (ref.ref_kind == 5) {
        nr = (unsigned long)as_number(value);
    } else if (ref.ref_kind == 6) {
        fnr = (unsigned long)as_number(value);
    } else if (ref.ref_kind == 2 && ref.ref_index >= 0 &&
               ref.ref_index < array_count && ref.ref_entry >= 0 &&
               ref.ref_entry < arrays[ref.ref_index].count) {
        arrays[ref.ref_index].item[ref.ref_entry].value = value;
    } else error_flag = 1;
}

static int regex_span(const char *, const char *, int *, int *);

static void split_fields(void) {
    int i = 0, fs_index = find_global("FS", 0), fs_len;
    char fs[MAX_STRING];
    nf = 0;
    if (fs_index >= 0 && globals[fs_index].value.kind != V_EMPTY)
        as_string(globals[fs_index].value, fs);
    else scopy(fs, " ", MAX_STRING);
    fs_len = slen(fs);
    if (fs_len == 1 && fs[0] == ' ') {
        while (i < record_length) {
            int start;
            while (i < record_length &&
                   (record[i] == ' ' || record[i] == '\t')) i++;
            if (i >= record_length) break;
            start = i;
            while (i < record_length &&
                   record[i] != ' ' && record[i] != '\t') i++;
            if (nf < MAX_FIELDS) {
                field_start[nf] = start;
                field_length[nf] = i - start;
            }
            nf++;
        }
    } else if (fs_len == 0) {
        for (i = 0; i < record_length && nf < MAX_FIELDS; i++) {
            field_start[nf] = i;
            field_length[nf++] = 1;
        }
    } else if (fs_len == 1) {
        int start = 0;
        for (i = 0; i <= record_length && nf < MAX_FIELDS; i++) {
            if (i == record_length || record[i] == fs[0]) {
                field_start[nf] = start;
                field_length[nf++] = i - start;
                start = i + 1;
            }
        }
    } else {
        int start = 0, off, length;
        while (start <= record_length && nf < MAX_FIELDS) {
            if (!regex_span(fs, record + start, &off, &length)) {
                field_start[nf] = start;
                field_length[nf++] = record_length - start;
                break;
            }
            field_start[nf] = start;
            field_length[nf++] = off;
            start += off + length;
            if (length == 0 && start < record_length) start++;
        }
    }
}

static Value field_value(int n) {
    char text[MAX_STRING];
    int i, len;
    Value v;
    if (n == 0) v = string_value(record);
    else if (n < 1 || n > nf || n > MAX_FIELDS) v = empty_value();
    else {
        len = field_length[n - 1];
        if (len >= MAX_STRING) len = MAX_STRING - 1;
        for (i = 0; i < len; i++)
            text[i] = record[field_start[n - 1] + i];
        text[len] = 0;
        v = string_value(text);
    }
    v.ref_kind = 3;
    v.ref_index = n;
    return v;
}

static void save_fields(void) {
    int i, j, len;
    for (i = 0; i < MAX_FIELDS; i++) field_text[i][0] = 0;
    for (i = 0; i < nf && i < MAX_FIELDS; i++) {
        len = field_length[i];
        if (len >= MAX_STRING) len = MAX_STRING - 1;
        for (j = 0; j < len; j++)
            field_text[i][j] = record[field_start[i] + j];
        field_text[i][len] = 0;
    }
}

static void rebuild_record(int count) {
    char rebuilt[MAX_RECORD], ofs[MAX_STRING];
    int oi = find_global("OFS", 0);
    int used = 0, i, j, olen;
    if (oi >= 0 && globals[oi].value.kind != V_EMPTY)
        as_string(globals[oi].value, ofs);
    else scopy(ofs, " ", MAX_STRING);
    olen = slen(ofs);
    rebuilt[0] = 0;
    for (i = 0; i < count; i++) {
        if (i && used + olen < MAX_RECORD - 1) {
            for (j = 0; j < olen; j++) rebuilt[used++] = ofs[j];
        }
        field_start[i] = used;
        for (j = 0; field_text[i][j] && used < MAX_RECORD - 1; j++)
            rebuilt[used++] = field_text[i][j];
        field_length[i] = used - field_start[i];
    }
    rebuilt[used] = 0;
    scopy(record, rebuilt, MAX_RECORD);
    record_length = used;
    nf = count;
}

static int assign_field(int n, Value value) {
    char text[MAX_STRING];
    int count;
    if (n < 0 || n > MAX_FIELDS) {
        error_flag = 1;
        return 0;
    }
    as_string(value, text);
    if (n == 0) {
        scopy(record, text, MAX_RECORD);
        record_length = slen(record);
        split_fields();
        return 1;
    }
    save_fields();
    count = nf > n ? nf : n;
    scopy(field_text[n - 1], text, MAX_STRING);
    rebuild_record(count);
    return 1;
}

static int assign_nf(Value value) {
    int count = (int)as_number(value);
    if (count < 0 || count > MAX_FIELDS) {
        error_flag = 1;
        return 0;
    }
    save_fields();
    rebuild_record(count);
    return 1;
}

static int case_lower(char);
static int case_upper(char);
static int regex_class(const char *, int, char);

static int regex_equal(char a, char b) {
    return a == b || (regex_icase && case_lower(a) == case_lower(b));
}

static int regex_atom(const char **p, char c) {
    const char *q = *p;
    int neg = 0, hit = 0;
    if (*q == '.') {
        *p = q + 1;
        return c != 0;
    }
    if (*q == '\\' && q[1]) {
        *p = q + 2;
        if (q[1] == 'd' || q[1] == 'D') {
            hit = is_digit(c);
            return q[1] == 'd' ? hit : !hit;
        }
        if (q[1] == 'w' || q[1] == 'W') {
            hit = is_alpha(c) || is_digit(c) || c == '_';
            return q[1] == 'w' ? hit : !hit;
        }
        if (q[1] == 's' || q[1] == 'S') {
            hit = is_space(c) || c == '\n';
            return q[1] == 's' ? hit : !hit;
        }
        return regex_equal(q[1], c);
    }
    if (*q != '[') {
        if (*q) *p = q + 1;
        return regex_equal(*q, c);
    }
    q++;
    if (*q == '^') { neg = 1; q++; }
    if (*q == ']') {
        if (regex_equal(c, *q)) hit = 1;
        q++;
    }
    while (*q && *q != ']') {
        if (q[0] == '[' && q[1] == ':') {
            const char *end = q + 2;
            while (*end && !(end[0] == ':' && end[1] == ']')) end++;
            if (end[0] == ':' && end[1] == ']') {
                if (regex_class(q + 2, (int)(end - (q + 2)), c))
                    hit = 1;
                q = end + 2;
            } else {
                if (c == *q) hit = 1;
                q++;
            }
        } else if (q[0] == '[' &&
                   (q[1] == '.' || q[1] == '=')) {
            const char *end = q + 2;
            char marker = q[1];
            while (*end && !(end[0] == marker && end[1] == ']')) end++;
            if (end[0] == marker && end[1] == ']') {
                if (end == q + 3 && regex_equal(c, q[2])) hit = 1;
                q = end + 2;
            } else {
                if (regex_equal(c, *q)) hit = 1;
                q++;
            }
        } else if (q[1] == '-' && q[2] && q[2] != ']') {
            char test = regex_icase ? case_lower(c) : c;
            char low = regex_icase ? case_lower(q[0]) : q[0];
            char high = regex_icase ? case_lower(q[2]) : q[2];
            if (q[0] == 'A' && q[2] == 'Z' && regex_icase) {
                if (is_alpha(c)) hit = 1;
            } else if (test >= low && test <= high) hit = 1;
            q += 3;
        } else {
            if (regex_equal(c, *q)) hit = 1;
            q++;
        }
    }
    if (*q == ']') q++;
    *p = q;
    return neg ? !hit : hit;
}

static int regex_class(const char *name, int length, char c) {
    int lower = case_lower(c), upper = case_upper(c);
    if (length == 5 && name[0] == 'd' && name[1] == 'i')
        return is_digit(c);
    if (length == 5 && name[0] == 'a' && name[1] == 'l' &&
        name[2] == 'p') return is_alpha(c);
    if (length == 5 && name[0] == 'a' && name[1] == 'l' &&
        name[2] == 'n') return is_alpha(c) || is_digit(c);
    if (length == 4 && name[0] == 'w')
        return is_alpha(c) || is_digit(c) || c == '_';
    if (length == 5 && name[0] == 's' && name[1] == 'p')
        return is_space(c) || c == '\n';
    if (length == 5 && name[0] == 'b' && name[1] == 'l')
        return c == ' ' || c == '\t';
    if (length == 5 && name[0] == 'l' && name[1] == 'o')
        return (lower == c || regex_icase) && is_alpha(c);
    if (length == 5 && name[0] == 'u' && name[1] == 'p')
        return (upper == c || regex_icase) && is_alpha(c);
    if (length == 6 && name[0] == 'x' && name[1] == 'd')
        return is_digit(c) || (lower >= 'a' && lower <= 'f');
    if (length == 5 && name[0] == 'c' && name[1] == 'n')
        return c < ' ' || c == 127;
    if (length == 5 && name[0] == 'g' && name[1] == 'r')
        return c > ' ' && c != 127;
    if (length == 5 && name[0] == 'p' && name[1] == 'r')
        return c >= ' ' && c != 127;
    if (length == 5 && name[0] == 'p' && name[1] == 'u')
        return c > ' ' && c != 127 && !is_alpha(c) && !is_digit(c);
    if (length == 5 && name[0] == 'a' && name[1] == 's')
        return (unsigned char)c <= 127;
    return 0;
}

#if 0
static int regex_here_end(const char *p, const char *s,
                          const char **match_end);

static int regex_repeat_range(const char *atom, const char *rest,
                              const char *s, int count, int minimum,
                              int maximum, const char **match_end) {
    const char *next;
    if (count < maximum && *s) {
        next = atom;
        if (regex_atom(&next, *s) &&
            regex_repeat_range(atom, rest, s + 1, count + 1,
                               minimum, maximum, match_end)) return 1;
    }
    if (count >= minimum)
        return regex_here_end(rest, s, match_end);
    return 0;
}

static int regex_repeat(const char *atom, const char *rest,
                        const char *s, const char **match_end) {
    const char *next;
    if (*s) {
        next = atom;
        if (regex_atom(&next, *s) &&
            regex_repeat(atom, rest, s + 1, match_end)) return 1;
    }
    return regex_here_end(rest, s, match_end);
}

static int regex_class(const char *name, int length, char c) {
    int lower = case_lower(c), upper = case_upper(c);
    if (length == 5 && name[0] == 'd' && name[1] == 'i')
        return is_digit(c);
    if (length == 5 && name[0] == 'a' && name[1] == 'l' &&
        name[2] == 'p') return is_alpha(c);
    if (length == 5 && name[0] == 'a' && name[1] == 'l' &&
        name[2] == 'n') return is_alpha(c) || is_digit(c);
    if (length == 4 && name[0] == 'w')
        return is_alpha(c) || is_digit(c) || c == '_';
    if (length == 5 && name[0] == 's' && name[1] == 'p')
        return is_space(c) || c == '\n';
    if (length == 5 && name[0] == 'b' && name[1] == 'l')
        return c == ' ' || c == '\t';
    if (length == 5 && name[0] == 'l' && name[1] == 'o')
        return (lower == c || regex_icase) && is_alpha(c);
    if (length == 5 && name[0] == 'u' && name[1] == 'p')
        return (upper == c || regex_icase) && is_alpha(c);
    if (length == 6 && name[0] == 'x' && name[1] == 'd')
        return is_digit(c) || (lower >= 'a' && lower <= 'f');
    return 0;
}

static int regex_here_end(const char *p, const char *s,
                          const char **match_end) {
    const char *q = p;
    int hit, minimum, maximum, digits;
    if (!*p) {
        *match_end = s;
        return 1;
    }
    if (*p == '$' && !p[1]) {
        if (*s) return 0;
        *match_end = s;
        return 1;
    }
    hit = regex_atom(&q, *s);
    if (*q == '*') return regex_repeat(p, q + 1, s, match_end);
    if (*q == '+')
        return hit && regex_repeat(p, q + 1, s + 1, match_end);
    if (*q == '?') {
        q++;
        if (hit && regex_here_end(q, s + 1, match_end)) return 1;
        return regex_here_end(q, s, match_end);
    }
    if (*q == '{') {
        const char *r = q + 1;
        minimum = 0;
        maximum = 0;
        digits = 0;
        while (is_digit(*r)) {
            digits = 1;
            minimum = minimum * 10 + (*r++ - '0');
        }
        maximum = minimum;
        if (*r == ',') {
            r++;
            if (!is_digit(*r)) maximum = MAX_RECORD;
            else {
                maximum = 0;
                while (is_digit(*r))
                    maximum = maximum * 10 + (*r++ - '0');
            }
        } else if (!digits) r = q;
        if (*r == '}' && digits && maximum >= minimum) {
            return regex_repeat_range(p, r + 1, s, 0, minimum,
                                      maximum, match_end);
        }
    }
    return hit && regex_here_end(q, s + 1, match_end);
}

static int regex_span_one(const char *p, const char *s,
                          int *start, int *length) {
    const char *at = s, *end;
    int offset = 0;
    if (*p == '^') {
        if (!regex_here_end(p + 1, s, &end)) return 0;
        *start = 0;
        *length = (int)(end - s);
        return 1;
    }
    for (;;) {
        if (regex_here_end(p, at, &end)) {
            *start = offset;
            *length = (int)(end - at);
            return 1;
        }
        if (!*at) return 0;
        at++;
        offset++;
    }
}

static int regex_append(char *to, int used, int cap, const char *from) {
    int i = 0;
    while (from[i] && used + i < cap - 1) {
        to[used + i] = from[i];
        i++;
    }
    to[used + i] = 0;
    return used + i;
}

static void regex_expand(const char *p, char out[][MAX_STRING],
                         int *count, int depth) {
    int i, open = -1, close = -1, level = 0, escaped = 0, in_class = 0;
    int begin, j;
    char candidate[MAX_STRING];
    if (*count >= 32 || depth >= 12) return;
    for (i = 0; p[i]; i++) {
        if (escaped) { escaped = 0; continue; }
        if (p[i] == '\\') { escaped = 1; continue; }
        if (p[i] == '[') { in_class = 1; continue; }
        if (p[i] == ']' && in_class) { in_class = 0; continue; }
        if (in_class) continue;
        if (p[i] == '(') {
            if (open < 0) open = i;
            level++;
        } else if (p[i] == ')') {
            if (level > 0 && --level == 0) { close = i; break; }
        }
    }
    if (open >= 0 && close > open && p[close + 1] != '*' &&
        p[close + 1] != '+' && p[close + 1] != '?' &&
        p[close + 1] != '{') {
        escaped = 0;
        in_class = 0;
        level = 0;
        begin = open + 1;
        for (i = begin; i <= close; i++) {
            char c = p[i];
            if (i == close || (!escaped && !in_class && level == 0 &&
                               c == '|')) {
                int used = 0;
                candidate[0] = 0;
                used = regex_append(candidate, used, MAX_STRING, p);
                candidate[open] = 0;
                used = open;
                for (j = begin; j < i && used < MAX_STRING - 1; j++)
                    candidate[used++] = p[j];
                for (j = close + 1; p[j] && used < MAX_STRING - 1; j++)
                    candidate[used++] = p[j];
                candidate[used] = 0;
                regex_expand(candidate, out, count, depth + 1);
                begin = i + 1;
                escaped = 0;
                continue;
            }
            if (escaped) escaped = 0;
            else if (c == '\\') escaped = 1;
            else if (c == '[') in_class = 1;
            else if (c == ']' && in_class) in_class = 0;
            else if (!in_class && c == '(') level++;
            else if (!in_class && c == ')' && level > 0) level--;
        }
        return;
    }
    escaped = 0;
    in_class = 0;
    for (i = 0; p[i]; i++) {
        char c = p[i];
        if (escaped) { escaped = 0; continue; }
        if (c == '\\') { escaped = 1; continue; }
        if (c == '[') { in_class = 1; continue; }
        if (c == ']' && in_class) { in_class = 0; continue; }
        if (!in_class && c == '|') {
            int len = i;
            if (len >= MAX_STRING) len = MAX_STRING - 1;
            for (j = 0; j < len; j++) out[*count][j] = p[j];
            out[*count][len] = 0;
            (*count)++;
            regex_expand(p + i + 1, out, count, depth + 1);
            return;
        }
    }
    scopy(out[*count], p, MAX_STRING);
    (*count)++;
}

static int regex_span(const char *p, const char *s,
                      int *start, int *length) {
    char alternatives[32][MAX_STRING];
    int count = 0, i, found = 0, at, len, best_at = 0, best_len = 0;
    int old_icase = regex_icase, ign = find_global("IGNORECASE", 0);
    regex_icase = ign >= 0 && truth(globals[ign].value);
    regex_expand(p, alternatives, &count, 0);
    for (i = 0; i < count; i++) {
        if (regex_span_one(alternatives[i], s, &at, &len) &&
            (!found || at < best_at || (at == best_at && len > best_len))) {
            found = 1;
            best_at = at;
            best_len = len;
        }
    }
    if (found) {
        *start = best_at;
        *length = best_len;
    }
    regex_icase = old_icase;
    return found;
}

static int regex_match(const char *p, const char *s) {
    int start, length;
    return regex_span(p, s, &start, &length);
}
#endif

static int rx_new(int kind, int left, int right, int value,
                  int minimum, int maximum) {
    int i;
    if (rx_node_count >= MAX_RX_NODES) {
        rx_parse_error = 1;
        return 0;
    }
    i = rx_node_count++;
    rx_nodes[i].kind = kind;
    rx_nodes[i].left = left;
    rx_nodes[i].right = right;
    rx_nodes[i].value = value;
    rx_nodes[i].minimum = minimum;
    rx_nodes[i].maximum = maximum;
    return i;
}

static int rx_parse_alt(void);

static int rx_parse_atom(void) {
    char c;
    int start, group, child, length;
    if (!rx_pattern[rx_parse_pos]) {
        rx_parse_error = 1;
        return 0;
    }
    c = rx_pattern[rx_parse_pos++];
    if (c == '(') {
        group = ++rx_group_count;
        if (group > MAX_RX_GROUPS) rx_parse_error = 1;
        child = rx_parse_alt();
        if (rx_pattern[rx_parse_pos] != ')') rx_parse_error = 1;
        else rx_parse_pos++;
        return rx_new(RX_GROUP, child, 0, group, 0, 0);
    }
    if (c == '[') {
        start = rx_parse_pos - 1;
        if (rx_pattern[rx_parse_pos] == '^') rx_parse_pos++;
        if (rx_pattern[rx_parse_pos] == ']') rx_parse_pos++;
        while (rx_pattern[rx_parse_pos]) {
            char marker;
            if (rx_pattern[rx_parse_pos] == '\\' &&
                rx_pattern[rx_parse_pos + 1]) {
                rx_parse_pos += 2;
                continue;
            }
            if (rx_pattern[rx_parse_pos] == '[' &&
                (rx_pattern[rx_parse_pos + 1] == ':' ||
                 rx_pattern[rx_parse_pos + 1] == '.' ||
                 rx_pattern[rx_parse_pos + 1] == '=')) {
                marker = rx_pattern[rx_parse_pos + 1];
                rx_parse_pos += 2;
                while (rx_pattern[rx_parse_pos] &&
                       !(rx_pattern[rx_parse_pos] == marker &&
                         rx_pattern[rx_parse_pos + 1] == ']'))
                    rx_parse_pos++;
                if (rx_pattern[rx_parse_pos]) rx_parse_pos += 2;
                continue;
            }
            if (rx_pattern[rx_parse_pos++] == ']') break;
        }
        length = rx_parse_pos - start;
        if (rx_pattern[rx_parse_pos - 1] != ']') rx_parse_error = 1;
        return rx_new(RX_CLASS, 0, 0, start, length, 0);
    }
    if (c == '\\') {
        c = rx_pattern[rx_parse_pos++];
        if (!c) {
            rx_parse_error = 1;
            return 0;
        }
        if (c >= '1' && c <= '9')
            return rx_new(RX_BACKREF, 0, 0, c - '0', 0, 0);
        if (c == 'd' || c == 'D' || c == 'w' || c == 'W' ||
            c == 's' || c == 'S') {
            rx_pattern[rx_parse_pos - 2] = '\\';
            return rx_new(RX_CLASS, 0, 0, rx_parse_pos - 2, 2, 0);
        }
        if (c == 'n') c = '\n';
        else if (c == 't') c = '\t';
        else if (c == 'r') c = '\r';
        return rx_new(RX_CHAR, 0, 0, (unsigned char)c, 0, 0);
    }
    if (c == '.') return rx_new(RX_ANY, 0, 0, 0, 0, 0);
    if (c == '^') return rx_new(RX_BOL, 0, 0, 0, 0, 0);
    if (c == '$') return rx_new(RX_EOL, 0, 0, 0, 0, 0);
    if (c == ')' || c == '|') {
        rx_parse_error = 1;
        return 0;
    }
    return rx_new(RX_CHAR, 0, 0, (unsigned char)c, 0, 0);
}

static int rx_parse_repeat(void) {
    int atom, minimum, maximum, digits;
    char c;
    const char *p;
    atom = rx_parse_atom();
    c = rx_pattern[rx_parse_pos];
    if (c == '*') {
        rx_parse_pos++;
        return rx_new(RX_STAR, atom, 0, 0, 0, -1);
    }
    if (c == '+') {
        rx_parse_pos++;
        return rx_new(RX_PLUS, atom, 0, 0, 1, -1);
    }
    if (c == '?') {
        rx_parse_pos++;
        return rx_new(RX_OPTIONAL, atom, 0, 0, 0, 1);
    }
    if (c != '{') return atom;
    p = rx_pattern + rx_parse_pos + 1;
    minimum = 0;
    maximum = 0;
    digits = 0;
    while (is_digit(*p)) {
        digits = 1;
        if (minimum < 1000) minimum = minimum * 10 + (*p - '0');
        p++;
    }
    maximum = minimum;
    if (*p == ',') {
        p++;
        if (!is_digit(*p)) maximum = -1;
        else {
            maximum = 0;
            while (is_digit(*p)) {
                if (maximum < 1000) maximum = maximum * 10 + (*p - '0');
                p++;
            }
        }
    }
    if (!digits || *p != '}' ||
        (maximum >= 0 && maximum < minimum) ||
        minimum > MAX_RECORD || maximum > MAX_RECORD) {
        rx_parse_error = 1;
        return atom;
    }
    rx_parse_pos = (int)(p - rx_pattern) + 1;
    return rx_new(RX_RANGE, atom, 0, 0, minimum, maximum);
}

static int rx_parse_sequence(void) {
    int node, next;
    if (rx_pattern[rx_parse_pos] == ')' ||
        rx_pattern[rx_parse_pos] == '|' ||
        rx_pattern[rx_parse_pos] == 0)
        return rx_new(RX_EMPTY, 0, 0, 0, 0, 0);
    node = rx_parse_repeat();
    while (rx_pattern[rx_parse_pos] &&
           rx_pattern[rx_parse_pos] != ')' &&
           rx_pattern[rx_parse_pos] != '|') {
        next = rx_parse_repeat();
        node = rx_new(RX_SEQ, node, next, 0, 0, 0);
    }
    return node;
}

static int rx_parse_alt(void) {
    int node, right;
    node = rx_parse_sequence();
    while (rx_pattern[rx_parse_pos] == '|') {
        rx_parse_pos++;
        right = rx_parse_sequence();
        node = rx_new(RX_ALT, node, right, 0, 0, 0);
    }
    return node;
}

static int rx_emit(int op, int x, int y, int value) {
    int i;
    if (rx_code_count >= MAX_RX_CODE) {
        rx_parse_error = 1;
        return 0;
    }
    i = rx_code_count++;
    rx_code[i].op = op;
    rx_code[i].x = x;
    rx_code[i].y = y;
    rx_code[i].value = value;
    return i;
}

static int rx_emit_node(int node, int next);

static int rx_emit_star(int child, int next) {
    int split = rx_emit(RXI_SPLIT, 0, next, 0);
    int start = rx_emit_node(child, split);
    rx_code[split].x = start;
    return split;
}

static int rx_emit_optional(int child, int next) {
    int split = rx_emit(RXI_SPLIT, 0, next, 0);
    rx_code[split].x = rx_emit_node(child, next);
    return split;
}

static int rx_emit_node(int node, int next) {
    RxNode *n = &rx_nodes[node];
    int start, end, i;
    switch (n->kind) {
    case RX_EMPTY:
        return next;
    case RX_CHAR:
        return rx_emit(RXI_CHAR, next, 0, n->value);
    case RX_ANY:
        return rx_emit(RXI_ANY, next, 0, 0);
    case RX_CLASS:
        return rx_emit(RXI_CLASS, next, 0, n->value);
    case RX_BOL:
        return rx_emit(RXI_BOL, next, 0, 0);
    case RX_EOL:
        return rx_emit(RXI_EOL, next, 0, 0);
    case RX_BACKREF:
        return rx_emit(RXI_BACKREF, next, 0, n->value);
    case RX_SEQ:
        start = rx_emit_node(n->right, next);
        return rx_emit_node(n->left, start);
    case RX_ALT:
        start = rx_emit_node(n->left, next);
        end = rx_emit_node(n->right, next);
        return rx_emit(RXI_SPLIT, start, end, 0);
    case RX_GROUP:
        end = rx_emit(RXI_SAVE_END, next, 0, n->value);
        start = rx_emit_node(n->left, end);
        return rx_emit(RXI_SAVE_START, start, 0, n->value);
    case RX_STAR:
        return rx_emit_star(n->left, next);
    case RX_PLUS:
        end = rx_emit(RXI_SPLIT, 0, next, 0);
        start = rx_emit_node(n->left, end);
        rx_code[end].x = start;
        return start;
    case RX_OPTIONAL:
        return rx_emit_optional(n->left, next);
    case RX_RANGE:
        start = next;
        if (n->maximum < 0) start = rx_emit_star(n->left, start);
        else {
            for (i = n->minimum; i < n->maximum; i++)
                start = rx_emit_optional(n->left, start);
        }
        for (i = 0; i < n->minimum; i++)
            start = rx_emit_node(n->left, start);
        return start;
    }
    rx_parse_error = 1;
    return next;
}

static int rx_caps_better(const RxState *state, int *best_start,
                          int *best_end) {
    int i, a, b;
    for (i = 1; i <= rx_group_count; i++) {
        a = state->start[i] < 0 ? 0 : state->end[i] - state->start[i] + 1;
        b = best_start[i] < 0 ? 0 : best_end[i] - best_start[i] + 1;
        if (a != b) return a > b;
        if (state->start[i] >= 0 && best_start[i] >= 0 &&
            state->start[i] != best_start[i])
            return state->start[i] < best_start[i];
    }
    return 0;
}

static int rx_run(int start_pc, const char *text, int text_len, int start_pos,
                  int *best_end, int *best_start, int *best_group_end) {
    int top = 0, steps = 0, found = 0, i;
    RxState state;
    state.pc = start_pc;
    state.pos = start_pos;
    for (i = 0; i <= MAX_RX_GROUPS; i++) {
        state.start[i] = -1;
        state.end[i] = -1;
    }
    rx_stack[top++] = state;
    while (top && steps++ < 50000) {
        state = rx_stack[--top];
        while (state.pc >= 0 && state.pc < rx_code_count) {
            RxInstruction *ins = &rx_code[state.pc];
            char c = state.pos < text_len ? text[state.pos] : 0;
            int cap, length, j, match;
            if (ins->op == RXI_CHAR) {
                match = c && regex_equal(c, (char)ins->value);
                if (!match) break;
                state.pos++;
                state.pc = ins->x;
            } else if (ins->op == RXI_ANY) {
                if (!c || c == '\n') break;
                state.pos++;
                state.pc = ins->x;
            } else if (ins->op == RXI_CLASS) {
                const char *classp = rx_pattern + ins->value;
                if (!c || !regex_atom(&classp, c)) break;
                state.pos++;
                state.pc = ins->x;
            } else if (ins->op == RXI_BOL) {
                if (state.pos != 0) break;
                state.pc = ins->x;
            } else if (ins->op == RXI_EOL) {
                if (state.pos != text_len) break;
                state.pc = ins->x;
            } else if (ins->op == RXI_SAVE_START) {
                cap = ins->value;
                state.start[cap] = state.pos;
                state.end[cap] = -1;
                state.pc = ins->x;
            } else if (ins->op == RXI_SAVE_END) {
                state.end[ins->value] = state.pos;
                state.pc = ins->x;
            } else if (ins->op == RXI_BACKREF) {
                cap = ins->value;
                if (cap > rx_group_count || state.start[cap] < 0 ||
                    state.end[cap] < state.start[cap]) break;
                length = state.end[cap] - state.start[cap];
                if (state.pos + length > text_len) break;
                for (j = 0; j < length; j++)
                    if (!regex_equal(text[state.start[cap] + j],
                                     text[state.pos + j])) break;
                if (j != length) break;
                state.pos += length;
                state.pc = ins->x;
            } else if (ins->op == RXI_SPLIT) {
                if (top >= MAX_RX_STACK) {
                    error_flag = 1;
                    break;
                }
                rx_stack[top] = state;
                rx_stack[top++].pc = ins->y;
                state.pc = ins->x;
            } else if (ins->op == RXI_MATCH) {
                if (!found || state.pos > *best_end ||
                    (state.pos == *best_end &&
                     rx_caps_better(&state, best_start, best_group_end))) {
                    found = 1;
                    *best_end = state.pos;
                    for (i = 0; i <= MAX_RX_GROUPS; i++) {
                        best_start[i] = state.start[i];
                        best_group_end[i] = state.end[i];
                    }
                }
                break;
            } else break;
        }
    }
    if (steps >= 50000) error_flag = 1;
    return found;
}

static int regex_span(const char *p, const char *s,
                      int *start, int *length) {
    int root, match_pc, start_pc, pos, best_end, found = 0;
    int i, old_icase = regex_icase, ign = find_global("IGNORECASE", 0);
    scopy(rx_pattern, p, MAX_STRING);
    rx_parse_pos = 0;
    rx_group_count = 0;
    rx_node_count = 0;
    rx_code_count = 0;
    rx_parse_error = 0;
    regex_icase = ign >= 0 && truth(globals[ign].value);
    root = rx_parse_alt();
    if (rx_pattern[rx_parse_pos] || rx_parse_error) {
        regex_icase = old_icase;
        error_flag = 1;
        return 0;
    }
    match_pc = rx_emit(RXI_MATCH, -1, 0, 0);
    start_pc = rx_emit_node(root, match_pc);
    if (rx_parse_error) {
        regex_icase = old_icase;
        error_flag = 1;
        return 0;
    }
    for (pos = 0; pos <= slen(s); pos++) {
        best_end = -1;
        for (i = 0; i <= MAX_RX_GROUPS; i++) {
            rx_capture_start[i] = -1;
            rx_capture_end[i] = -1;
        }
        if (rx_run(start_pc, s, slen(s), pos, &best_end,
                   rx_capture_start, rx_capture_end)) {
            found = 1;
            *start = pos;
            *length = best_end - pos;
            break;
        }
        if (error_flag) break;
    }
    regex_icase = old_icase;
    return found;
}

static int regex_match(const char *p, const char *s) {
    int start, length;
    return regex_span(p, s, &start, &length);
}

static int prec_start(int k) {
    return k == TOK_ID || k == TOK_NUM || k == TOK_STR || k == '$' ||
           k == '(' || k == '!';
}

static Value parse_expression(void);
static Value parse_assignment(void);
static Value parse_statement(int run);

static int next_main_line(char *line) {
    char filename[MAX_STRING], key[MAX_KEY];
    Value arg;
    int argc;
    while (1) {
        if (data_stream) {
            if (fgets(line, MAX_RECORD, data_stream)) {
                int n = slen(line);
                while (n > 0 &&
                       (line[n - 1] == '\n' || line[n - 1] == '\r'))
                    line[--n] = 0;
                nr++;
                fnr++;
                return 1;
            }
            fclose(data_stream);
            data_stream = 0;
        }
        argc = (int)as_number(get_variable("ARGC"));
        if (input_index < 1 || input_index >= argc) return 0;
        sprintf(key, "%d", input_index++);
        arg = get_element("ARGV", key, 0);
        as_string(arg, filename);
        if (!filename[0]) continue;
        data_stream = fopen(filename, "r");
        if (!data_stream) {
            printf("CMSAWK: cannot open input %s\n", filename);
            error_flag = 1;
            return 0;
        }
        set_global("FILENAME", string_value(filename));
        fnr = 0;
    }
}

static int read_record(FILE *stream, int count_nr, int replace_zero,
                       int has_target, Value target) {
    char line[MAX_RECORD];
    int n;
    if (count_nr) {
        if (!next_main_line(line)) return 0;
    } else {
        if (!stream || !fgets(line, sizeof line, stream)) return 0;
        n = slen(line);
        while (n > 0 && (line[n - 1] == '\n' || line[n - 1] == '\r'))
            line[--n] = 0;
    }
    if (replace_zero) {
        scopy(record, line, MAX_RECORD);
        record_length = slen(record);
        split_fields();
    } else if (has_target) {
        assign_ref(target, string_value(line));
    }
    return 1;
}

static int find_function(const char *name) {
    int i;
    for (i = 0; i < function_count; i++)
        if (seq(functions[i].name, name)) return i;
    return -1;
}

static Value call_function(int fi, Value *args, int argc) {
    Value result = empty_value();
    ParserState resume;
    int i, caller_flow;
    if (!execute_enabled) return result;
    if (fi < 0 || fi >= function_count || frame_depth >= MAX_FRAMES) {
        error_flag = 1;
        return result;
    }
    resume = save_parser();
    caller_flow = flow_state;
    flow_state = FLOW_NONE;
    frame_depth++;
    frames[frame_depth - 1].count = 0;
    frames[frame_depth - 1].flow = FLOW_NONE;
    frames[frame_depth - 1].result = empty_value();
    for (i = 0; i < functions[fi].param_count; i++) {
        int vi = find_local(functions[fi].param[i], 1);
        if (vi < 0) { error_flag = 1; break; }
        if (i < argc) {
            frames[frame_depth - 1].var[vi].value = args[i];
            if (args[i].ref_kind == 1 && args[i].array_id >= 0) {
                frames[frame_depth - 1].var[vi].array_id = args[i].array_id;
            } else if (args[i].ref_kind == 1) {
                frames[frame_depth - 1].var[vi].alias_kind =
                    args[i].ref_entry == 0 ? 1 : 2;
                frames[frame_depth - 1].var[vi].alias_index =
                    args[i].ref_index;
            } else if (args[i].kind == V_ARRAY) {
                frames[frame_depth - 1].var[vi].array_id = args[i].array_id;
            }
        }
    }
    set_parser(functions[fi].body_start);
    parse_statement(1);
    if (flow_state == FLOW_RETURN) {
        result = frames[frame_depth - 1].result;
        flow_state = caller_flow;
    } else if (flow_state != FLOW_EXIT && flow_state != FLOW_NEXT) {
        if (flow_state != FLOW_NONE) error_flag = 1;
        flow_state = caller_flow;
    }
    frame_depth--;
    restore_parser(resume);
    return result;
}

static void clear_array(int aid) {
    int i;
    if (aid < 0 || aid >= array_count) return;
    for (i = 0; i < arrays[aid].count; i++)
        arrays[aid].item[i].used = 0;
    arrays[aid].count = 0;
}

static int array_from_value(Value v) {
    AwkVar *var;
    if (v.kind == V_ARRAY) return v.array_id;
    if (v.ref_kind != 1) return -1;
    var = ref_var(v.ref_entry, v.ref_index);
    return var ? ensure_array(var) : -1;
}

static void set_global(const char *name, Value v) {
    int i = find_global(name, 1);
    if (i >= 0) globals[i].value = v;
}

static int split_into_array(const char *text, int aid, const char *sep) {
    int count = 0, i = 0, start, len, n;
    char key[MAX_KEY], part[MAX_STRING];
    int sep_len = slen(sep);
    clear_array(aid);
    n = slen(text);
    if (sep_len == 1 && sep[0] == ' ') {
        while (i < n) {
            while (i < n && is_space(text[i])) i++;
            if (i >= n) break;
            start = i;
            while (i < n && !is_space(text[i])) i++;
            len = i - start;
            if (len >= MAX_STRING) len = MAX_STRING - 1;
            while (len > 0) {
                int j;
                for (j = 0; j < len; j++) part[j] = text[start + j];
                part[len] = 0;
                sprintf(key, "%d", count + 1);
                if (array_item(aid, key, 1) < 0) return count;
                arrays[aid].item[array_item(aid, key, 0)].value =
                    string_value(part);
                count++;
                break;
            }
        }
        return count;
    }
    if (!sep_len) {
        while (i < n && count < MAX_ITEMS) {
            part[0] = text[i++];
            part[1] = 0;
            sprintf(key, "%d", count + 1);
            {
                int entry = array_item(aid, key, 1);
                if (entry < 0) break;
                arrays[aid].item[entry].value = string_value(part);
            }
            count++;
        }
        return count;
    }
    while (i <= n) {
        int at, width, found = 0;
        if (i == n) {
            at = n;
            width = 0;
            found = 1;
        } else if (sep_len == 1) {
            for (at = i; at < n && text[at] != sep[0]; at++) {}
            if (at < n) { width = 1; found = 1; }
        } else {
            int off, ml;
            if (regex_span(sep, text + i, &off, &ml)) {
                at = i + off;
                width = ml;
                found = 1;
            }
        }
        if (!found) {
            at = n;
            width = 0;
        }
        len = at - i;
        if (len >= MAX_STRING) len = MAX_STRING - 1;
        {
            int j;
            for (j = 0; j < len; j++) part[j] = text[i + j];
        }
        part[len] = 0;
        sprintf(key, "%d", count + 1);
        {
            int entry = array_item(aid, key, 1);
            if (entry < 0) return count;
            arrays[aid].item[entry].value = string_value(part);
        }
        count++;
        if (at >= n) break;
        i = at + width;
        if (width == 0 && i < n) i++;
    }
    return count;
}

static int case_lower(char c) {
    if ((c >= 'A' && c <= 'I') || (c >= 'J' && c <= 'R') ||
        (c >= 'S' && c <= 'Z')) return c + ('a' - 'A');
    return c;
}

static int case_upper(char c) {
    if ((c >= 'a' && c <= 'i') || (c >= 'j' && c <= 'r') ||
        (c >= 's' && c <= 'z')) return c + ('A' - 'a');
    return c;
}

static double abs_double(double x) {
    return x < 0 ? -x : x;
}

static double sqrt_approx(double x) {
    double guess;
    int i;
    if (x < 0) { error_flag = 1; return 0; }
    if (x == 0) return 0;
    guess = x >= 1 ? x : 1;
    for (i = 0; i < 32; i++) guess = (guess + x / guess) / 2;
    return guess;
}

static double exp_approx(double x) {
    double term = 1, sum = 1;
    int i, scale = 0;
    if (x > 80) return 1.0e30;
    if (x < -80) return 0;
    while (abs_double(x) > 0.5 && scale < 16) {
        x /= 2;
        scale++;
    }
    for (i = 1; i <= 36; i++) {
        term *= x / i;
        sum += term;
    }
    while (scale-- > 0) sum *= sum;
    return sum;
}

static double log_approx(double x) {
    double z, z2, term, sum;
    int scale = 0, i;
    if (x <= 0) { error_flag = 1; return 0; }
    while (x > 1.5) { x /= 2; scale++; }
    while (x < 0.75) { x *= 2; scale--; }
    z = (x - 1) / (x + 1);
    z2 = z * z;
    term = z;
    sum = z;
    for (i = 3; i <= 79; i += 2) {
        term *= z2;
        sum += term / i;
    }
    return 2 * sum + scale * 0.6931471805599453;
}

static double atan_small(double x) {
    double term = x, sum = x, x2 = x * x;
    int i, sign = -1;
    for (i = 3; i <= 79; i += 2) {
        term *= x2;
        sum += sign * term / i;
        sign = -sign;
    }
    return sum;
}

static double atan_approx(double x) {
    double sign = 1;
    if (x < 0) { sign = -1; x = -x; }
    if (x > 1) return sign * (1.5707963267948966 -
                              atan_approx(1 / x));
    if (x > 0.4142135623730950)
        return sign * (0.7853981633974483 +
                       atan_small((x - 1) / (x + 1)));
    return sign * atan_small(x);
}

static double atan2_approx(double y, double x) {
    if (x > 0) return atan_approx(y / x);
    if (x < 0 && y >= 0) return atan_approx(y / x) + 3.1415926535897932;
    if (x < 0 && y < 0) return atan_approx(y / x) - 3.1415926535897932;
    if (y > 0) return 1.5707963267948966;
    if (y < 0) return -1.5707963267948966;
    return 0;
}

static double sin_approx(double x) {
    double term, sum, x2;
    int i, n;
    while (x > 3.1415926535897932) x -= 6.2831853071795864;
    while (x < -3.1415926535897932) x += 6.2831853071795864;
    term = x;
    sum = x;
    x2 = x * x;
    for (i = 3, n = 1; i <= 31; i += 2, n++) {
        term *= -x2 / ((i - 1) * i);
        sum += term;
    }
    return sum;
}

static int substitute_value(const char *pattern, const char *replacement,
                            Value target, int global, int use_current) {
    char input[MAX_STRING], repl[MAX_STRING], output[MAX_STRING];
    int in_len, pos = 0, used = 0, count = 0;
    as_string(target, input);
    as_string(string_value(replacement), repl);
    in_len = slen(input);
    output[0] = 0;
    while (pos <= in_len && used < MAX_STRING - 1) {
        int start, length, i;
        if (!regex_span(pattern, input + pos, &start, &length)) break;
        start += pos;
        for (i = pos; i < start && used < MAX_STRING - 1; i++)
            output[used++] = input[i];
        for (i = 0; repl[i] && used < MAX_STRING - 1; i++) {
            if (repl[i] == '&') {
                int j;
                for (j = 0; j < length && used < MAX_STRING - 1; j++)
                    output[used++] = input[start + j];
            } else if (repl[i] == '\\' && repl[i + 1] == '&') {
                output[used++] = '&';
                i++;
            } else output[used++] = repl[i];
        }
        count++;
        pos = start + length;
        if (!global) break;
        if (length == 0 && pos < in_len) output[used++] = input[pos++];
        if (length == 0 && pos >= in_len) break;
    }
    while (pos < in_len && used < MAX_STRING - 1)
        output[used++] = input[pos++];
    output[used] = 0;
    if (count) {
        if (target.ref_kind) assign_ref(target, string_value(output));
        else if (use_current) assign_field(0, string_value(output));
    }
    return count;
}

static void set_array_string(int aid, int index, const char *text) {
    char key[MAX_KEY];
    int entry;
    sprintf(key, "%d", index);
    entry = array_item(aid, key, 1);
    if (entry >= 0) arrays[aid].item[entry].value = string_value(text);
}

static void match_captures(const char *text, int match_start,
                           int match_length, int aid) {
    int group, start, end, i;
    char value[MAX_STRING];
    clear_array(aid);
    for (i = 0; i < match_length && i < MAX_STRING - 1; i++)
        value[i] = text[match_start + i];
    value[i] = 0;
    set_array_string(aid, 0, value);
    for (group = 1; group <= rx_group_count; group++) {
        start = rx_capture_start[group];
        end = rx_capture_end[group];
        if (start < match_start || end < start ||
            end > match_start + match_length) {
            set_array_string(aid, group, "");
            continue;
        }
        for (i = 0; start + i < end && i < MAX_STRING - 1; i++)
            value[i] = text[start + i];
        value[i] = 0;
        set_array_string(aid, group, value);
    }
}

static Value call_builtin(const char *name, Value *args, int argc) {
    Value v = empty_value();
    char text[MAX_STRING], other[MAX_STRING];
    if (seq(name, "length")) {
        if (argc && args[0].kind == V_ARRAY &&
            args[0].array_id >= 0 && args[0].array_id < array_count) {
            int i, count = 0;
            for (i = 0; i < arrays[args[0].array_id].count; i++)
                if (arrays[args[0].array_id].item[i].used) count++;
            return number_value(count);
        }
        if (argc) as_string(args[0], text);
        else scopy(text, record, MAX_STRING);
        return number_value((double)slen(text));
    }
    if (seq(name, "int") && argc)
        return number_value((long)as_number(args[0]));
    if (seq(name, "index") && argc >= 2) {
        int i, j;
        as_string(args[0], text);
        as_string(args[1], other);
        for (i = 0; text[i]; i++) {
            for (j = 0; other[j] && text[i + j] == other[j]; j++) {}
            if (!other[j]) return number_value(i + 1);
        }
        return number_value(other[0] ? 0 : 1);
    }
    if (seq(name, "tolower") && argc) {
        int i;
        as_string(args[0], text);
        for (i = 0; text[i]; i++) text[i] = (char)case_lower(text[i]);
        return string_value(text);
    }
    if (seq(name, "toupper") && argc) {
        int i;
        as_string(args[0], text);
        for (i = 0; text[i]; i++) text[i] = (char)case_upper(text[i]);
        return string_value(text);
    }
    if (seq(name, "substr") && argc >= 2) {
        int start = (int)as_number(args[1]) - 1;
        int len, i, source_len;
        as_string(args[0], text);
        if (start < 0) start = 0;
        source_len = slen(text);
        if (start > source_len) start = source_len;
        len = argc >= 3 ? (int)as_number(args[2]) : source_len - start;
        if (len < 0) len = 0;
        for (i = 0; i < len && i < MAX_STRING - 1 &&
                    text[start + i]; i++) v.text[i] = text[start + i];
        v.text[i] = 0;
        v.kind = V_STR;
        return v;
    }
    if (seq(name, "split") && argc >= 2) {
        char sep[MAX_STRING];
        int aid = array_from_value(args[1]);
        if (aid < 0) { error_flag = 1; return number_value(0); }
        as_string(args[0], text);
        if (argc >= 3) as_string(args[2], sep);
        else {
            int fs = find_global("FS", 0);
            if (fs >= 0 && globals[fs].value.kind != V_EMPTY)
                as_string(globals[fs].value, sep);
            else scopy(sep, " ", MAX_STRING);
        }
        return number_value(split_into_array(text, aid, sep));
    }
    if (seq(name, "match") && argc >= 2) {
        int start, length;
        as_string(args[0], text);
        as_string(args[1], other);
        if (regex_span(other, text, &start, &length)) {
            set_global("RSTART", number_value(start + 1));
            set_global("RLENGTH", number_value(length));
            if (argc >= 3) {
                int aid = array_from_value(args[2]);
                if (aid >= 0) match_captures(text, start, length, aid);
            }
            return number_value(start + 1);
        }
        set_global("RSTART", number_value(0));
        set_global("RLENGTH", number_value(-1));
        if (argc >= 3) {
            int aid = array_from_value(args[2]);
            clear_array(aid);
        }
        return number_value(0);
    }
    if ((seq(name, "sub") || seq(name, "gsub")) && argc >= 2) {
        Value target = argc >= 3 ? args[2] : field_value(0);
        as_string(args[0], text);
        as_string(args[1], other);
        return number_value(substitute_value(text, other, target,
                          seq(name, "gsub"), argc < 3));
    }
    if (seq(name, "close") && argc) {
        as_string(args[0], text);
        return number_value(close_io(text));
    }
    if (seq(name, "fflush")) {
        if (!argc) {
            fflush((FILE *)0);
            return number_value(0);
        }
        as_string(args[0], text);
        {
            int i;
            for (i = 0; i < MAX_IO; i++)
                if (io_stream[i] && seq(io_name[i], text))
                    return number_value(fflush(io_stream[i]));
        }
        return number_value(-1);
    }
    if (seq(name, "sqrt") && argc)
        return number_value(sqrt_approx(as_number(args[0])));
    if (seq(name, "exp") && argc)
        return number_value(exp_approx(as_number(args[0])));
    if (seq(name, "log") && argc)
        return number_value(log_approx(as_number(args[0])));
    if (seq(name, "sin") && argc)
        return number_value(sin_approx(as_number(args[0])));
    if (seq(name, "cos") && argc)
        return number_value(sin_approx(as_number(args[0]) +
                                       1.5707963267948966));
    if (seq(name, "atan2") && argc >= 2)
        return number_value(atan2_approx(as_number(args[0]),
                                         as_number(args[1])));
    if (seq(name, "rand")) {
        random_seed = random_seed * 1103515245UL + 12345UL;
        return number_value((double)(random_seed & 0x7fffffffUL) /
                            2147483648.0);
    }
    if (seq(name, "srand")) {
        unsigned long old = random_seed;
        random_seed = argc ? (unsigned long)as_number(args[0]) : 1UL;
        return number_value((double)old);
    }
    if (seq(name, "system") && argc) {
        as_string(args[0], text);
        return number_value(system(text));
    }
    return v;
}

static Value parse_primary(void) {
    Value v = empty_value();
    if (token.kind == TOK_NUM) {
        v = number_value(token.number);
        lex_next();
        return v;
    }
    if (token.kind == TOK_STR) {
        v = string_value(token.text);
        lex_next();
        return v;
    }
    if (token.kind == TOK_REGEX) {
        v = string_value(token.text);
        lex_next();
        return v;
    }
    if (token.kind == '/') {
        int p = token.start + 1, escaped = 0;
        int start = p;
        while (p < source_length) {
            char c = source[p++];
            if (!escaped && c == '/') break;
            if (escaped) escaped = 0;
            else if (c == '\\') escaped = 1;
        }
        if (p > source_length || source[p - 1] != '/') {
            error_flag = 1;
            return empty_value();
        }
        token_text(&token, source + start, p - start - 1);
        v = string_value(token.text);
        set_parser(p);
        return v;
    }
    if (accept('(')) {
        int old_context = print_context;
        print_context = 0;
        v = parse_expression();
        require(')');
        print_context = old_context;
        return v;
    }
    if (accept('$')) {
        Value n = parse_primary();
        return field_value((int)as_number(n));
    }
    if (token.kind == TOK_ID) {
        char name[MAX_STRING];
        Value args[MAX_PARAMS];
        int argc = 0, fi;
        scopy(name, token.text, MAX_STRING);
        lex_next();
        if (seq(name, "getline")) {
            Value target = empty_value(), filename_value;
            int has_target = 0, from_file = 0, got;
            char filename[MAX_STRING];
            FILE *input = data_stream;
            if (accept('<')) {
                filename_value = parse_assignment();
                as_string(filename_value, filename);
                from_file = 1;
            } else if (token.kind == TOK_ID || token.kind == '$') {
                target = parse_primary();
                has_target = 1;
                if (accept('<')) {
                    filename_value = parse_assignment();
                    as_string(filename_value, filename);
                    from_file = 1;
                }
            }
            if (!execute_enabled) return number_value(0);
            if (from_file) input = open_io(filename, 'r');
            got = read_record(input, !from_file, !has_target, has_target,
                              target);
            return number_value(got);
        }
        if (seq(name, "NR")) {
            v = number_value((double)nr);
            v.ref_kind = 5;
            return v;
        }
        if (seq(name, "FNR")) {
            v = number_value((double)fnr);
            v.ref_kind = 6;
            return v;
        }
        if (seq(name, "NF")) {
            v = number_value((double)nf);
            v.ref_kind = 4;
            return v;
        }
        if (seq(name, "SUBSEP")) {
            int scope, index, vi;
            AwkVar *var = resolve_var("SUBSEP", 0, &scope, &index);
            if (!var) {
                vi = find_global("SUBSEP", 1);
                if (vi >= 0 && globals[vi].value.kind == V_EMPTY) {
                    char sep[2];
                    sep[0] = '\034';
                    sep[1] = 0;
                    globals[vi].value = string_value(sep);
                }
            }
            return get_variable("SUBSEP");
        }
        if (accept('(')) {
            if (token.kind != ')') {
                do {
                    if (argc >= MAX_PARAMS) { error_flag = 1; break; }
                    args[argc++] = parse_assignment();
                } while (accept(','));
            }
            require(')');
            if (!execute_enabled) return empty_value();
            if (seq(name, "sprintf")) {
                char fmt[MAX_STRING], out[1024];
                if (!argc) return string_value("");
                as_string(args[0], fmt);
                format_output(fmt, args + 1, argc - 1, out, sizeof out);
                return string_value(out);
            }
            if (seq(name, "length") || seq(name, "int") ||
                seq(name, "index") || seq(name, "tolower") ||
                seq(name, "toupper") || seq(name, "substr") ||
                seq(name, "split") || seq(name, "match") ||
                seq(name, "sub") || seq(name, "gsub") ||
                seq(name, "close") || seq(name, "fflush") ||
                seq(name, "sqrt") || seq(name, "exp") ||
                seq(name, "log") || seq(name, "sin") ||
                seq(name, "cos") || seq(name, "atan2") ||
                seq(name, "rand") || seq(name, "srand") ||
                seq(name, "system"))
                return call_builtin(name, args, argc);
            fi = find_function(name);
            return call_function(fi, args, argc);
        }
        if (accept('[')) {
            char key[MAX_KEY], subsep[MAX_STRING];
            Value index = parse_assignment();
            current_subsep(subsep);
            as_string(index, key);
            while (accept(',')) {
                char part[MAX_KEY], joined[MAX_KEY];
                int n, j;
                index = parse_assignment();
                as_string(index, part);
                scopy(joined, key, MAX_KEY);
                n = slen(joined);
                for (j = 0; subsep[j] && n < MAX_KEY - 1; j++)
                    joined[n++] = subsep[j];
                joined[n] = 0;
                for (j = 0; part[j] && n < MAX_KEY - 1; j++)
                    joined[n++] = part[j];
                joined[n] = 0;
                scopy(key, joined, MAX_KEY);
            }
            require(']');
            if (!execute_enabled) return empty_value();
            return get_element(name, key, 1);
        }
        return get_variable(name);
    }
    error_flag = 1;
    if (token.kind) lex_next();
    return v;
}

static Value parse_power(void);

static Value parse_unary(void) {
    Value v;
    int op = token.kind;
    if (op == TOK_INC || op == TOK_DEC) {
        int inc = op == TOK_INC;
        double n;
        lex_next();
        v = parse_unary();
        if (!v.ref_kind) error_flag = 1;
        n = as_number(v) + (inc ? 1 : -1);
        if (execute_enabled) assign_ref(v, number_value(n));
        return number_value(n);
    }
    if (op == '!' || op == '-' || op == '+') {
        lex_next();
        v = parse_unary();
        if (op == '!') return number_value(!truth(v));
        if (op == '-') return number_value(-as_number(v));
        return number_value(as_number(v));
    }
    v = parse_power();
    if (token.kind == TOK_INC || token.kind == TOK_DEC) {
        int inc = token.kind == TOK_INC;
        double n = as_number(v);
        lex_next();
        if (!v.ref_kind) error_flag = 1;
        else if (execute_enabled)
            assign_ref(v, number_value(n + (inc ? 1 : -1)));
        return number_value(n);
    }
    return v;
}

static Value parse_power(void) {
    Value a = parse_primary(), b;
    if (token.kind == TOK_INC || token.kind == TOK_DEC) {
        int inc = token.kind == TOK_INC;
        double n = as_number(a);
        lex_next();
        if (!a.ref_kind) error_flag = 1;
        else if (execute_enabled)
            assign_ref(a, number_value(n + (inc ? 1 : -1)));
        a = number_value(n);
    }
    if (accept('^')) {
        b = parse_unary();
        if (as_number(a) == 0 && as_number(b) < 0) error_flag = 1;
        else if (as_number(a) < 0 &&
                 (long)as_number(b) != as_number(b)) error_flag = 1;
        else {
            double x = as_number(a), y = as_number(b);
            if (x < 0) {
                long n = (long)y, i;
                double result = 1;
                for (i = 0; i < (n < 0 ? -n : n); i++) result *= -x;
                a = number_value(n < 0 ? 1 / result : result);
                if (n % 2) a.number = -a.number;
            } else if (x == 0) a = number_value(y == 0 ? 1 : 0);
            else a = number_value(exp_approx(y * log_approx(x)));
        }
    }
    return a;
}

static Value parse_multiply(void) {
    Value a = parse_unary(), b;
    int op;
    while (token.kind == '*' || token.kind == '/' || token.kind == '%') {
        op = token.kind;
        lex_next();
        b = parse_unary();
        if (op == '*') a = number_value(as_number(a) * as_number(b));
        else if (op == '/') {
            if (as_number(b) == 0) error_flag = 1;
            else a = number_value(as_number(a) / as_number(b));
        } else {
            if ((long)as_number(b) == 0) error_flag = 1;
            else a = number_value((long)as_number(a) % (long)as_number(b));
        }
    }
    return a;
}

static Value parse_add(void) {
    Value a = parse_multiply(), b;
    int op;
    while (token.kind == '+' || token.kind == '-') {
        op = token.kind;
        lex_next();
        b = parse_multiply();
        a = number_value(op == '+' ?
                         as_number(a) + as_number(b) :
                         as_number(a) - as_number(b));
    }
    return a;
}

static Value parse_concat(void) {
    Value a = parse_add(), b;
    char left[MAX_STRING], right[MAX_STRING], joined[MAX_STRING];
    int n, i;
    while (prec_start(token.kind)) {
        b = parse_add();
        as_string(a, left);
        as_string(b, right);
        n = slen(left);
        for (i = 0; right[i] && n < MAX_STRING - 1; i++)
            left[n++] = right[i];
        left[n] = 0;
        scopy(joined, left, MAX_STRING);
        a = string_value(joined);
    }
    return a;
}

static int compare_values(Value a, Value b) {
    char x[MAX_STRING], y[MAX_STRING];
    double nx, ny;
    if (a.kind == V_NUM && b.kind == V_NUM)
        return a.number < b.number ? -1 : a.number > b.number ? 1 : 0;
    as_string(a, x);
    as_string(b, y);
    if (number_string(x, &nx) && number_string(y, &ny))
        return nx < ny ? -1 : nx > ny ? 1 : 0;
    {
        int i = 0;
        while (x[i] && y[i] && x[i] == y[i]) i++;
        return x[i] == y[i] ? 0 : (x[i] < y[i] ? -1 : 1);
    }
}

static void pipe_unavailable(void) {
    puts("CMSAWK: command pipes need POPEN/PCLOSE; PDPCLIB lacks them");
    error_flag = 1;
}

static Value parse_compare(void) {
    Value a = parse_concat(), b;
    int op, cmp;
    while (token.kind == TOK_EQ || token.kind == TOK_NE ||
           token.kind == '<' || token.kind == '>' ||
           token.kind == TOK_LE || token.kind == TOK_GE ||
           token.kind == TOK_MATCH || token.kind == TOK_NMATCH ||
           token.kind == TOK_IN || token.kind == '|') {
        if (print_context &&
            (token.kind == '>' || token.kind == '|')) break;
        op = token.kind;
        lex_next();
        if (op == '|') {
            if (token.kind != TOK_ID || !seq(token.text, "getline")) {
                error_flag = 1;
                return number_value(0);
            }
            lex_next();
            if (token.kind == TOK_ID || token.kind == '$') parse_primary();
            if (execute_enabled) pipe_unavailable();
            return number_value(-1);
        }
        b = parse_concat();
        if (op == TOK_IN) {
            char key[MAX_KEY];
            as_string(a, key);
            a = number_value(b.kind == V_ARRAY && b.array_id >= 0 &&
                             array_item(b.array_id, key, 0) >= 0);
            continue;
        }
        cmp = compare_values(a, b);
        if (op == TOK_EQ) a = number_value(cmp == 0);
        else if (op == TOK_NE) a = number_value(cmp != 0);
        else if (op == '<') a = number_value(cmp < 0);
        else if (op == '>') a = number_value(cmp > 0);
        else if (op == TOK_LE) a = number_value(cmp <= 0);
        else if (op == TOK_GE) a = number_value(cmp >= 0);
        else {
            char pat[MAX_STRING], text[MAX_STRING];
            as_string(a, text);
            as_string(b, pat);
            cmp = regex_match(pat, text);
            a = number_value(op == TOK_MATCH ? cmp : !cmp);
        }
    }
    return a;
}

static Value parse_and(void) {
    Value a = parse_compare(), b;
    while (accept(TOK_AND)) {
        int old_enabled = execute_enabled;
        if (!truth(a)) execute_enabled = 0;
        b = parse_compare();
        execute_enabled = old_enabled;
        a = number_value(truth(a) && truth(b));
    }
    return a;
}

static Value parse_or(void) {
    Value a = parse_and(), b;
    while (accept(TOK_OR)) {
        int old_enabled = execute_enabled;
        if (truth(a)) execute_enabled = 0;
        b = parse_and();
        execute_enabled = old_enabled;
        a = number_value(truth(a) || truth(b));
    }
    return a;
}

static Value parse_conditional(void) {
    Value a = parse_or(), b, c;
    if (accept('?')) {
        int old_enabled = execute_enabled;
        if (!truth(a)) execute_enabled = 0;
        b = parse_assignment();
        execute_enabled = old_enabled;
        require(':');
        if (truth(a)) execute_enabled = 0;
        c = parse_assignment();
        execute_enabled = old_enabled;
        return truth(a) ? b : c;
    }
    return a;
}

static Value parse_assignment(void) {
    Value left = parse_conditional(), right;
    int op = token.kind;
    double a, b;
    if (op != '=' && op != TOK_ADD_EQ && op != TOK_SUB_EQ &&
        op != TOK_MUL_EQ && op != TOK_DIV_EQ && op != TOK_MOD_EQ)
        return left;
    lex_next();
    right = parse_assignment();
    if (!left.ref_kind) {
        error_flag = 1;
        return right;
    }
    if (op == '=') {
        if (execute_enabled) assign_ref(left, right);
    }
    else {
        a = as_number(left);
        b = as_number(right);
        if (op == TOK_ADD_EQ) a += b;
        else if (op == TOK_SUB_EQ) a -= b;
        else if (op == TOK_MUL_EQ) a *= b;
        else if (op == TOK_DIV_EQ) {
            if (b == 0) error_flag = 1;
            else a /= b;
        } else {
            if ((long)b == 0) error_flag = 1;
            else a = (long)a % (long)b;
        }
        right = number_value(a);
        if (execute_enabled) assign_ref(left, right);
    }
    return right;
}

static Value parse_expression(void) {
    return parse_assignment();
}

static int find_statement_end(int start);

static int append_output(char *out, int used, int cap, const char *text) {
    int i = 0;
    while (text[i] && used + i < cap - 1) {
        out[used + i] = text[i];
        i++;
    }
    out[used + i] = 0;
    return used + i;
}

static void format_output(const char *fmt, Value *args, int argc,
                          char *out, int cap) {
    int i = 0, used = 0, ai = 0, n, j, width, zero_flag;
    char spec[32], temp[256], text[MAX_STRING];
    char c;
    out[0] = 0;
    while (fmt[i] && used < cap - 1) {
        if (fmt[i] != '%') {
            temp[0] = fmt[i++];
            temp[1] = 0;
            used = append_output(out, used, cap, temp);
            continue;
        }
        i++;
        if (fmt[i] == '%') {
            used = append_output(out, used, cap, "%");
            i++;
            continue;
        }
        n = 0;
        spec[n++] = '%';
        while (fmt[i] && n < 28 &&
               (fmt[i] == '-' || fmt[i] == '+' || fmt[i] == ' ' ||
                fmt[i] == '#' || fmt[i] == '0' || is_digit(fmt[i]) ||
                fmt[i] == '.')) spec[n++] = fmt[i++];
        if (fmt[i] == 'l' && n < 29) spec[n++] = fmt[i++];
        c = fmt[i];
        if (!c) break;
        if (c == 's' || c == 'c' || c == 'd' || c == 'i' ||
            c == 'u' || c == 'x' || c == 'X' || c == 'o' ||
            c == 'f' || c == 'F' || c == 'e' || c == 'E' ||
            c == 'g' || c == 'G') {
            spec[n++] = c;
            spec[n] = 0;
            i++;
            if (ai >= argc) {
                used = append_output(out, used, cap, "");
                continue;
            }
            if (c == 's') {
                as_string(args[ai], text);
                sprintf(temp, spec, text);
            } else if (c == 'c') {
                sprintf(temp, spec, (int)as_number(args[ai]));
            } else if (c == 'd' || c == 'i' || c == 'u' ||
                       c == 'x' || c == 'X' || c == 'o') {
                if (n > 2 && spec[n - 2] == 'l')
                    sprintf(temp, spec, (long)as_number(args[ai]));
                else sprintf(temp, spec, (int)as_number(args[ai]));
            } else {
                sprintf(temp, spec, as_number(args[ai]));
            }
            zero_flag = 0;
            width = 0;
            for (j = 1; j < n && spec[j] != '.'; j++) {
                if (spec[j] == '0' && width == 0) zero_flag = 1;
                else if (is_digit(spec[j])) width = width * 10 +
                                                   spec[j] - '0';
            }
            if (zero_flag && c != 's' && c != 'c') {
                int first = temp[0] == '-' || temp[0] == '+' ? 1 : 0;
                while (temp[first] == ' ') temp[first++] = '0';
            }
            ai++;
            used = append_output(out, used, cap, temp);
        } else {
            for (j = 0; j < n && used < cap - 1; j++) {
                temp[0] = spec[j];
                temp[1] = 0;
                used = append_output(out, used, cap, temp);
            }
            if (fmt[i]) i++;
        }
    }
}

static void write_text(FILE *dest, const char *text) {
    if (dest) fputs(text, dest);
    else printf("%s", text);
}

static FILE *parse_output_target(int run) {
    Value name_value;
    char name[MAX_STRING];
    char mode;
    FILE *dest = 0;
    if (token.kind != '>' && token.kind != TOK_APPEND) return 0;
    mode = token.kind == TOK_APPEND ? 'a' : 'w';
    lex_next();
    print_context = 0;
    name_value = parse_assignment();
    as_string(name_value, name);
    if (run) {
        dest = open_io(name, mode);
        if (!dest) error_flag = 1;
    }
    return dest;
}

static void print_value(Value v, FILE *dest) {
    char text[MAX_STRING];
    as_string(v, text);
    write_text(dest, text);
}

static void print_statement(int run, int formatted) {
    Value args[MAX_PARAMS];
    int argc = 0, i, old_context = print_context;
    FILE *dest;
    print_context = 1;
    if (formatted) {
        if (accept('(')) {
            print_context = 0;
            if (token.kind != ')') {
                do {
                    if (argc < MAX_PARAMS) args[argc++] = parse_assignment();
                    else error_flag = 1;
                } while (accept(','));
            }
            require(')');
            print_context = 1;
        } else {
            do {
                if (argc < MAX_PARAMS) args[argc++] = parse_assignment();
                else error_flag = 1;
            } while (accept(','));
        }
        dest = parse_output_target(run);
        if (run && argc > 0) {
            char fmt[MAX_STRING], out[1024];
            as_string(args[0], fmt);
            format_output(fmt, args + 1, argc - 1, out, sizeof out);
            write_text(dest, out);
        }
        print_context = old_context;
        return;
    }
    if (accept('(')) {
        print_context = 0;
        if (token.kind != ')') {
            do {
                if (argc < MAX_PARAMS) args[argc++] = parse_assignment();
                else error_flag = 1;
            } while (accept(','));
        }
        require(')');
        print_context = 1;
    } else if (token.kind != TOK_SEMI && token.kind != '}' &&
        token.kind != '>' && token.kind != TOK_APPEND &&
        token.kind != 0) {
        do {
            if (argc < MAX_PARAMS) args[argc++] = parse_assignment();
            else error_flag = 1;
        } while (accept(','));
    } else {
        args[argc++] = field_value(0);
    }
    if (token.kind == '|') {
        lex_next();
        print_context = 0;
        parse_assignment();
        if (run) pipe_unavailable();
        print_context = old_context;
        return;
    }
    dest = parse_output_target(run);
    if (run) {
        int oi = find_global("OFS", 0);
        int ri = find_global("ORS", 0);
        char sep[MAX_STRING], end[MAX_STRING];
        if (oi >= 0 && globals[oi].value.kind != V_EMPTY)
            as_string(globals[oi].value, sep);
        else scopy(sep, " ", MAX_STRING);
        if (ri >= 0 && globals[ri].value.kind != V_EMPTY)
            as_string(globals[ri].value, end);
        else scopy(end, "\n", MAX_STRING);
        for (i = 0; i < argc; i++) {
            if (i) write_text(dest, sep);
            print_value(args[i], dest);
        }
        write_text(dest, end);
    }
    print_context = old_context;
}

static void skip_balanced(int left, int right) {
    int depth = 1;
    lex_next();
    while (token.kind && depth > 0) {
        if (token.kind == left) depth++;
        else if (token.kind == right) depth--;
        lex_next();
    }
}

static void skip_to_delimiter(int delimiter) {
    int parens = 0, brackets = 0;
    while (token.kind) {
        if (token.kind == delimiter && parens == 0 && brackets == 0) return;
        if (token.kind == '(') parens++;
        else if (token.kind == ')' && parens > 0) parens--;
        else if (token.kind == '[') brackets++;
        else if (token.kind == ']' && brackets > 0) brackets--;
        lex_next();
    }
}

static int find_statement_end(int start) {
    ParserState saved = save_parser();
    int end, body_end;
    set_parser(start);
    if (token.kind == '{') {
        skip_balanced('{', '}');
        end = token.start;
    } else if (token.kind == TOK_ID && seq(token.text, "if")) {
        lex_next();
        if (token.kind == '(') skip_balanced('(', ')');
        skip_semis();
        body_end = find_statement_end(token.start);
        set_parser(body_end);
        if (token.kind == TOK_ID && seq(token.text, "else")) {
            lex_next();
            skip_semis();
            end = find_statement_end(token.start);
        } else end = body_end;
    } else if (token.kind == TOK_ID &&
               (seq(token.text, "while") || seq(token.text, "for"))) {
        lex_next();
        if (token.kind == '(') skip_balanced('(', ')');
        skip_semis();
        end = find_statement_end(token.start);
    } else if (token.kind == TOK_ID && seq(token.text, "do")) {
        lex_next();
        skip_semis();
        body_end = find_statement_end(token.start);
        set_parser(body_end);
        skip_semis();
        if (token.kind == TOK_ID && seq(token.text, "while")) {
            lex_next();
            if (token.kind == '(') skip_balanced('(', ')');
            if (token.kind == TOK_SEMI) {
                lex_next();
                end = token.start;
            } else end = token.start;
        } else end = body_end;
    } else {
        while (token.kind && token.kind != TOK_SEMI && token.kind != '}')
            lex_next();
        if (token.kind == TOK_SEMI) lex_next();
        end = token.start;
    }
    restore_parser(saved);
    return end;
}

static Value parse_statement_impl(int run) {
    Value result = empty_value();
    int loop_end, cond_pos, inc_pos, body_start;
    int loop, aid, entry;
    char name[MAX_STRING], key[MAX_KEY];
    double cond;
    if (token.kind == TOK_SEMI) {
        lex_next();
        return result;
    }
    if (token.kind == '{') {
        lex_next();
        skip_semis();
        while (token.kind && token.kind != '}') {
            int enabled = run && flow_state == FLOW_NONE;
            parse_statement(enabled);
            skip_semis();
        }
        require('}');
        return result;
    }
    if (token.kind == TOK_ID && seq(token.text, "if")) {
        lex_next();
        require('(');
        result = parse_expression();
        require(')');
        skip_semis();
        cond = truth(result);
        parse_statement(run && cond);
        skip_semis();
        if (token.kind == TOK_ID && seq(token.text, "else")) {
            lex_next();
            skip_semis();
            parse_statement(run && !cond && flow_state == FLOW_NONE);
        }
        return result;
    }
    if (token.kind == TOK_ID && seq(token.text, "while")) {
        lex_next();
        require('(');
        cond_pos = token.start;
        skip_to_delimiter(')');
        require(')');
        skip_semis();
        body_start = token.start;
        loop_end = find_statement_end(body_start);
        loop = 0;
        while (run && !error_flag && loop++ < 100000) {
            set_parser(cond_pos);
            result = parse_expression();
            if (!truth(result)) break;
            set_parser(body_start);
            parse_statement(1);
            if (flow_state == FLOW_BREAK) {
                flow_state = FLOW_NONE;
                break;
            }
            if (flow_state == FLOW_CONTINUE) flow_state = FLOW_NONE;
            else if (flow_state != FLOW_NONE) break;
        }
        if (loop >= 100000) error_flag = 1;
        set_parser(loop_end);
        return result;
    }
    if (token.kind == TOK_ID && seq(token.text, "do")) {
        lex_next();
        skip_semis();
        body_start = token.start;
        loop_end = find_statement_end(body_start);
        loop = 0;
        do {
            set_parser(body_start);
            parse_statement(run);
            if (flow_state == FLOW_BREAK) {
                flow_state = FLOW_NONE;
                break;
            }
            if (flow_state == FLOW_CONTINUE) flow_state = FLOW_NONE;
            else if (flow_state != FLOW_NONE) break;
            set_parser(loop_end);
            if (!(token.kind == TOK_ID && seq(token.text, "while"))) {
                error_flag = 1;
                return result;
            }
            lex_next();
            require('(');
            result = parse_expression();
            require(')');
        } while (run && truth(result) && ++loop < 100000);
        if (loop >= 100000) error_flag = 1;
        accept(TOK_SEMI);
        return result;
    }
    if (token.kind == TOK_ID && seq(token.text, "for")) {
        lex_next();
        require('(');
        if (token.kind == TOK_ID) {
            ParserState mark = save_parser();
            scopy(name, token.text, MAX_STRING);
            lex_next();
            if (token.kind == TOK_IN) {
                lex_next();
                if (token.kind != TOK_ID) error_flag = 1;
                else {
                    char array_name[MAX_STRING];
                    AwkVar *av;
                    int scope, vi;
                    scopy(array_name, token.text, MAX_STRING);
                    lex_next();
                    require(')');
                    skip_semis();
                    body_start = token.start;
                    loop_end = find_statement_end(body_start);
                    av = resolve_var(array_name, 1, &scope, &vi);
                    aid = av ? ensure_array(av) : -1;
                    loop = 0;
                    for (entry = 0; run && aid >= 0 &&
                         entry < arrays[aid].count && loop++ < MAX_ITEMS;
                         entry++) {
                        if (!arrays[aid].item[entry].used) continue;
                        {
                            Value v = string_value(arrays[aid].item[entry].key);
                            Value l = get_variable(name);
                            assign_ref(l, v);
                        }
                        set_parser(body_start);
                        parse_statement(1);
                        if (flow_state == FLOW_BREAK) {
                            flow_state = FLOW_NONE;
                            break;
                        }
                        if (flow_state == FLOW_CONTINUE) flow_state = FLOW_NONE;
                        else if (flow_state != FLOW_NONE) break;
                    }
                    set_parser(loop_end);
                    return result;
                }
            }
            restore_parser(mark);
        }
        if (token.kind != TOK_SEMI) parse_expression();
        require(TOK_SEMI);
        cond_pos = token.start;
        skip_to_delimiter(TOK_SEMI);
        require(TOK_SEMI);
        inc_pos = token.start;
        skip_to_delimiter(')');
        require(')');
        skip_semis();
        body_start = token.start;
        loop_end = find_statement_end(body_start);
        loop = 0;
        while (run && !error_flag && loop++ < 100000) {
            set_parser(cond_pos);
            if (token.kind != TOK_SEMI) result = parse_expression();
            else result = number_value(1);
            if (!truth(result)) break;
            set_parser(body_start);
            parse_statement(1);
            if (flow_state == FLOW_BREAK) {
                flow_state = FLOW_NONE;
                break;
            }
            if (flow_state == FLOW_CONTINUE) flow_state = FLOW_NONE;
            else if (flow_state != FLOW_NONE) break;
            set_parser(inc_pos);
            if (token.kind != ')') parse_expression();
        }
        if (loop >= 100000) error_flag = 1;
        set_parser(loop_end);
        return result;
    }
    if (token.kind == TOK_ID &&
        (seq(token.text, "print") || seq(token.text, "printf"))) {
        int formatted = seq(token.text, "printf");
        lex_next();
        print_statement(run, formatted);
        return result;
    }
    if (token.kind == TOK_ID && seq(token.text, "next")) {
        lex_next();
        if (run) flow_state = FLOW_NEXT;
        return result;
    }
    if (token.kind == TOK_ID && seq(token.text, "exit")) {
        lex_next();
        if (token.kind != TOK_SEMI && token.kind != '}' && token.kind)
            result = parse_expression();
        if (run) flow_state = FLOW_EXIT;
        return result;
    }
    if (token.kind == TOK_ID && seq(token.text, "break")) {
        lex_next();
        if (run) flow_state = FLOW_BREAK;
        return result;
    }
    if (token.kind == TOK_ID && seq(token.text, "continue")) {
        lex_next();
        if (run) flow_state = FLOW_CONTINUE;
        return result;
    }
    if (token.kind == TOK_ID && seq(token.text, "return")) {
        lex_next();
        if (token.kind != TOK_SEMI && token.kind != '}' && token.kind)
            result = parse_expression();
        if (run && frame_depth > 0) {
            frames[frame_depth - 1].result = result;
            flow_state = FLOW_RETURN;
        }
        return result;
    }
    if (token.kind == TOK_ID && seq(token.text, "delete")) {
        AwkVar *var;
        int scope, vi;
        lex_next();
        if (token.kind != TOK_ID) { error_flag = 1; return result; }
        scopy(name, token.text, MAX_STRING);
        lex_next();
        var = resolve_var(name, 1, &scope, &vi);
        if (accept('[')) {
            Value idx = parse_assignment();
            char subsep[MAX_STRING];
            current_subsep(subsep);
            as_string(idx, key);
            while (accept(',')) {
                char part[MAX_KEY], joined[MAX_KEY];
                int n, k;
                idx = parse_assignment();
                as_string(idx, part);
                scopy(joined, key, MAX_KEY);
                n = slen(joined);
                for (k = 0; subsep[k] && n < MAX_KEY - 1; k++)
                    joined[n++] = subsep[k];
                joined[n] = 0;
                for (k = 0; part[k] && n < MAX_KEY - 1; k++)
                    joined[n++] = part[k];
                joined[n] = 0;
                scopy(key, joined, MAX_KEY);
            }
            require(']');
            if (run && var) {
                int array = ensure_array(var);
                int e = array_item(array, key, 0);
                if (e >= 0) arrays[array].item[e].used = 0;
            }
        } else if (run && var && var->array_id >= 0) {
            int e;
            for (e = 0; e < arrays[var->array_id].count; e++)
                arrays[var->array_id].item[e].used = 0;
            arrays[var->array_id].count = 0;
        }
        return result;
    }
    result = parse_expression();
    return result;
}

static Value parse_statement(int run) {
    int old_enabled = execute_enabled;
    Value result;
    execute_enabled = old_enabled && run;
    result = parse_statement_impl(execute_enabled);
    execute_enabled = old_enabled;
    return result;
}

static int load_program(const char *fileid) {
    FILE *f;
    char line[MAX_RECORD];
    int i, n;
    f = fopen(fileid, "r");
    if (!f) return 0;
    source_length = 0;
    while (fgets(line, sizeof line, f)) {
        n = slen(line);
        if (source_length + n + 1 >= SOURCE_SIZE) {
            fclose(f);
            return 0;
        }
        for (i = 0; i < n; i++) source[source_length++] = line[i];
        if (!n || line[n - 1] != '\n') source[source_length++] = '\n';
    }
    source[source_length] = 0;
    classify_newlines();
    return fclose(f) == 0;
}

static int parse_function(void) {
    AwkFunction *fn;
    char name[MAX_STRING];
    int start, end;
    lex_next();
    if (token.kind != TOK_ID || function_count >= MAX_FUNCS) return 0;
    scopy(name, token.text, MAX_STRING);
    if (find_function(name) >= 0) return 0;
    fn = &functions[function_count++];
    fn->used = 1;
    scopy(fn->name, name, MAX_STRING);
    fn->param_count = 0;
    lex_next();
    if (!require('(')) return 0;
    if (token.kind != ')') {
        do {
            if (token.kind != TOK_ID || fn->param_count >= MAX_PARAMS)
                return 0;
            scopy(fn->param[fn->param_count++], token.text, MAX_STRING);
            lex_next();
        } while (accept(','));
    }
    if (!require(')')) return 0;
    skip_semis();
    if (token.kind != '{') return 0;
    start = token.start;
    end = find_statement_end(start);
    fn->body_start = start;
    fn->body_end = end;
    set_parser(end);
    skip_semis();
    return 1;
}

static int parse_rule_source(void) {
    AwkRule *r;
    int body_start, body_end, start, p, escaped, old_enabled;
    char c;
    if (rule_count >= MAX_RULES) return 0;
    r = &rules[rule_count];
    r->kind = RULE_ALL;
    r->pattern_start = -1;
    r->pattern[0] = 0;
    if (token.kind == TOK_ID && seq(token.text, "BEGIN")) {
        r->kind = RULE_BEGIN;
        lex_next();
        skip_semis();
    } else if (token.kind == TOK_ID && seq(token.text, "END")) {
        r->kind = RULE_END;
        lex_next();
        skip_semis();
    } else if (token.kind == '{') {
        r->kind = RULE_ALL;
    } else if (token.kind == '/') {
        r->kind = RULE_REGEX;
        start = token.start + 1;
        p = start;
        escaped = 0;
        while (p < source_length) {
            c = source[p++];
            if (!escaped && c == '/') break;
            if (escaped) escaped = 0;
            else if (c == '\\') escaped = 1;
        }
        if (p > source_length || source[p - 1] != '/') return 0;
        token_text(&token, source + start, p - start - 1);
        scopy(r->pattern, token.text, MAX_STRING);
        set_parser(p);
        skip_semis();
    } else {
        r->kind = RULE_EXPR;
        r->pattern_start = token.start;
        old_enabled = execute_enabled;
        execute_enabled = 0;
        parse_expression();
        execute_enabled = old_enabled;
        skip_semis();
    }
    if (token.kind != '{') return 0;
    body_start = token.start;
    body_end = find_statement_end(body_start);
    r->body_start = body_start;
    r->body_end = body_end;
    rule_count++;
    set_parser(body_end);
    skip_semis();
    return 1;
}

static int parse_program(void) {
    set_parser(0);
    rule_count = 0;
    function_count = 0;
    while (token.kind) {
        skip_semis();
        if (!token.kind) break;
        if (token.kind == TOK_ID && seq(token.text, "function")) {
            if (!parse_function()) return 0;
        } else if (!parse_rule_source()) {
            return 0;
        }
    }
    return !error_flag;
}

static int rule_matches(const AwkRule *r) {
    Value v;
    ParserState saved;
    int yes;
    if (r->kind == RULE_ALL) return 1;
    if (r->kind == RULE_BEGIN || r->kind == RULE_END) return 0;
    if (r->kind == RULE_REGEX) return regex_match(r->pattern, record);
    saved = save_parser();
    set_parser(r->pattern_start);
    v = parse_expression();
    yes = truth(v);
    restore_parser(saved);
    return yes;
}

static int execute_rule(const AwkRule *r) {
    set_parser(r->body_start);
    parse_statement(1);
    return !error_flag;
}

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

int main(int argc, char **argv) {
    char script_id[32], input_id[32], line[MAX_RECORD];
    AwkVar *argv_var;
    int i, run_data, data_count, argv_index, arg_index;
    if (argc < 7 || (argc - 4) % 3 != 0) {
        puts("Usage: CMSAWK scriptFN scriptFT scriptFM"
             " dataFN dataFT dataFM ...");
        return 4;
    }
    make_file_id(script_id, argv[1], argv[2], argv[3]);
    data_count = (argc - 4) / 3;
    if (data_count > MAX_INPUT_FILES) {
        puts("CMSAWK: too many input files");
        return 4;
    }
    if (!load_program(script_id)) {
        puts("CMSAWK: cannot read script or script too large");
        return 8;
    }
    if (!parse_program()) {
        puts("CMSAWK: invalid script or interpreter limit exceeded");
        return 4;
    }
    global_count = 0;
    array_count = 0;
    frame_depth = 0;
    flow_state = FLOW_NONE;
    nr = 0;
    fnr = 0;
    nf = 0;
    error_flag = 0;
    input_index = 1;
    {
        int vi = find_global("ARGV", 1);
        if (vi < 0) return 8;
        argv_var = &globals[vi];
        argv_var->array_id = new_array();
        argv_index = argv_var->array_id;
    }
    set_global("ARGC", number_value(data_count + 1));
    set_array_string(argv_index, 0, "CMSAWK");
    for (i = 0; i < data_count; i++) {
        arg_index = 4 + i * 3;
        make_file_id(input_id, argv[arg_index], argv[arg_index + 1],
                     argv[arg_index + 2]);
        set_array_string(argv_index, i + 1, input_id);
    }
    set_global("FILENAME", string_value(""));
    run_data = 1;
    data_stream = 0;
    for (i = 0; i < rule_count; i++) {
        if (rules[i].kind == RULE_BEGIN) {
            flow_state = FLOW_NONE;
            if (!execute_rule(&rules[i])) break;
            if (flow_state == FLOW_EXIT) {
                run_data = 0;
                break;
            }
            if (flow_state != FLOW_NONE) {
                error_flag = 1;
                break;
            }
        }
    }
    if (run_data && !error_flag) {
        while (next_main_line(line)) {
            scopy(record, line, MAX_RECORD);
            record_length = slen(record);
            if (record_length >= MAX_RECORD - 1) {
                error_flag = 1;
                break;
            }
            split_fields();
            flow_state = FLOW_NONE;
            for (i = 0; i < rule_count; i++) {
                if (rules[i].kind == RULE_ALL ||
                    rules[i].kind == RULE_REGEX ||
                    rules[i].kind == RULE_EXPR) {
                    if (rule_matches(&rules[i])) {
                        if (!execute_rule(&rules[i])) {
                            error_flag = 1;
                            break;
                        }
                    }
                    if (flow_state == FLOW_NEXT ||
                        flow_state == FLOW_EXIT) break;
                }
            }
            if (flow_state == FLOW_NEXT) flow_state = FLOW_NONE;
            else if (flow_state == FLOW_EXIT) break;
            if (error_flag) break;
        }
    }
    if (data_stream) fclose(data_stream);
    data_stream = 0;
    for (i = 0; i < rule_count; i++) {
        if (rules[i].kind == RULE_END) {
            flow_state = FLOW_NONE;
            if (!execute_rule(&rules[i])) error_flag = 1;
        }
    }
    close_all_io();
    if (error_flag) {
        puts("CMSAWK: runtime error or resource limit exceeded");
        return 8;
    }
    return 0;
}
