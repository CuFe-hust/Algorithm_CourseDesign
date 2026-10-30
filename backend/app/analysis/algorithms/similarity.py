"""Token-level code similarity: normalise, fingerprint with winnowing, compare.

Pure functions only: no web, database, filesystem or global randomness. The
method is the Winnowing algorithm used by MOSS (Schleimer, Wilkerson & Aiken,
SIGMOD 2003): reduce the source to a normalised token stream, hash every k-gram,
keep the minimum hash of each sliding window of ``w`` windows, and treat the
retained fingerprints as the document's sketch.

Two properties matter for a course setting:

* Renaming identifiers, reordering independent statements and editing comments
  do not change the sketch, so cosmetic rewrites do not hide a copy.
* Every fingerprint remembers its source line, so the result can quote the
  matched line ranges as evidence instead of returning an unexplained number.

The cost is linear in the token count plus the cost of counting shared
fingerprints through an inverted index, which avoids comparing every pair of
sketch sets directly.
"""

from __future__ import annotations

import builtins
import hashlib
import keyword
import re
import tokenize
from dataclasses import dataclass, field
from io import StringIO

# Algorithm parameters. They are sent inside the analysis payload so a stored
# snapshot reproduces exactly the same sketch and the same pairs.
KGRAM = 12
WINDOW = 4
BASELINE = 0x9E3779B97F4A7C15
MASK = (1 << 64) - 1
MAX_SPANS = 20
MAX_PAIRS = 500
DEFAULT_MINIMUM_TOKENS = 40
DEFAULT_THRESHOLD = 0.5

PYTHON_LANGUAGES = {'python', 'python3', 'python3.11', 'python3.12', 'python3.13', 'python3.14', 'py'}
C_LIKE_LANGUAGES = {'c', 'c17', 'gcc', 'cpp', 'c++', 'cpp17', 'g++', 'cc', 'java', 'java17', 'openjdk'}

_IDENTIFIER = re.compile(r'[A-Za-z_][A-Za-z_0-9]*')
_NUMBER = re.compile(r'\d+(?:\.\d+)?(?:[eE][+-]?\d+)?[fFlLuU]*|0[xX][0-9A-Fa-f]+')
_OPERATOR = re.compile(r'>>=|<<=|->\*|\.\.\.|::|->|\+\+|--|&&|\|\||==|!=|<=|>=|\+=|-=|\*=|/=|%=|&=|\|=|\^=|<<|>>'
                       r'|[+\-*/%&|^!~=<>?:;,.(){}\[\]]')
_KEYWORDS = frozenset({
    # C / C++
    'auto', 'break', 'case', 'char', 'const', 'continue', 'default', 'do', 'double', 'else', 'enum',
    'extern', 'float', 'for', 'goto', 'if', 'inline', 'int', 'long', 'register', 'restrict', 'return',
    'short', 'signed', 'sizeof', 'static', 'struct', 'switch', 'typedef', 'union', 'unsigned', 'void',
    'volatile', 'while', 'bool', 'catch', 'class', 'delete', 'explicit', 'false', 'friend', 'namespace',
    'new', 'operator', 'private', 'protected', 'public', 'template', 'this', 'throw', 'true', 'try',
    'typename', 'using', 'virtual', 'nullptr',
    # Java
    'abstract', 'assert', 'boolean', 'byte', 'extends', 'final', 'finally', 'implements', 'import',
    'instanceof', 'interface', 'native', 'package', 'strictfp', 'super', 'synchronized', 'throws',
    'transient', 'null', 'var', 'record', 'yield',
})


# Builtins and standard-library entry points keep their names: they decide what
# the program actually does, so keeping them makes a fingerprint more specific
# than the classic "every identifier becomes V" reduction.
PYTHON_BUILTINS = frozenset(dir(builtins))
C_LIBRARY = frozenset({
    'printf', 'scanf', 'puts', 'gets', 'cout', 'cin', 'cerr', 'endl', 'vector', 'string', 'map',
    'set', 'queue', 'stack', 'pair', 'sort', 'reverse', 'push_back', 'push', 'pop', 'front', 'back',
    'size', 'begin', 'end', 'first', 'second', 'length', 'substr', 'max', 'min', 'abs', 'swap',
    'malloc', 'free', 'memset', 'memcpy', 'strlen', 'strcmp', 'strcpy', 'fopen', 'fclose', 'fgets',
    'fprintf', 'fscanf', 'main', 'System', 'out', 'println', 'print', 'Scanner', 'nextInt',
    'nextLine', 'BufferedReader', 'InputStreamReader', 'ArrayList', 'HashMap', 'HashSet',
    'StringBuilder', 'Integer', 'Long', 'Math', 'Arrays', 'Collections', 'String', 'List', 'Map',
})


class TokenizationError(ValueError):
    """The source could not be reduced to tokens; the submission is skipped."""


@dataclass(frozen=True)
class Token:
    kind: str
    text: str
    line: int


@dataclass(frozen=True)
class Fingerprint:
    value: int
    position: int  # index of the first token of the k-gram
    line: int      # line of the first token
    end_line: int  # line of the last token


@dataclass
class Sketch:
    answer_key: str
    language: str | None
    token_count: int
    fingerprints: list[Fingerprint] = field(default_factory=list)
    positions: dict[int, list[tuple[int, int, int]]] = field(default_factory=dict)

    @property
    def hash_set(self) -> set[int]:
        return set(self.positions)


def normalise_language(language: str | None) -> str:
    if not language:
        return ''
    value = language.strip().lower()
    if value in PYTHON_LANGUAGES:
        return 'python'
    if value in C_LIKE_LANGUAGES:
        return 'c-like'
    return ''


def tokenize_python(source: str) -> list[Token]:
    """Reduce Python source to structural tokens.

    Comments, blank lines, indentation and encoding markers are dropped.
    Identifiers collapse to ``ID``, literals to ``NUM``/``STR``, keywords and
    operators keep their own text. Only the operator/keyword skeleton survives,
    which is what makes renaming ineffective as an evasion.
    """
    tokens: list[Token] = []
    try:
        stream = tokenize.generate_tokens(StringIO(source).readline)
        for info in stream:
            kind = info.type
            line = info.start[0]
            if kind == tokenize.NAME:
                # Identifiers collapse to one structural token: renaming a
                # variable cannot change the sketch, while keywords (which
                # define control flow) keep their own text.
                if keyword.iskeyword(info.string):
                    tokens.append(Token(kind='KW', text=info.string, line=line))
                elif info.string in PYTHON_BUILTINS:
                    tokens.append(Token(kind='BUILTIN', text=info.string, line=line))
                else:
                    tokens.append(Token(kind='ID', text='ID', line=line))
            elif kind == tokenize.NUMBER:
                tokens.append(Token(kind='NUM', text='NUM', line=line))
            elif kind in (tokenize.STRING, getattr(tokenize, 'FSTRING_START', -1),
                          getattr(tokenize, 'FSTRING_MIDDLE', -1), getattr(tokenize, 'FSTRING_END', -1)):
                tokens.append(Token(kind='STR', text='STR', line=line))
            elif kind == tokenize.OP:
                tokens.append(Token(kind='OP', text=info.string, line=line))
            elif kind == tokenize.ERRORTOKEN:
                if info.string.strip():
                    tokens.append(Token(kind='OP', text=info.string, line=line))
    except IndentationError:
        # Similarity is a lexical measure, so a submission whose indentation is
        # inconsistent still has a token stream. Fall back to a line-oriented
        # lexer instead of refusing to compare it.
        return tokenize_c_like(source)
    except (tokenize.TokenError, SyntaxError) as error:
        raise TokenizationError(str(error)) from None
    return tokens


def _strip_comments_and_strings(source: str) -> str:
    """Blank out comments and string literals in one left-to-right pass.

    A single pass is required for two reasons found in review:

    * Substituting block comments before strings let a literal ``"/*"`` open a
      comment that swallowed the rest of the file, so two extra print statements
      were enough to drop a 152-token program to 18 tokens and evade comparison
      entirely. Scanning left to right knows whether ``/*`` is inside a literal.
    * Each replaced comment keeps its newlines, so every token keeps its real
      line number; replacing a multi-line comment with one space shifted every
      following line.
    """
    out: list[str] = []
    index = 0
    length = len(source)
    while index < length:
        char = source[index]
        if char == '/' and index + 1 < length and source[index + 1] == '/':
            while index < length and source[index] != '\n':
                index += 1
            continue
        if char == '#' and not source.startswith('#include', index):
            while index < length and source[index] != '\n':
                index += 1
            continue
        if char == '/' and index + 1 < length and source[index + 1] == '*':
            index += 2
            while index + 1 < length and not (source[index] == '*' and source[index + 1] == '/'):
                if source[index] == '\n':
                    out.append('\n')
                index += 1
            index = min(length, index + 2)
            out.append(' ')
            continue
        if char in '"\'':
            quote = char
            index += 1
            while index < length:
                if source[index] == '\\' and index + 1 < length:
                    index += 2
                    continue
                if source[index] == quote:
                    index += 1
                    break
                if source[index] == '\n':
                    break
                index += 1
            out.append('STRTOKEN ')
            continue
        out.append(char)
        index += 1
    return ''.join(out)


def tokenize_c_like(source: str) -> list[Token]:
    """Lexical token stream for C/C++/Java.

    This is deliberately lexical: no parser is bundled for these languages, so
    the result is a structural approximation that still defeats simple renaming
    and formatting changes.
    """
    text = _strip_comments_and_strings(source)
    tokens: list[Token] = []
    line = 1
    index = 0
    length = len(text)
    while index < length:
        char = text[index]
        if char == '\n':
            line += 1
            index += 1
            continue
        if char in ' \t\r\f\v':
            index += 1
            continue
        if text.startswith('STRTOKEN', index):
            tokens.append(Token(kind='STR', text='STR', line=line))
            index += len('STRTOKEN')
            continue
        match = _IDENTIFIER.match(text, index)
        if match:
            word = match.group(0)
            if word in _KEYWORDS:
                tokens.append(Token(kind='KW', text=word, line=line))
            elif word in C_LIBRARY:
                tokens.append(Token(kind='BUILTIN', text=word, line=line))
            else:
                tokens.append(Token(kind='ID', text='ID', line=line))
            index = match.end()
            continue
        match = _NUMBER.match(text, index)
        if match:
            tokens.append(Token(kind='NUM', text='NUM', line=line))
            index = match.end()
            continue
        match = _OPERATOR.match(text, index)
        if match:
            tokens.append(Token(kind='OP', text=match.group(0), line=line))
            index = match.end()
            continue
        # Unknown character: keep it as an operator so the structure is not silently lost.
        tokens.append(Token(kind='OP', text=char, line=line))
        index += 1
    return tokens


def tokenize_source(source: str, language: str | None) -> list[Token]:
    family = normalise_language(language)
    if family == 'python':
        return tokenize_python(source)
    if family == 'c-like':
        return tokenize_c_like(source)
    raise TokenizationError('unsupported-language')


def _token_ids(tokens: list[Token]) -> list[int]:
    """Map token texts to stable 64-bit identifiers.

    ``hash()`` on strings is salted per process, so it can never be used here:
    a stored snapshot must reproduce the same sketch in a later process.
    """
    cache: dict[str, int] = {}
    ids: list[int] = []
    for token in tokens:
        key = token.kind + '\x00' + token.text
        value = cache.get(key)
        if value is None:
            digest = hashlib.blake2b(key.encode('utf-8'), digest_size=8).digest()
            value = int.from_bytes(digest, 'big') or 1
            cache[key] = value
        ids.append(value)
    return ids


def _kgram_hashes(ids: list[int], k: int) -> list[int]:
    if len(ids) < k:
        return []
    power = pow(BASELINE, k - 1, 1 << 64)
    value = 0
    for index in range(k):
        value = (value * BASELINE + ids[index]) & MASK
    hashes = [value]
    for index in range(k, len(ids)):
        value = ((value - ids[index - k] * power) * BASELINE + ids[index]) & MASK
        hashes.append(value)
    return hashes


def winnow(hashes: list[int], window: int) -> list[tuple[int, int]]:
    """Return ``(hash, rightmost_index)`` for each selected window minimum.

    Records the rightmost occurrence of the minimum, matching the reference
    implementation, so the same input always produces the same positions.
    """
    if not hashes:
        return []
    if window >= len(hashes):
        window = len(hashes)
    selected: list[tuple[int, int]] = []
    # Monotonic deque of (index, hash): smallest hash first.
    from collections import deque
    queue: deque[tuple[int, int]] = deque()
    last = None
    for index, value in enumerate(hashes):
        while queue and queue[-1][1] > value:
            queue.pop()
        queue.append((index, value))
        while queue[0][0] <= index - window:
            queue.popleft()
        if index + 1 >= window:
            candidate = (queue[0][1], queue[0][0])
            if candidate != last:
                selected.append(candidate)
                last = candidate
    return selected


def sketch(answer_key: str, source: str, language: str | None, *,
           k: int = KGRAM, window: int = WINDOW) -> Sketch:
    tokens = tokenize_source(source, language)
    ids = _token_ids(tokens)
    hashes = _kgram_hashes(ids, k)
    selected = winnow(hashes, window)
    fingerprints: list[Fingerprint] = []
    positions: dict[int, list[tuple[int, int, int]]] = {}
    for value, index in selected:
        line = tokens[index].line
        end_line = tokens[index + k - 1].line
        fingerprints.append(Fingerprint(value=value, position=index, line=line, end_line=end_line))
        positions.setdefault(value, []).append((index, line, end_line))
    return Sketch(answer_key=answer_key, language=language, token_count=len(tokens),
                  fingerprints=fingerprints, positions=positions)


@dataclass(frozen=True)
class _Anchor:
    left_pos: int
    right_pos: int
    left_line: int
    left_end: int
    right_line: int
    right_end: int


def _merge_spans(anchors: list[_Anchor], k: int) -> list[dict[str, int]]:
    """Group matched k-gram anchors into line ranges on both sides.

    An anchor is one shared fingerprint, so it covers ``k`` tokens starting at
    ``left_pos``/``right_pos``. Two anchors belong to the same span when both
    sides advance by at most ``k`` tokens; a deleted or moved statement breaks
    the span instead of merging everything into one misleading range.

    Both bounds matter. Anchors are sorted by the left position only, so without
    the lower bound a run of matches that moves backwards on the right side -- the
    classic "cut the last lines and paste them at the top" edit -- was merged into
    a single span whose reported range did not cover the tokens it claimed.
    """
    if not anchors:
        return []
    ordered = sorted(anchors, key=lambda anchor: (anchor.left_pos, anchor.right_pos))
    spans: list[dict[str, int]] = []
    first = last = ordered[0]
    run = 1
    run_best = 1

    def flush(current_first: _Anchor, current_last: _Anchor, best_run: int) -> None:
        spans.append({
            'left_start_line': current_first.left_line,
            'left_end_line': max(current_first.left_end, current_last.left_end),
            'right_start_line': current_first.right_line,
            'right_end_line': max(current_first.right_end, current_last.right_end),
            'matched_tokens': (current_last.left_pos - current_first.left_pos) + k,
            'run_tokens': best_run + k - 1,
        })

    for anchor in ordered[1:]:
        left_step = anchor.left_pos - last.left_pos
        right_step = anchor.right_pos - last.right_pos
        if -k <= left_step <= k and -k <= right_step <= k:
            last = anchor
            run += 1
            run_best = max(run_best, run)
            continue
        flush(first, last, run_best)
        first = last = anchor
        run = run_best = 1
    flush(first, last, run_best)
    return spans


def _spans_for_pair(left: Sketch, right: Sketch, shared: set[int], k: int) -> tuple[list[dict[str, int]], int]:
    """Return bounded line-range evidence plus the longest continuous run."""
    anchor_candidates: list[_Anchor] = []
    for value in shared:
        left_positions = left.positions.get(value) or []
        right_positions = right.positions.get(value) or []
        if not left_positions or not right_positions:
            continue
        # Pair the first occurrence on each side; repeated occurrences are
        # counted once so a loop body is not multiplied by its iteration count.
        l_index, l_line, l_end = left_positions[0]
        r_index, r_line, r_end = right_positions[0]
        anchor_candidates.append(_Anchor(l_index, r_index, l_line, l_end, r_line, r_end))
    spans = _merge_spans(anchor_candidates, k)
    longest = max((span['run_tokens'] for span in spans), default=0)
    spans.sort(key=lambda span: (-span['matched_tokens'], span['left_start_line']))
    return spans[:MAX_SPANS], longest


@dataclass
class ItemResult:
    pairs: list[dict]
    clusters: list[dict]
    insufficient: list[dict]
    submission_count: int
    method: str = 'winnowing_token'
    # True when the evidence list hit ``MAX_PAIRS``. The cluster list is built
    # from the full threshold graph, so a truncated result still reports every
    # similar group; only the per-pair evidence is cut.
    pairs_truncated: bool = False


def compare(item: list[dict], *, minimum_tokens: int = DEFAULT_MINIMUM_TOKENS,
            threshold: float = DEFAULT_THRESHOLD, k: int = KGRAM,
            window: int = WINDOW, max_pairs: int = MAX_PAIRS) -> ItemResult:
    """Compare submissions of one assignment item.

    ``item`` is a list of ``{"answer_key", "content", "language"}``. The return
    value uses only stable answer keys; joining names and student numbers is the
    caller's projection job.
    """
    sketches: list[Sketch] = []
    insufficient: list[dict] = []
    for entry in sorted(item, key=lambda row: str(row.get('answer_key'))):
        answer_key = str(entry.get('answer_key'))
        language = entry.get('language')
        if normalise_language(language) == '':
            insufficient.append({'answer_key': answer_key, 'reason': 'NOT_A_PROGRAMMING_LANGUAGE',
                                 'tokens': 0})
            continue
        try:
            item_sketch = sketch(answer_key, str(entry.get('content') or ''), language, k=k, window=window)
        except TokenizationError as error:
            insufficient.append({'answer_key': answer_key, 'reason': 'TOKENIZATION_FAILED',
                                 'tokens': 0, 'detail': str(error)[:120]})
            continue
        if item_sketch.token_count < minimum_tokens:
            insufficient.append({'answer_key': answer_key, 'reason': 'INSUFFICIENT_TOKENS',
                                 'tokens': item_sketch.token_count})
            continue
        sketches.append(item_sketch)
    if len(sketches) < 2:
        return ItemResult(pairs=[], clusters=[], insufficient=insufficient,
                          submission_count=len(sketches))

    # Inverted index: fingerprint -> sketch indexes. Only fingerprints shared by
    # two sketches are relevant, and each shared fingerprint is counted once per
    # pair by walking the index bucket.
    index: dict[int, list[int]] = {}
    for position, item_sketch in enumerate(sketches):
        for value in item_sketch.positions:
            index.setdefault(value, []).append(position)
    shared_counts: dict[tuple[int, int], int] = {}
    for value, owners in index.items():
        if len(owners) < 2:
            continue
        for first in range(len(owners)):
            for second in range(first + 1, len(owners)):
                key = (owners[first], owners[second])
                shared_counts[key] = shared_counts.get(key, 0) + 1

    pairs: list[dict] = []
    union_sizes: dict[tuple[int, int], int] = {}
    for (first, second), shared in shared_counts.items():
        left = sketches[first]
        right = sketches[second]
        left_size = len(left.positions)
        right_size = len(right.positions)
        containment_left = shared / left_size if left_size else 0.0
        containment_right = shared / right_size if right_size else 0.0
        similarity = max(containment_left, containment_right)
        union_sizes[(first, second)] = left_size + right_size - shared
        if similarity + 1e-12 < threshold:
            continue
        span_rows, longest = _spans_for_pair(left, right, set(left.positions) & set(right.positions), k)
        pairs.append({
            'left_key': left.answer_key, 'right_key': right.answer_key,
            'similarity': _ratio(similarity),
            'containment_left': _ratio(containment_left),
            'containment_right': _ratio(containment_right),
            'jaccard': _ratio(shared / union_sizes[(first, second)]) if union_sizes[(first, second)] else '0',
            'shared_fingerprints': shared,
            'left_fingerprints': left_size, 'right_fingerprints': right_size,
            # Token counts let a reader judge evidence strength: on short,
            # formulaic programs independent work also converges (measured 0.54
            # to 1.00 below ~120 tokens with a shared classroom idiom), so a high
            # score between two 60-token submissions says little.
            'left_tokens': left.token_count, 'right_tokens': right.token_count,
            'matched_tokens': round(similarity * max(left.token_count, right.token_count)),
            'longest_run_tokens': longest,
            'matching_spans': span_rows,
        })
    pairs.sort(key=lambda row: (-float(row['similarity']), row['left_key'], row['right_key']))
    truncated = len(pairs) > max_pairs
    pairs = pairs[:max_pairs]

    # Clusters use the full threshold graph, not the truncated evidence list.
    parent: dict[int, int] = {index: index for index in range(len(sketches))}

    def find(node: int) -> int:
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    def union(left: int, right: int) -> None:
        root_left, root_right = find(left), find(right)
        if root_left != root_right:
            parent[max(root_left, root_right)] = min(root_left, root_right)

    edge_weight: dict[tuple[int, int], float] = {}
    for (first, second), shared in shared_counts.items():
        left, right = sketches[first], sketches[second]
        similarity = max(shared / len(left.positions), shared / len(right.positions))
        if similarity + 1e-12 < threshold:
            continue
        union(first, second)
        edge_weight[(min(first, second), max(first, second))] = similarity
    groups: dict[int, list[int]] = {}
    for index in range(len(sketches)):
        groups.setdefault(find(index), []).append(index)
    clusters = []
    for members in groups.values():
        if len(members) < 3:
            continue
        # The union-find is single-link, so a cluster is a connected component and
        # not necessarily a clique: A~B and B~C place C in the group even when A
        # and C share almost nothing. Review measured a real 8-member cluster where
        # only 8 of the 28 member pairs reached the threshold, so the report states
        # how many pairs actually qualify instead of letting "size" imply a clique.
        ordered = sorted(members)
        member_edges = [edge_weight[(first, second)]
                        for i, first in enumerate(ordered)
                        for second in ordered[i + 1:]
                        if (first, second) in edge_weight]
        total_pairs = len(members) * (len(members) - 1) // 2
        clusters.append({
            'member_keys': [sketches[index].answer_key for index in ordered],
            'size': len(members),
            'max_similarity': _ratio(max(member_edges, default=0.0)),
            'min_similarity': _ratio(min(member_edges, default=0.0)),
            'qualifying_pairs': len(member_edges),
            'total_pairs': total_pairs,
        })
    clusters.sort(key=lambda row: (-row['size'], -float(row['max_similarity'])))

    return ItemResult(pairs=pairs, clusters=clusters, insufficient=insufficient,
                      submission_count=len(sketches), pairs_truncated=truncated)


def _ratio(value: float) -> str:
    bounded = max(0.0, min(1.0, float(value)))
    return f'{bounded:.6f}'


def estimate_tokens(source: str, language: str | None) -> int:
    """Cheap token count used for the public "too short to compare" reason."""
    try:
        return len(tokenize_source(source, language))
    except TokenizationError:
        return 0
